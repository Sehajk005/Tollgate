"""
Source: Day-6 Plan §4 / TRD §6.7 -- a score oscillating inside
[theta_T - hysteresis_gap, theta_T] produces exactly ONE tier change, not
many. The hysteresis_gap -> T_exit mapping is Day-6 Plan D7:
    rise to T   requires p >= theta_T
    fall below T requires p <  theta_T - hysteresis_gap
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from packages.contracts.decision import Decision
from packages.detect.policy import EntityKey, PolicyEngine, PolicySnapshot

THRESHOLDS = {"throttle": 0.065, "challenge": 0.257, "step_up": 0.509, "block": 0.874}
GAP = 0.08


@dataclass
class _Eval:
    minimum_tier: Decision = Decision.ALLOW
    fired_names: tuple = ()


def _snapshot() -> PolicySnapshot:
    return PolicySnapshot(
        version=1, thresholds=THRESHOLDS, hysteresis_gap=GAP, cooldown_seconds=300,
        cusum_rho=5.0, cusum_h=255.0, cusum_bucket_s=10, drift_window_s=1800,
        allow_auto_block=False, auto_ceiling="challenge", k_max_entities=10,
        control_fraction=0.0, rules_config={},
    )


def _resolve(engine, snap, entity, p):
    return engine.resolve(
        merchant_id="m", p_calibrated=p, evaluation=_Eval(), entity=entity, snapshot=snap,
        incident_open=True, corroborated=True, active_enforced_count=0,
        bin_is_foreign_issued=0.0, regime="in_control", prior_used=0.001,
    )


class TestHysteresis:
    def test_oscillation_inside_the_band_produces_one_tier_change(self):
        engine = PolicyEngine()
        snap = _snapshot()
        e = EntityKey("ip", "203.0.113.7")
        theta = THRESHOLDS["challenge"]
        # start just below the band (throttle), rise once to challenge, then
        # oscillate strictly inside [theta - gap, theta): 0.19 .. 0.25
        sequence = [0.10, theta + 0.001, 0.19, 0.25, 0.20, 0.24, 0.21, 0.23, 0.19, 0.25]
        tiers: List[Decision] = [_resolve(engine, snap, e, p).in_force_tier for p in sequence]
        changes = sum(1 for a, b in zip(tiers, tiers[1:]) if a != b)
        assert changes == 1, f"expected one tier change, got {changes}: {[t.value for t in tiers]}"
        assert tiers[0] == Decision.THROTTLE
        assert all(t == Decision.CHALLENGE for t in tiers[1:])

    def test_falls_only_when_the_score_leaves_the_band_below(self):
        engine = PolicyEngine()
        snap = _snapshot()
        e = EntityKey("ip", "203.0.113.8")
        theta = THRESHOLDS["challenge"]
        _resolve(engine, snap, e, theta + 0.01)
        assert _resolve(engine, snap, e, theta - GAP + 0.001).in_force_tier == Decision.CHALLENGE
        assert _resolve(engine, snap, e, theta - GAP - 0.05).in_force_tier == Decision.THROTTLE
