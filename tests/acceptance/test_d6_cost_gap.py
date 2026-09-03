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

    # ---- plan §24.2: the mandatory numeric upgrade -----------------------

    def test_regime_switch_saving_is_recomputed_exactly_from_the_anchors(self, b4):
        """Independently recompute the ₹2,32,145 headline from the artifact's
        own curve_pi1 and the hardcoded C_FN=5200 / C_FP=1800 anti-circularity
        anchors -- NOT `>= 0`. Ties the backend number to the exact rupee string
        the UI must render (FE-T-FMT-01 asserts the other half)."""
        pi1 = b4["pi1"]
        cop = b4["cost_optimal"]
        stay_cost_pi1 = _cost(cop["fpr"], cop["tpr"], pi1)
        best_cost_pi1 = min(_cost(fpr, tpr, pi1) for fpr, tpr, _c in b4["curve_pi1"])
        expected = stay_cost_pi1 - best_cost_pi1

        assert stay_cost_pi1 == pytest.approx(24855010.972933434, abs=1e-6)
        assert best_cost_pi1 == pytest.approx(1640502.7668777597, abs=1e-6)
        assert expected == pytest.approx(23214508.206055675, abs=1e-6)
        assert b4["regime_switch_saving_minor"] == pytest.approx(expected, abs=1e-6)
        assert round(expected / 100) == 232145  # the displayed rupee figure

    def test_cost_optimal_point_is_exactly_the_expected_operating_point(self, b4):
        cop = b4["cost_optimal"]
        assert cop["fpr"] == 0.0
        assert cop["tpr"] == pytest.approx(0.46891002194586684, abs=1e-12)
        assert cop["cost_pi0"] == pytest.approx(27616.67885881492, abs=1e-6)

    def test_f1_optimal_point_and_its_f1_value_are_exact(self, b4):
        f1p = b4["f1_optimal"]
        assert f1p["fpr"] == 0.0
        assert f1p["tpr"] == pytest.approx(0.46891002194586684, abs=1e-12)
        assert f1p["f1"] == pytest.approx(0.6384462151394422, abs=1e-12)

    def test_every_curve_cost_is_recomputable_from_the_formula(self, b4):
        for fpr, tpr, cost in b4["curve_pi0"]:
            assert cost == pytest.approx(_cost(fpr, tpr, b4["pi0"]), rel=1e-9, abs=1e-6)
        for fpr, tpr, cost in b4["curve_pi1"]:
            assert cost == pytest.approx(_cost(fpr, tpr, b4["pi1"]), rel=1e-9, abs=1e-6)

    # ---- plan FIX-M-004 / FIX-M-039 / FIX-M-005 (backend halves) ---------

    def test_optima_coincidence_is_a_backend_fact_not_a_frontend_compare(self, b4):
        f1p, cop = b4["f1_optimal"], b4["cost_optimal"]
        assert b4["optima_coincident"] is True
        assert (f1p["fpr"], f1p["tpr"]) == (cop["fpr"], cop["tpr"])

    def test_rupee_gap_is_flagged_structural_with_a_substantiating_note(self, b4):
        assert b4["rupee_gap_minor"] == 0.0
        assert b4["rupee_gap_is_structural"] is True
        note = b4["rupee_gap_note"]
        assert "structural" in note and "precision" in note

    def test_decision_region_bound_contains_both_optima_and_the_next_vertex(self, b4):
        bound = b4["decision_region_fpr_max"]
        assert bound > 0.0
        assert b4["cost_optimal"]["fpr"] < bound
        next_vertices = sorted(f for f, _t, _c in b4["curve_pi0"] if f > b4["cost_optimal"]["fpr"])
        assert next_vertices and next_vertices[0] < bound

    def test_ribbon_envelope_is_a_valid_non_crossing_band(self, b4):
        env = b4["ribbon_envelope"]
        assert len(env) == len(b4["curve_pi0"])
        for fpr, lo, hi in env:
            assert hi >= lo, f"ribbon envelope inverts at fpr={fpr}: lo={lo} hi={hi}"
        xs = [fpr for fpr, _lo, _hi in env]
        assert xs == sorted(xs)  # monotone x -> forward/reverse polylines cannot cross
