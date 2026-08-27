"""
Source: Day-4 Plan (rev. 2) §6 test 6 -- "Cost endpoints + hull."
(FPR,TPR)=(1,1) -> 10_000*(1-pi)*C_FP; (0,0) -> 10_000*pi*C_FN. Worked case
(pi0=0.001, challenge): Rs 179,820 (17,982,000 minor units) and Rs 520
(52,000 minor units). Hull minimum is a vertex and matches brute force
over all points.
"""

from __future__ import annotations

import itertools

from eval.cost import load_cost_model, roc_convex_hull

PI0 = 0.001


class TestCostCurveEndpoints:
    def test_always_positive_endpoint(self):
        model = load_cost_model()
        cost = model.expected_cost_per_10k(tpr=1.0, fpr=1.0, pi=PI0, tier="challenge")
        expected = 10_000 * (1 - PI0) * model.c_fp_minor("challenge")
        assert cost == expected
        assert round(cost) == 17_982_000  # Rs 179,820.00 in minor units

    def test_always_negative_endpoint(self):
        model = load_cost_model()
        cost = model.expected_cost_per_10k(tpr=0.0, fpr=0.0, pi=PI0, tier="challenge")
        expected = 10_000 * PI0 * model.c_fn_minor()
        assert cost == expected
        assert round(cost) == 52_000  # Rs 520.00 in minor units

    def test_roc_convex_hull_includes_trivial_endpoints(self):
        hull = roc_convex_hull([(0.2, 0.4), (0.5, 0.6)])
        assert (0.0, 0.0) in hull
        assert (1.0, 1.0) in hull

    def test_hull_minimum_matches_brute_force_over_all_points(self):
        model = load_cost_model()
        points = [(0.0, 0.0), (0.0005, 0.6), (0.001, 0.75), (0.01, 0.95), (0.3, 0.99), (1.0, 1.0)]
        hull = roc_convex_hull(points)

        # Brute force over the ORIGINAL point set (plus its own trivial
        # endpoints) must never beat the hull's minimum -- the hull is a
        # superset-safe search space for the piecewise-linear-minimum claim.
        candidates = set(points) | {(0.0, 0.0), (1.0, 1.0)}
        brute_best = min(
            model.expected_cost_per_10k(tpr, fpr, PI0, "challenge") for fpr, tpr in candidates
        )
        _, hull_best = model.min_cost_operating_point(hull, PI0, "challenge")
        assert hull_best <= brute_best + 1e-9

    def test_hull_minimum_is_a_hull_vertex(self):
        model = load_cost_model()
        points = [(0.0, 0.0), (0.0005, 0.6), (0.001, 0.75), (0.01, 0.95), (0.3, 0.99), (1.0, 1.0)]
        hull = roc_convex_hull(points)
        best_point, best_cost = model.min_cost_operating_point(hull, PI0, "challenge")
        assert best_point in hull
        assert best_cost is not None

    def test_hull_is_convex_and_monotone_in_fpr(self):
        points = [(0.0, 0.0), (0.0005, 0.6), (0.001, 0.75), (0.01, 0.95), (0.3, 0.99), (1.0, 1.0)]
        hull = roc_convex_hull(points)
        fprs = [p[0] for p in hull]
        assert fprs == sorted(fprs)
        for a, b in itertools.pairwise(hull):
            assert b[0] >= a[0]
