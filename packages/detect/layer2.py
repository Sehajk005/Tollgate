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

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from packages.detect.baseline import StoreBaseline
from packages.detect.cusum import CusumParams, CusumStep, PoissonCusum, baseline_lambda0, hour_of_day
from packages.detect.drift import DriftParams, DriftStep, SequentialDrift
from packages.detect.episode import DetectorSignal
from packages.detect.policy import EntityKey

logger = logging.getLogger("tollgate.detect.layer2")

_DRIFT_ENTITY_TYPES = frozenset({"ip", "ipua"})

# Source: remediation plan §11.5 (FIX-002) -- the TIME-DISCONTINUITY horizon,
# in 10-second buckets. 17 280 buckets = 48 hours.
#
# Replay time and serving time are the SAME domain (plan F-B): a replay
# launched with `epoch_ms: 0` produces bucket indices 0..1080, while a
# `POST /v1/score` from the storefront uses the system clock and produces
# ~1.756e8. A gap wider than this constant is not a gap in one timeline, it is
# two unrelated timelines meeting -- and folding it bucket-by-bucket is the
# ~175,600,000-iteration synchronous spin that wedged the scorer (AUDIT-006).
#
# WHY 17 280 AND NOT THE PLAN'S PROPOSED 8 640 (24 h). The plan required the
# horizon to be MEASURED rather than assumed, and the measurement rejected
# 8 640. Replaying all four tiers at seed 42 and recording the peak statistic
# under the pessimistic assumption that EVERY attempt is tau_flag-gated:
#
#     tier      events   bucket span   peak S_t   empty buckets to floor
#     easy         821          1076    948.195                    11 853
#     medium       701          1076    753.776                     9 423
#     hard         508          1076    437.316                     5 467
#     evasive      390          1076    253.632                     3 171
#
# "empty buckets to floor" is ceil(S / decay_floor) with the PROVABLE decay
# floor (rho - 1) * lambda_min = (5.0 - 1) * 0.02 = 0.08 per empty bucket --
# the worst case over every hour-of-day volume profile. The worst tier needs
# 11 853, so a 24-hour horizon could not carry the equivalence argument;
# 48 hours does, with 1.46x margin. Re-measure before lowering it.
#
# Crossing the horizon is handled ANALYTICALLY rather than iteratively. See
# `_empty_buckets_to_floor` for why that is answer-preserving and not a
# mitigation -- and note that correctness does not actually depend on this
# constant: the equivalence horizon is recomputed from the live parameters on
# every crossing, and a statistic that outlives it is reset explicitly and
# logged rather than silently approximated.
MAX_CATCHUP_BUCKETS = 17_280


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

    def _commit_one(self, mc: "_MerchantCusum", bucket_index: int, n_t: int) -> None:
        """Fold exactly one bucket and record the committed statistic. This is
        the body the catch-up loop always had; it is a method now so the
        discontinuity path can reuse it verbatim rather than reimplement it."""
        bucket_start_ms = bucket_index * self._cp.bucket_s * 1000
        lam0 = self._lambda0(bucket_start_ms)
        step = mc.cusum.observe(bucket_index, n_t, lam0)
        mc.committed_bucket = bucket_index
        mc.committed_alarm = step.alarm
        mc.committed_rate_ratio = step.rate_ratio

    def _empty_buckets_to_floor(self, s: float) -> Optional[int]:
        """How many consecutive EMPTY buckets provably pin S_t at exactly 0.0.

        The one-sided Poisson CUSUM is

            S_t = max(0, S_{t-1} + n_t*ln(lam1/lam0) - (lam1 - lam0))

        so an empty bucket (n_t = 0) subtracts exactly (lam1 - lam0) and floors
        at zero. lam1 = rho*lam0 and lam0 is floored at `lambda_min`, therefore
        EVERY empty bucket removes at least

            decay_floor = (rho - 1) * lambda_min

        regardless of the hour-of-day volume profile. After
        ceil(S / decay_floor) empty buckets S is exactly 0.0, and 0.0 is a fixed
        point of the recursion -- every further empty bucket leaves it there.

        That is why the bounded path is ANSWER-PRESERVING rather than a
        mitigation: beyond this horizon the long fold and the short one produce
        byte-identical (S, alarm, rate_ratio). The horizon is COMPUTED from the
        live parameters, not assumed, so a future rho / lambda_min change cannot
        silently invalidate the argument.

        Returns None when the parameters make the CUSUM non-decaying
        (rho <= 1 or lambda_min <= 0), i.e. when no such proof exists.
        """
        decay_floor = (float(self._cp.rho) - 1.0) * float(self._cp.lambda_min)
        if decay_floor <= 0.0:
            return None
        return math.ceil(max(s, 0.0) / decay_floor)

    def _commit_forward_discontinuity(
        self, merchant_id: str, mc: "_MerchantCusum", target_bucket: int, gap: int
    ) -> None:
        # 1. The still-filling bucket is a REAL observation carrying a real
        #    gated count. The unbounded fold committed it first; so does this.
        self._commit_one(mc, mc.pending_bucket, mc.pending_n)
        mc.pending_bucket += 1
        mc.pending_n = 0

        # 2. Every bucket between here and the target is empty. Fold only as
        #    many as can still change the answer.
        remaining = target_bucket - mc.pending_bucket
        to_floor = self._empty_buckets_to_floor(mc.cusum.s)
        provable = (
            to_floor is not None
            and to_floor <= remaining
            and to_floor <= MAX_CATCHUP_BUCKETS
        )
        fold_n = to_floor if provable else min(remaining, MAX_CATCHUP_BUCKETS)
        for _ in range(fold_n):
            self._commit_one(mc, mc.pending_bucket, 0)
            mc.pending_bucket += 1

        if not provable and mc.cusum.s > 0.0:
            # No equivalence proof available (a non-decaying parameterisation,
            # or a statistic so large it outlives a full 24 h of decay). Reset
            # rather than spin: an S_t carried across two unrelated time domains
            # is not a meaningful statistic anyway.
            mc.cusum.reset()

        # 3. Land on the target by folding its immediately preceding bucket, so
        #    `committed_bucket`, `committed_alarm`, `committed_rate_ratio` and
        #    the CUSUM's own bucket cursor all match the long fold exactly.
        if mc.pending_bucket < target_bucket:
            self._commit_one(mc, target_bucket - 1, 0)
            mc.pending_bucket = target_bucket
        mc.pending_n = 0

        logger.warning(
            "layer2: bounded time discontinuity for merchant %s -- forward jump of "
            "%d buckets (%.1f h) exceeds MAX_CATCHUP_BUCKETS=%d; folded %d bucket(s) "
            "analytically%s. This is replay time and serving time meeting in one "
            "engine (plan F-B); the statistic is equivalent, not approximated.",
            merchant_id, gap, gap * self._cp.bucket_s / 3600.0, MAX_CATCHUP_BUCKETS,
            fold_n, "" if provable else " and RESET (no equivalence proof)",
        )

    def _commit_backward_discontinuity(
        self, merchant_id: str, mc: "_MerchantCusum", target_bucket: int, gap: int
    ) -> None:
        """A jump far BACKWARDS -- a wall-clock checkout followed by an epoch-0
        replay. The old loop simply did not run, which cost nothing in CPU but
        stranded `pending_bucket` ~1.756e8 buckets in the future: from then on
        `observe()` never matched the live bucket, `pending_n` never
        incremented, and Layer 2 silently never fired again for the rest of the
        process. Silence is worse than a spin, not better."""
        mc.cusum.reset()
        mc.pending_bucket = target_bucket
        mc.pending_n = 0
        mc.committed_bucket = None
        mc.committed_alarm = False
        mc.committed_rate_ratio = 0.0
        logger.warning(
            "layer2: bounded time discontinuity for merchant %s -- backward jump of "
            "%d buckets (%.1f h) exceeds MAX_CATCHUP_BUCKETS=%d; the CUSUM has been "
            "reset to the new time domain rather than stranded in the old one.",
            merchant_id, -gap, -gap * self._cp.bucket_s / 3600.0, MAX_CATCHUP_BUCKETS,
        )

    def _commit_through(self, merchant_id: str, target_bucket: int) -> None:
        mc = self._merchant(merchant_id)
        if mc.pending_bucket is None:
            mc.pending_bucket = target_bucket
            mc.pending_n = 0
            return

        # Source: remediation plan §11.5 (FIX-002). Inside the horizon this is
        # byte-for-byte the loop Day 6 shipped -- a normal 3-hour replay spans
        # 1 080 buckets, well under MAX_CATCHUP_BUCKETS, so ordinary operation
        # never reaches either discontinuity branch.
        gap = target_bucket - mc.pending_bucket
        if gap > MAX_CATCHUP_BUCKETS:
            self._commit_forward_discontinuity(merchant_id, mc, target_bucket, gap)
            return
        if gap < -MAX_CATCHUP_BUCKETS:
            self._commit_backward_discontinuity(merchant_id, mc, target_bucket, gap)
            return

        while mc.pending_bucket < target_bucket:
            self._commit_one(mc, mc.pending_bucket, mc.pending_n)
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
