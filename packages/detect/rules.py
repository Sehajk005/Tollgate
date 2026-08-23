"""
Source: TRD v2.1 §6.10 -- the Day 1 cold-start rules layer (decisions 1-2 in
Decisions.md).

R1  attempts_per_ip_60s        >= 20   -> minimum tier: throttle    [rate]
R2  distinct_cards_per_ip_5m   >= 15   -> minimum tier: challenge   [source fan-out]
R3  distinct_cards_per_bin_5m  >= 20   -> minimum tier: challenge   [issuer fan-out]

Rules set a FLOOR (final_tier >= max(rule_minimums)), never a ceiling. They
require no /v1/outcome, no decline data, no learned baseline, no ML model,
and no BIN metadata join -- all three are computable from the in-memory
WindowStore alone, active from the first scored attempt.

R3 is distinct_cards_per_bin, NOT distinct_bins_per_ip -- the inverse
geometry. See tests/acceptance/test_rules_geometry.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from packages.contracts.decision import Decision
from packages.features.store import WindowRequest, WindowStore

WINDOW_60S_MS = 60_000
WINDOW_5M_MS = 5 * 60_000

_TIER_ORDER = [
    Decision.ALLOW,
    Decision.MONITOR,
    Decision.THROTTLE,
    Decision.CHALLENGE,
    Decision.STEP_UP,
    Decision.BLOCK,
]


@dataclass(frozen=True)
class RuleInput:
    merchant_id: str
    attempt_uid: str
    ingest_ms: int
    ip: str
    card_hash: str
    bin: str


@dataclass(frozen=True)
class RuleResult:
    name: str
    fired: bool
    minimum_tier: Optional[Decision]
    value: int
    threshold: int


@dataclass(frozen=True)
class RulesEvaluation:
    results: Tuple[RuleResult, ...]

    @property
    def minimum_tier(self) -> Decision:
        fired_tiers = [r.minimum_tier for r in self.results if r.fired and r.minimum_tier is not None]
        if not fired_tiers:
            return Decision.ALLOW
        return max(fired_tiers, key=_TIER_ORDER.index)

    @property
    def fired_names(self) -> list:
        return [r.name for r in self.results if r.fired]

    @property
    def feature_snapshot(self) -> dict:
        return {r.name: r.value for r in self.results}

    def rule_score(self) -> float:
        """
        A simple deterministic score in [0, 1] derived from how far each
        rule's statistic sits past its threshold. Day 1 has no model (Day 5)
        or calibrator (Day 5); this stands in as the honest 'rules-only-v0'
        degraded form Impl Plan Day 5's own cut fallback already names.
        """
        ratios = [r.value / r.threshold for r in self.results if r.threshold > 0]
        return min(1.0, max(ratios, default=0.0))


class DayOneRules:
    def __init__(
        self,
        store: WindowStore,
        r1_threshold: int = 20,
        r2_threshold: int = 15,
        r3_threshold: int = 20,
    ) -> None:
        self._store = store
        self._r1_threshold = r1_threshold
        self._r2_threshold = r2_threshold
        self._r3_threshold = r3_threshold

    def evaluate(self, inp: RuleInput) -> RulesEvaluation:
        r1_count = self._store.record_and_read(
            WindowRequest(
                merchant_id=inp.merchant_id,
                space="ip",
                key=inp.ip,
                metric="ev",
                member=inp.attempt_uid,
                ingest_ms=inp.ingest_ms,
                window_ms=WINDOW_60S_MS,
            )
        ).count

        r2_count = self._store.record_and_read(
            WindowRequest(
                merchant_id=inp.merchant_id,
                space="ip",
                key=inp.ip,
                metric="card",
                member=inp.card_hash,
                ingest_ms=inp.ingest_ms,
                window_ms=WINDOW_5M_MS,
            )
        ).count

        r3_count = self._store.record_and_read(
            WindowRequest(
                merchant_id=inp.merchant_id,
                space="bin",
                key=inp.bin,
                metric="card",
                member=inp.card_hash,
                ingest_ms=inp.ingest_ms,
                window_ms=WINDOW_5M_MS,
            )
        ).count

        results = (
            RuleResult(
                "attempts_per_ip_60s",
                r1_count >= self._r1_threshold,
                Decision.THROTTLE,
                r1_count,
                self._r1_threshold,
            ),
            RuleResult(
                "distinct_cards_per_ip_5m",
                r2_count >= self._r2_threshold,
                Decision.CHALLENGE,
                r2_count,
                self._r2_threshold,
            ),
            RuleResult(
                "distinct_cards_per_bin_5m",
                r3_count >= self._r3_threshold,
                Decision.CHALLENGE,
                r3_count,
                self._r3_threshold,
            ),
        )
        return RulesEvaluation(results)
