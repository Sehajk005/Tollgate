"""
Source: Day-8 Plan Step 4 (G11) + Day-8 exit gate D.13 -- the block-4 cost
quantities are hand-checkable from the artifact alone.

Recompute `f1_optimal`, `cost_optimal` and the rupee gap FROM the artifact's
own `curve_pi0` points (first-wins argmax / argmin, the same scan
`eval/d6.py` and `CostModel.min_cost_operating_point` use) and assert they
match the stored values. Then the exit-gate hand calculation:

    cost = 10_000 * (pi*(1-TPR)*C_FN + (1-pi)*FPR*C_FP)

with C_FN = 5200 (auth_fee 200 + downstream_exposure 5000) and
C_FP(challenge) = 1800 (aov 120000 * margin 0.30 * P(abandon|challenge) 0.05),
evaluated at the artifact's own f1_optimal / cost_optimal points, reproduces
`rupee_gap_minor` exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"

C_FN_MINOR = 5200.0             # auth_fee_minor 200 + downstream_exposure_minor 5000
C_FP_CHALLENGE_MINOR = 1800.0   # aov_minor 120000 * margin_pct 0.30 * abandonment[challenge] 0.05


def _cost(fpr: float, tpr: float, pi: float) -> float:
    return 10_000 * (pi * (1 - tpr) * C_FN_MINOR + (1 - pi) * fpr * C_FP_CHALLENGE_MINOR)


def _precision(fpr: float, tpr: float, pi: float) -> float:
    denom = pi * tpr + (1 - pi) * fpr
    return (pi * tpr / denom) if denom > 0 else 0.0


def _f1(fpr: float, tpr: float, pi: float) -> float:
    p = _precision(fpr, tpr, pi)
    r = tpr
    return (2 * p * r / (p + r)) if (p + r) > 0 else 0.0


@pytest.fixture(scope="module")
def b4() -> dict:
    assert ARTIFACT.exists(), f"{ARTIFACT} missing -- regenerate via eval.harness"
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["block4_cost"]


class TestD6CostGap:
    def test_both_regimes_present(self, b4):
        assert b4["curve_pi0"] and b4["curve_pi1"]
        assert b4["pi0"] == 0.001 and b4["pi1"] == 0.9
        for row in b4["curve_pi0"] + b4["curve_pi1"]:
            assert len(row) == 3  # [fpr, tpr, cost]

    def test_ribbon_spans_1e_4_to_1e_2(self, b4):
        pis = [entry["pi"] for entry in b4["ribbon"]]
        assert min(pis) == 1e-4
        assert max(pis) == 1e-2
        for entry in b4["ribbon"]:
            assert entry["curve"], f"empty ribbon curve at pi={entry['pi']}"

    def test_cost_optimal_recomputed_from_curve_pi0_matches_stored(self, b4):
        pi0 = b4["pi0"]
        best = None
        for fpr, tpr, cost in b4["curve_pi0"]:
            if best is None or cost < best[2]:
                best = (fpr, tpr, cost)
        assert [best[0], best[1]] == [b4["cost_optimal"]["fpr"], b4["cost_optimal"]["tpr"]]
        assert best[2] == pytest.approx(b4["cost_optimal"]["cost_pi0"])
        # sanity: the stored cost equals the hand formula at that point
        assert _cost(best[0], best[1], pi0) == pytest.approx(b4["cost_optimal"]["cost_pi0"])

    def test_f1_optimal_recomputed_from_curve_pi0_matches_stored(self, b4):
        pi0 = b4["pi0"]
        best = None
        for fpr, tpr, _cost in b4["curve_pi0"]:
            v = _f1(fpr, tpr, pi0)
            if best is None or v > best[2]:
                best = (fpr, tpr, v)
        assert [best[0], best[1]] == [b4["f1_optimal"]["fpr"], b4["f1_optimal"]["tpr"]]

    def test_rupee_gap_recomputed_exactly_matches_and_is_non_negative(self, b4):
        pi0 = b4["pi0"]
        f1p = b4["f1_optimal"]
        cop = b4["cost_optimal"]
        gap = _cost(f1p["fpr"], f1p["tpr"], pi0) - _cost(cop["fpr"], cop["tpr"], pi0)
        assert gap >= 0.0
        assert gap == pytest.approx(b4["rupee_gap_minor"], abs=1e-6)

    def test_inputs_block_carries_the_four_hand_check_quantities(self, b4):
        inp = b4["inputs"]
        assert inp["c_fn_minor"] == 5200
        assert inp["c_fp_minor_challenge"] == pytest.approx(1800.0)
        assert inp["f1_optimal_point"] == [b4["f1_optimal"]["fpr"], b4["f1_optimal"]["tpr"]]
        assert inp["cost_optimal_point"] == [b4["cost_optimal"]["fpr"], b4["cost_optimal"]["tpr"]]

    def test_regime_switch_saving_is_non_negative(self, b4):
        assert b4["regime_switch_saving_minor"] >= 0.0
