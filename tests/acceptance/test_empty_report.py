"""
Source: Day-4 Plan (rev. 2) §6 test 11 -- "Empty split / zero incidents."
Every metric returns None, not 0.0; no exception; report renders explicit
empty states; zero-incident report renders.
"""

from __future__ import annotations

from eval.metrics import (
    ap_at_prevalence,
    average_precision,
    operating_point,
    recall_at_fpr,
    roc_auc,
    roc_points,
)
from eval.scorers import PerfectScorer


class TestEmptyAndDegenerateMetrics:
    def test_empty_input_returns_none_or_empty_never_crashes(self):
        assert recall_at_fpr([], [], 1e-3) is None
        assert average_precision([], []) is None
        assert ap_at_prevalence([], [], 0.01) is None
        assert roc_auc([], []) is None
        assert roc_points([], []) == []
        assert operating_point([], [], 0.5) is None

    def test_all_negative_split_returns_none_never_0_0(self):
        labels = [False] * 50
        scores = [0.5] * 50
        assert recall_at_fpr(scores, labels, 1e-3) is None
        assert average_precision(scores, labels) is None
        assert ap_at_prevalence(scores, labels, 0.01) is None
        assert roc_auc(scores, labels) is None

    def test_all_positive_split_returns_none_never_0_0(self):
        labels = [True] * 50
        scores = [0.5] * 50
        assert recall_at_fpr(scores, labels, 1e-3) is None
        assert average_precision(scores, labels) is None
        assert roc_auc(scores, labels) is None

    def test_operating_point_on_zero_incidents_renders_well_defined_zeros(self):
        # A non-empty but entirely-negative population at a fixed threshold
        # is well-defined (a real "zero incidents" operating point), unlike
        # the ranking metrics above which are undefined without both classes.
        labels = [False] * 20
        scores = [0.9] * 20
        point = operating_point(scores, labels, theta=0.5)
        assert point is not None
        assert point.tp == 0 and point.fn == 0
        assert point.fpr == 1.0  # all 20 negatives scored above theta
        assert point.precision == 0.0


def _partial_tier_samples():
    from eval.dataset import Sample

    # Only "easy" tier samples -- medium/hard tiers are empty in this split.
    return tuple(
        Sample(
            event_id=f"e-{i}", t_ms=i, is_attack=(i % 5 == 0), stream_tier="easy",
            episode_tier="easy" if i % 5 == 0 else None, episode_id="ep-1" if i % 5 == 0 else None,
            kind="attack" if i % 5 == 0 else "baseline", scenario=None, entity_overlap=False,
            outcome_visible_ms=i + 340, ip=f"1.1.1.{i % 50}", bin="999000", card_hash=f"c-{i}",
            amount_minor=100, gateway_status="authorized", decline_code=None,
        )
        for i in range(200)
    )


class TestEmptyReportRendersExplicitStates:
    def test_evaluate_does_not_crash_on_a_split_missing_two_tiers(self):
        from eval.cost import load_cost_model
        from eval.dataset import Split
        from eval.harness import _make_provenance, evaluate

        cost_model = load_cost_model()
        split = Split(name="temporal_test", samples=_partial_tier_samples())
        report = evaluate(split, PerfectScorer(), cost_model, _make_provenance("none:perfect"))

        assert report.tier_breakdown["medium"] is None
        assert report.tier_breakdown["hard"] is None
        assert report.tier_breakdown["easy"] is not None

    def test_full_render_with_zero_negative_control_scenarios_produces_explicit_empty_states(self, tmp_path):
        from eval.cost import load_cost_model
        from eval.dataset import Split
        from eval.harness import BaselineSummary, HarnessRun, _build_sanity_scorers, _make_provenance, evaluate
        from eval.metrics import operating_point
        from eval.report import render

        cost_model = load_cost_model()
        split = Split(name="temporal_test", samples=_partial_tier_samples())
        scorers = _build_sanity_scorers(seed=42)
        reports = [
            evaluate(split, scorer, cost_model, _make_provenance(model_version))
            for _key, (model_version, scorer) in scorers.items()
        ]

        dummy_point = operating_point([0.0], [False], 0.5)
        run = HarnessRun(
            eval_reports={"temporal_test": reports},
            temporal_train_n=0, holdout_train_n=0,
            negative_scenario_names=(),  # zero negative-control scenarios in this run
            negative_splits={},
            baseline_summary=BaselineSummary(
                b1_operating_point=dummy_point, b2_operating_point=dummy_point,
                sanity_recall_at_b1_fpr={}, sanity_recall_at_b2_fpr={},
            ),
            seed=42,
        )

        out_path = tmp_path / "report.md"
        render([run], out_path=out_path, seeds_used=1, base_seed=42)  # must not raise
        text = out_path.read_text(encoding="utf-8")

        assert "| medium | 0 | n/a | n/a (empty) | n/a | n/a |" in text
        assert "| hard | 0 | n/a | n/a (empty) | n/a | n/a |" in text
        assert "## Block 2" in text  # zero-scenario negative-controls block still renders, not skipped
