"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md FIX-BE-02 / §24.3 -- Block 2 must
carry the PRODUCT's own false-positive behaviour on the negative-control
scenarios, not only the four analytically-predetermined sanity scorers.

Reads the committed `eval/outputs/d6.json` (schema v2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"

_SANITY = ("perfect", "random", "inverted", "always_positive")


@pytest.fixture(scope="module")
def block2() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["block2_negative_controls"]


def test_seven_scenarios_each_with_six_rows(block2):
    assert len(block2) == 7, sorted(block2)
    total = 0
    for scenario, rows in block2.items():
        assert len(rows) == 6, f"{scenario}: {[r['scorer'] for r in rows]}"
        total += len(rows)
    assert total == 42


def test_model_and_b0_rows_are_first_and_present_for_every_scenario(block2):
    for scenario, rows in block2.items():
        assert rows[0]["scorer"] == "l1-lgbm-v1", f"{scenario} row 0"
        assert rows[1]["scorer"] == "rules-only-v0", f"{scenario} row 1"
        for row in rows[:2]:
            assert row["available"] is True
            assert isinstance(row["attempt_fp"], int) and row["attempt_fp"] >= 0


def test_sanity_scorers_retained_as_the_harness_floor(block2):
    for scenario, rows in block2.items():
        assert [r["scorer"] for r in rows[2:]] == list(_SANITY), scenario


def test_denominators_are_identical_across_all_six_rows(block2):
    for scenario, rows in block2.items():
        denoms = {r["attempts"] for r in rows}
        assert len(denoms) == 1, f"{scenario}: {[(r['scorer'], r['attempts']) for r in rows]}"


def test_attempt_fp_never_exceeds_attempts(block2):
    for scenario, rows in block2.items():
        for row in rows:
            if row["attempt_fp"] is not None:
                assert row["attempt_fp"] <= row["attempts"], (scenario, row["scorer"])


def test_episode_flagged_is_boolean_and_consistent_with_episode_fp(block2):
    for scenario, rows in block2.items():
        for row in rows:
            assert isinstance(row["episode_flagged"], bool), (scenario, row["scorer"])
            assert row["episode_flagged"] == (row["episode_fp"] > 0), (scenario, row["scorer"])


def test_denominator_basis_is_legitimate_attempts_only(block2):
    for scenario, rows in block2.items():
        for row in rows:
            assert row["denominator_basis"] == "legitimate_attempts_only"


def test_shared_ip_legit_is_a_single_legitimate_attempt(block2):
    assert all(r["attempts"] == 1 for r in block2["shared_ip_legit"])


def test_retry_storm_is_underpowered(block2):
    assert all(r["attempts"] == 5 for r in block2["retry_storm"])


def test_flash_sale_has_an_adequate_denominator(block2):
    assert all(r["attempts"] == 720 for r in block2["flash_sale"])


def test_every_row_carries_the_v2_shape(block2):
    for scenario, rows in block2.items():
        for row in rows:
            assert row["episodes"] == 1
            assert set(row) >= {
                "scorer", "episode_fp", "episodes", "attempt_fp", "attempts",
                "episode_flagged", "denominator_basis", "available", "reason",
            }
