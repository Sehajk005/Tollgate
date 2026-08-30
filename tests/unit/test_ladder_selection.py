"""
Source: Day-6 Plan §4 (tests/unit, advisory) -- domestic drops `step_up`,
foreign keeps it (AFA already binds a domestic-issued BIN, so forcing 3-D
Secure is not an escalation -- TRD §6.7 / Threat Model §7a).
"""

from __future__ import annotations

from packages.contracts.decision import Decision
from packages.detect.policy import ladder_tiers, select_ladder, tier_from_score

_LADDER = {"throttle": 0.065, "challenge": 0.257, "step_up": 0.509, "block": 0.874}


def test_select_ladder_defaults_domestic_and_flips_only_for_a_foreign_bin():
    assert select_ladder(0.0) == "domestic"
    assert select_ladder(0.4) == "domestic"
    assert select_ladder(1.0) == "foreign"


def test_domestic_ladder_omits_step_up_foreign_keeps_it():
    assert "step_up" not in ladder_tiers("domestic")
    assert ladder_tiers("domestic") == ("throttle", "challenge", "block")
    assert "step_up" in ladder_tiers("foreign")


def test_tier_from_score_skips_step_up_on_the_domestic_ladder():
    p = 0.6  # > theta_step_up (0.509), < theta_block (0.874)
    assert tier_from_score(p, _LADDER, "domestic") == Decision.CHALLENGE
    assert tier_from_score(p, _LADDER, "foreign") == Decision.STEP_UP


def test_tier_from_score_floor_is_monitor_not_allow():
    assert tier_from_score(0.0, _LADDER, "domestic") == Decision.MONITOR
    assert tier_from_score(0.9, _LADDER, "domestic") == Decision.BLOCK
