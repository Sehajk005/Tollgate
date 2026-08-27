"""
Source: Day-4 Plan (rev. 2) §6 tests 2-5 -- the exit gate. "Four sanity
scorers produce four analytically expected reports."

Test 2 -- Perfect scorer: recall@1e-3 == 1.0; AP == 1.0; ROC-AUC == 1.0.
Test 3 -- Random scorer: tolerance derived a priori (F19), not fitted:
    |AP - pi| <= 3*sqrt(pi*(1-pi)/N), |AUC - 0.5| <= 3*sqrt(1/(12*min(P,N-P))),
    across 5 seeds.
Test 4 -- Inverted scorer (the only sign-error test): ROC-AUC == 0.0;
    recall@1e-3 == 0.0; AP == (1/P)*sum_{k=1..P} k/(N-P+k), strictly < pi,
    guarded P >= 2 (at P=1, AP = 1/N = pi exactly).
Test 5 -- Always-positive scorer: two operating points only ->
    recall@1e-3 is None (unreachable), not 0.0; AP == pi; ROC-AUC == 0.5.
"""

from __future__ import annotations

import math

import pytest

from eval.dataset import Sample
from eval.metrics import average_precision, recall_at_fpr, roc_auc, roc_points
from eval.scorers import AlwaysPositiveScorer, InvertedScorer, PerfectScorer, RandomScorer

TARGET_FPR = 1e-3


def _make_samples(n: int, n_pos: int) -> list:
    """
    n samples with n_pos attacks EVENLY SPACED (every n/n_pos-th position,
    not clustered) through the input order. This matters specifically for
    AlwaysPositiveScorer: when every score is identically tied, Python's
    stable sort preserves input order, so average_precision's per-item
    ranking is computed over exactly THIS arrangement -- evenly-spaced
    positives make the k-th positive land at rank k*(n/n_pos), giving
    precision-at-rank = k/(k*(n/n_pos)) = n_pos/n = pi, CONSTANT for every
    k, which is what makes AP == pi an exact (not merely expected-value)
    identity (test 5). A front-loaded or random arrangement would not.
    """
    spacing = n // n_pos
    samples = []
    for i in range(n):
        is_attack = (i + 1) % spacing == 0 and i < spacing * n_pos
        samples.append(Sample(
            event_id=f"e-{i}", t_ms=i * 1000, is_attack=is_attack, stream_tier="hard" if is_attack else None,
            episode_tier="hard" if is_attack else None, episode_id=f"ep-{i}" if is_attack else None,
            kind="attack" if is_attack else "baseline", scenario=None, entity_overlap=False,
            outcome_visible_ms=i * 1000 + 340, ip=f"1.1.1.{i % 250}", bin="999000",
            card_hash=f"card-{i}", amount_minor=1000, gateway_status="authorized", decline_code=None,
        ))
    assert sum(1 for s in samples if s.is_attack) == n_pos
    return samples


N = 2000
N_POS = 20  # pi = 0.01, n_neg = 1980 >= 1/1e-3 = 1000 -- resolvable at target_fpr


class TestPerfectScorer:
    def test_recall_at_1e3_ap_and_auc_are_all_1_0(self):
        samples = _make_samples(N, N_POS)
        scorer = PerfectScorer()
        scores = [scorer(s) for s in samples]
        labels = [s.is_attack for s in samples]

        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.resolvable
        assert result.value == 1.0
        assert average_precision(scores, labels) == 1.0
        assert roc_auc(scores, labels) == 1.0


class TestRandomScorer:
    def test_ap_and_auc_within_a_priori_derived_tolerance_across_5_seeds(self):
        samples = _make_samples(N, N_POS)
        labels = [s.is_attack for s in samples]
        n_pos = sum(1 for lbl in labels if lbl)
        n_neg = len(labels) - n_pos
        pi = n_pos / len(labels)

        ap_tolerance = 3 * math.sqrt(pi * (1 - pi) / len(labels))
        auc_tolerance = 3 * math.sqrt(1 / (12 * min(n_pos, n_neg)))

        for seed in (1, 2, 3, 4, 5):
            scorer = RandomScorer(seed=seed)
            scores = [scorer(s) for s in samples]
            ap = average_precision(scores, labels)
            auc = roc_auc(scores, labels)
            assert abs(ap - pi) <= ap_tolerance, f"seed {seed}: AP={ap} pi={pi} tol={ap_tolerance}"
            assert abs(auc - 0.5) <= auc_tolerance, f"seed {seed}: AUC={auc} tol={auc_tolerance}"


class TestInvertedScorer:
    def test_auc_0_recall_0_ap_matches_closed_form(self):
        samples = _make_samples(N, N_POS)
        scorer = InvertedScorer()
        scores = [scorer(s) for s in samples]
        labels = [s.is_attack for s in samples]

        assert roc_auc(scores, labels) == 0.0
        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.value == 0.0

        n = len(labels)
        p = sum(1 for lbl in labels if lbl)
        assert p >= 2, "closed-form guard requires P >= 2"
        expected_ap = sum(k / (n - p + k) for k in range(1, p + 1)) / p
        actual_ap = average_precision(scores, labels)
        assert actual_ap == pytest.approx(expected_ap, rel=1e-9)
        assert actual_ap < p / n  # strictly less than pi

    def test_closed_form_guard_p_equals_1_is_exact_pi(self):
        samples = _make_samples(500, 1)
        scorer = InvertedScorer()
        scores = [scorer(s) for s in samples]
        labels = [s.is_attack for s in samples]
        ap = average_precision(scores, labels)
        assert ap == pytest.approx(1 / len(labels), rel=1e-9)


class TestAlwaysPositiveScorer:
    def test_recall_is_none_ap_equals_pi_auc_equals_0_5(self):
        samples = _make_samples(N, N_POS)
        scorer = AlwaysPositiveScorer()
        scores = [scorer(s) for s in samples]
        labels = [s.is_attack for s in samples]
        pi = sum(1 for lbl in labels if lbl) / len(labels)

        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.value is None, (
            f"AlwaysPositiveScorer has only two trivial ROC points (0,0)/(1,1) -- zero "
            f"discriminating power -- recall@{TARGET_FPR} must be None (unreachable), "
            f"got {result.value!r}"
        )

        points = roc_points(scores, labels)
        distinct_points = {(p[0], p[1]) for p in points}
        assert distinct_points == {(0.0, 0.0), (1.0, 1.0)}, f"expected only 2 operating points, got {distinct_points}"

        assert average_precision(scores, labels) == pytest.approx(pi, rel=1e-9)
        assert roc_auc(scores, labels) == 0.5
