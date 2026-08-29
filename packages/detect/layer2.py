"""
Source: Day-6 Plan §3.1 / §3.2 / §3.10 -- `Layer2Engine`, the in-process
coordinator that owns the per-merchant Poisson CUSUM (with tau_flag-gated
bucket accounting) and the per-entity distinct-card drift SPRT, and produces
one `DetectorSignal` per scored attempt for the incident state machine.

Decision 45's deferred question -- WHERE n_t is counted -- is answered here:
the gated count and S_t are maintained IN-PROCESS on ScorerState (exactly as
ThreatRollup already is), never as a second Redis write, so the
one-round-trip invariant and the p99<5ms budget both hold. The raw Lua
bucket counter (ScorePathSnapshot.cusum_bucket_count) is left untouched and
is available only as a cross-check.

Bucket accounting (the M8 "pure fold over the prefix" contract):
  * S_t is COMMITTED for a bucket only once a later bucket's attempt
    arrives (or `flush()` is called). Gap buckets are committed with n_t=0,
    so an empty bucket decays S_t by exactly (lam1 - lam0).
  * The still-filling bucket is folded PROVISIONALLY on every attempt
    (`cusum.peek`), so the first attempt that drives S_live past h is the
    fire point -- monotone within a bucket, deterministic given the prefix.
  * `regime_for(bucket_index)` commits every bucket strictly before
    `bucket_index` and returns the committed alarm state. The serving path
    calls it BEFORE the model so the alarm regime that picks the prior is a
    function of buckets that are already fully scored -- no circularity
    between p_calibrated and the tau_flag gate.

PURE of I/O and wall clock; imports no `eval`, no label source.
`reset()` clears every dict (wired into ReplayDriver.reset()).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from packages.detect.baseline import StoreBaseline
from packages.detect.cusum import CusumParams, CusumStep, PoissonCusum, baseline_lambda0, hour_of_day
from packages.detect.drift import DriftParams, DriftStep, SequentialDrift
from packages.detect.episode import DetectorSignal
from packages.detect.policy import EntityKey

_DRIFT_ENTITY_TYPES = frozenset({"ip", "ipua"})


@dataclass
class _MerchantCusum:
    cusum: PoissonCusum
    committed_bucket: Optional[int] = None
    pending_bucket: Optional[int] = None
    pending_n: int = 0
    committed_alarm: bool = False
    committed_rate_ratio: float = 0.0


@dataclass
class _EntityState:
    drift: SequentialDrift
    attempts: int = 0
    cards: Set[str] = field(default_factory=set)
    first_seen_ms: int = 0


class Layer2Engine:
    def __init__(
        self,
        *,
        baseline: StoreBaseline,
        cusum_params: CusumParams,
        drift_params: DriftParams,
        tau_flag: float,
    ) -> None:
        self._baseline = baseline
        self._cp = cusum_params
        self._dp = drift_params
        self._tau_flag = float(tau_flag)
        self._q_hi_30m = baseline.card_quantile("30m", drift_params.exceedance_quantile)
        self._merchants: Dict[str, _MerchantCusum] = {}
        self._entities: Dict[Tuple[str, Tuple[str, str]], _EntityState] = {}

    # -- config surface (for the seam / SSE) ---------------------------

    @property
    def tau_flag(self) -> float:
        return self._tau_flag

    @property
    def drift_enabled(self) -> bool:
        return self._dp.enabled

    # -- state ------------------------------------------------------

    def reset(self) -> None:
        self._merchants.clear()
        self._entities.clear()

    def _merchant(self, merchant_id: str) -> _MerchantCusum:
        mc = self._merchants.get(merchant_id)
        if mc is None:
            mc = _MerchantCusum(cusum=PoissonCusum(self._cp))
            self._merchants[merchant_id] = mc
        return mc

    def _entity(self, merchant_id: str, entity: EntityKey) -> _EntityState:
        key = (merchant_id, entity.as_tuple())
        st = self._entities.get(key)
        if st is None:
            st = _EntityState(drift=SequentialDrift(self._dp))
            self._entities[key] = st
        return st

    def _lambda0(self, bucket_or_ingest_ms: int) -> float:
        return baseline_lambda0(
            attempts_this_hour=self._baseline.attempts_this_hour(hour_of_day(bucket_or_ingest_ms)),
            bucket_s=self._cp.bucket_s,
            flagged_rate_mean=self._baseline.flagged_rate_mean,
            lambda_min=self._cp.lambda_min,
        )

    def _commit_through(self, merchant_id: str, target_bucket: int) -> None:
        mc = self._merchant(merchant_id)
        if mc.pending_bucket is None:
            mc.pending_bucket = target_bucket
            mc.pending_n = 0
            return
        while mc.pending_bucket < target_bucket:
            bucket_start_ms = mc.pending_bucket * self._cp.bucket_s * 1000
            lam0 = self._lambda0(bucket_start_ms)
            step = mc.cusum.observe(mc.pending_bucket, mc.pending_n, lam0)
            mc.committed_bucket = mc.pending_bucket
            mc.committed_alarm = step.alarm
            mc.committed_rate_ratio = step.rate_ratio
            mc.pending_bucket += 1
            mc.pending_n = 0

    # -- the two entry points -------------------------------------

    def regime_for(self, merchant_id: str, bucket_index: int) -> Tuple[str, float]:
        """Commit every bucket strictly before `bucket_index`; return
        ("alarm"|"in_control", rate_ratio) from the committed statistic. The
        serving path calls this before the model so the alarm regime is a
        pure function of already-scored buckets."""
        self._commit_through(merchant_id, bucket_index)
        mc = self._merchant(merchant_id)
        regime = "alarm" if mc.committed_alarm else "in_control"
        return regime, mc.committed_rate_ratio

    def observe(
        self,
        *,
        merchant_id: str,
        entity: EntityKey,
        ingest_ms: int,
        bucket_index: int,
        p_calibrated: float,
        distinct_cards_per_ip_30m: float,
        rule_families: frozenset,
        card_hash: Optional[str],
    ) -> Tuple[DetectorSignal, CusumStep, Optional[DriftStep]]:
        self._commit_through(merchant_id, bucket_index)
        mc = self._merchant(merchant_id)
        if mc.pending_bucket is None:
            mc.pending_bucket = bucket_index
            mc.pending_n = 0

        st = self._entity(merchant_id, entity)
        attempts_before = st.attempts
        cards_before = len(st.cards)
        first_seen = st.first_seen_ms or ingest_ms
        st.attempts += 1
        if card_hash:
            st.cards.add(card_hash)
        if not st.first_seen_ms:
            st.first_seen_ms = ingest_ms

        flagged = p_calibrated >= self._tau_flag
        if flagged and mc.pending_bucket == bucket_index:
            mc.pending_n += 1

        lam0 = self._lambda0(ingest_ms)
        cstep = mc.cusum.peek(bucket_index, mc.pending_n, lam0)
        cusum_fired = cstep.alarm

        dstep: Optional[DriftStep] = None
        drift_fired = False
        if entity.entity_type in _DRIFT_ENTITY_TYPES:
            dstep = st.drift.observe(distinct_cards_per_ip_30m, self._q_hi_30m)
            drift_fired = dstep.fired

        if cusum_fired and drift_fired:
            detector = "both"
        elif cusum_fired:
            detector = "cusum"
        elif drift_fired:
            detector = "drift"
        else:
            detector = "none"

        fired = cusum_fired or drift_fired
        signal_value = cstep.rate_ratio if cusum_fired else (dstep.lam if dstep is not None else 0.0)

        signal = DetectorSignal(
            fired=fired,
            detector=detector,
            cusum_stat=cstep.s,
            signal_value=float(signal_value),
            cusum_bucket_index=bucket_index,
            families=frozenset(rule_families),
            entity_first_seen_ms=first_seen,
            attempts_on_entity=attempts_before,
            cards_on_entity=cards_before,
        )
        return signal, cstep, dstep

    def flush(self, merchant_id: str, now_bucket_index: int) -> None:
        """Commit any still-pending bucket (end of stream / test teardown)."""
        self._commit_through(merchant_id, now_bucket_index + 1)
