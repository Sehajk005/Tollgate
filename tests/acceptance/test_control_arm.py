"""
Source: Day-6 Plan §4 / Eval Protocol §6.1 -- the control arm.

  * EXACTLY `control_fraction` of enforcement-eligible attempts pass
    unenforced (deterministic one-per-block-of-N selection, Day-6 Plan D9).
  * two runs with the same seed (merchant_id + pinned policy_version) select
    the identical attempt set.
  * a control attempt returns the un-enforced decision (allow), including
    past the R1-R3 floors (Day-6 Plan D10).
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.decision import Decision
from packages.detect.policy import (
    EntityKey,
    PolicyEngine,
    PolicySnapshot,
    control_block_size,
    is_control_ordinal,
)

THRESHOLDS = {"throttle": 0.065, "challenge": 0.257, "step_up": 0.509, "block": 0.874}


@dataclass
class _Eval:
    minimum_tier: Decision = Decision.CHALLENGE  # R2/R3 floor -- a control still passes it
    fired_names: tuple = ("distinct_cards_per_ip_5m",)


def _snap(control_fraction: float, version: int = 7) -> PolicySnapshot:
    return PolicySnapshot(
        version=version, thresholds=THRESHOLDS, hysteresis_gap=0.08, cooldown_seconds=300,
        cusum_rho=5.0, cusum_h=255.0, cusum_bucket_s=10, drift_window_s=1800,
        allow_auto_block=False, auto_ceiling="challenge", k_max_entities=10,
        control_fraction=control_fraction, rules_config={},
    )


def _run(engine, snap, n):
    out = []
    for i in range(n):
        e = EntityKey("ip", f"10.0.0.{i}")
        o = engine.resolve(
            merchant_id="m", p_calibrated=0.30, evaluation=_Eval(), entity=e, snapshot=snap,
            incident_open=True, corroborated=True, active_enforced_count=0,
            bin_is_foreign_issued=0.0, regime="in_control", prior_used=0.001,
        )
        out.append((i, o.control_arm, o.in_force_tier))
    return out


class TestControlArm:
    def test_exactly_control_fraction_pass_unenforced(self):
        rows = _run(PolicyEngine(), _snap(0.05), 100)
        controls = [r for r in rows if r[1]]
        assert len(controls) == 5, f"expected 5 controls in 100 eligible, got {len(controls)}"
        n = control_block_size(0.05)
        assert n == 20
        assert {c[0] // n for c in controls} == {0, 1, 2, 3, 4}

    def test_same_seed_selects_the_identical_set(self):
        snap = _snap(0.05)
        a = [r[0] for r in _run(PolicyEngine(), snap, 60) if r[1]]
        b = [r[0] for r in _run(PolicyEngine(), snap, 60) if r[1]]
        assert a == b and len(a) == 3

    def test_a_different_policy_version_reshuffles(self):
        a = [r[0] for r in _run(PolicyEngine(), _snap(0.05, version=7), 60) if r[1]]
        b = [r[0] for r in _run(PolicyEngine(), _snap(0.05, version=8), 60) if r[1]]
        assert a != b

    def test_control_attempt_passes_unenforced_past_the_rule_floor(self):
        rows = _run(PolicyEngine(), _snap(0.05), 20)
        control = next(r for r in rows if r[1])
        assert control[2] == Decision.ALLOW

    def test_is_control_ordinal_is_pure_and_block_local(self):
        n = control_block_size(0.05)
        for block in range(4):
            hits = [
                o for o in range(block * n, (block + 1) * n)
                if is_control_ordinal(
                    eligible_ordinal=o, merchant_id="m", policy_version=1, control_fraction=0.05
                )
            ]
            assert len(hits) == 1
