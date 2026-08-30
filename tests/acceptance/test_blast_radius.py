"""
Source: Day-6 Plan §4 / Threat Model §4/P2 -- at `k_max_entities` the engine
enters ADVISORY mode: it stops issuing NEW enforcement on NEW entities,
keeps scoring, keeps entities already under enforcement, and raises the
operator alert (SSE `enforcement.advisory_mode`).

`K_max` here is the scalar `policy_config.k_max_entities` (Day-6 Plan D8);
the 1%-of-active-entities form is recorded as future work, not invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.decision import Decision
from packages.detect.policy import EntityKey, PolicyEngine, PolicySnapshot

THRESHOLDS = {"throttle": 0.065, "challenge": 0.257, "step_up": 0.509, "block": 0.874}


@dataclass
class _Eval:
    minimum_tier: Decision = Decision.ALLOW
    fired_names: tuple = ()


def _snap(k_max: int) -> PolicySnapshot:
    return PolicySnapshot(
        version=1, thresholds=THRESHOLDS, hysteresis_gap=0.08, cooldown_seconds=300,
        cusum_rho=5.0, cusum_h=255.0, cusum_bucket_s=10, drift_window_s=1800,
        allow_auto_block=False, auto_ceiling="challenge", k_max_entities=k_max,
        control_fraction=0.0, rules_config={},
    )


def _resolve(engine, snap, entity, *, active, p=0.30):
    return engine.resolve(
        merchant_id="m", p_calibrated=p, evaluation=_Eval(), entity=entity, snapshot=snap,
        incident_open=True, corroborated=True, active_enforced_count=active,
        bin_is_foreign_issued=0.0, regime="in_control", prior_used=0.001,
    )


class TestBlastRadius:
    def test_new_entity_at_the_cap_enters_advisory_and_is_not_enforced(self):
        engine = PolicyEngine()
        snap = _snap(k_max=3)
        out = _resolve(engine, snap, EntityKey("ip", "203.0.113.99"), active=3)
        assert out.advisory_mode is True
        assert out.in_force_tier == Decision.ALLOW
        assert out.proposed_tier == Decision.CHALLENGE

    def test_below_the_cap_enforces_normally(self):
        engine = PolicyEngine()
        out = _resolve(engine, _snap(k_max=3), EntityKey("ip", "203.0.113.1"), active=2)
        assert out.advisory_mode is False
        assert out.in_force_tier == Decision.CHALLENGE

    def test_entity_already_under_enforcement_is_retained_at_the_cap(self):
        engine = PolicyEngine()
        snap = _snap(k_max=3)
        e = EntityKey("ip", "203.0.113.7")
        _resolve(engine, snap, e, active=1)
        assert engine.current_tier(e) == Decision.CHALLENGE
        out = _resolve(engine, snap, e, active=3)
        assert out.advisory_mode is False
        assert out.in_force_tier == Decision.CHALLENGE
