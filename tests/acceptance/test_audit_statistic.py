"""
Source: Day-4 Plan (rev. 2) Step 9 -- the audit statistic ships today; the
audit itself (over feature_snapshot) is Day 5 by dependency. Proves the
statistic isn't vacuously passing via a planted-perfect-discriminator.
"""

from __future__ import annotations

from eval.audit import univariate_auc


class TestAuditStatistic:
    def test_planted_perfect_discriminator_is_detected(self):
        values = [10.0] * 50 + [0.0] * 50
        labels = [True] * 50 + [False] * 50
        assert univariate_auc(values, labels) == 1.0

    def test_non_discriminating_value_scores_near_0_5(self):
        values = [1.0] * 100
        labels = ([True] * 50) + ([False] * 50)
        assert univariate_auc(values, labels) == 0.5

    def test_degenerate_input_returns_none(self):
        assert univariate_auc([1.0, 2.0], [True, True]) is None
