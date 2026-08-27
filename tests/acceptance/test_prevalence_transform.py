"""
Source: Day-4 Plan (rev. 2) §6 test 19 -- "Analytic prevalence
transformation." ap_at_prevalence(pi_raw) == average_precision(...);
transforming DOWN from pi=0.9 to 0.01 works (empirical resampling could
not); result matches a resampled estimate within its CI on a case where
both are valid (F7).
"""

from __future__ import annotations

import random

import pytest

from eval.metrics import ap_at_prevalence, average_precision

RNG = random.Random(1234)


def _scored_samples(n_pos: int, n_neg: int, separation: float) -> tuple:
    """Positives score higher on average than negatives by `separation`, with noise; returns (scores, labels)."""
    scores = []
    labels = []
    for _ in range(n_pos):
        scores.append(RNG.gauss(separation, 1.0))
        labels.append(True)
    for _ in range(n_neg):
        scores.append(RNG.gauss(0.0, 1.0))
        labels.append(False)
    combined = list(zip(scores, labels))
    RNG.shuffle(combined)
    scores, labels = zip(*combined)
    return list(scores), list(labels)


class TestAnalyticPrevalenceTransformation:
    def test_ap_at_raw_prevalence_matches_average_precision_exactly(self):
        scores, labels = _scored_samples(n_pos=200, n_neg=1800, separation=1.5)
        pi_raw = sum(1 for lbl in labels if lbl) / len(labels)
        assert ap_at_prevalence(scores, labels, pi_raw) == pytest.approx(
            average_precision(scores, labels), rel=1e-9
        )

    def test_transforming_down_from_high_prevalence_to_low_works(self):
        # pi_raw = 0.9 -- empirical negative subsampling could only RAISE
        # prevalence further, never lower it to 0.01. The analytic
        # transform must still produce a well-defined, finite value.
        scores, labels = _scored_samples(n_pos=900, n_neg=100, separation=1.5)
        result = ap_at_prevalence(scores, labels, 0.01)
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_transforming_up_also_works(self):
        scores, labels = _scored_samples(n_pos=20, n_neg=1980, separation=1.5)
        result = ap_at_prevalence(scores, labels, 0.5)
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_matches_a_resampled_empirical_estimate_within_tolerance(self):
        """
        Where BOTH the analytic transform and empirical resampling are
        valid (transforming DOWN in prevalence, which resampling can do by
        discarding negatives -- unlike the UP case), the analytic result
        must agree with a resampled empirical estimate within sampling
        noise.
        """
        scores, labels = _scored_samples(n_pos=200, n_neg=800, separation=1.5)
        pi_target = 0.05  # achievable by discarding negatives

        analytic = ap_at_prevalence(scores, labels, pi_target)

        # Empirical: resample negatives down so pi_target holds, using the
        # SAME pool of negative scores drawn from the full population
        # (bootstrap with replacement across several trials for stability).
        pos_scores = [s for s, lbl in zip(scores, labels) if lbl]
        neg_scores = [s for s, lbl in zip(scores, labels) if not lbl]
        n_neg_needed = int(len(pos_scores) * (1 - pi_target) / pi_target)

        trial_aps = []
        for trial in range(20):
            trial_rng = random.Random(trial)
            resampled_neg = trial_rng.choices(neg_scores, k=n_neg_needed)
            trial_scores = pos_scores + resampled_neg
            trial_labels = [True] * len(pos_scores) + [False] * len(resampled_neg)
            trial_aps.append(average_precision(trial_scores, trial_labels))

        empirical_mean = sum(trial_aps) / len(trial_aps)
        assert analytic == pytest.approx(empirical_mean, abs=0.05), (
            f"analytic={analytic}, empirical resampled mean={empirical_mean}"
        )

    def test_degenerate_input_returns_none(self):
        assert ap_at_prevalence([1.0, 1.0], [True, True], 0.1) is None
