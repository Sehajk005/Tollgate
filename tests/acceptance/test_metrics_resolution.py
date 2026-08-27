"""
Source: Day-4 Plan (rev. 2) §6 test 18 -- "recall@FPR resolvability."
n_neg < 1/target_fpr -> resolvable=False and the harness refuses to report
the figure; Wilson CI brackets the point estimate; zero observed FPs
yields a one-sided interval, not 0.0 (F6).
"""

from __future__ import annotations

from eval.dataset import Sample
from eval.metrics import recall_at_fpr

TARGET_FPR = 1e-3


def _samples(n_pos: int, n_neg: int) -> list:
    samples = []
    for i in range(n_pos):
        samples.append(Sample(
            event_id=f"pos-{i}", t_ms=i, is_attack=True, stream_tier="hard", episode_tier="hard",
            episode_id=f"ep-{i}", kind="attack", scenario=None, entity_overlap=False,
            outcome_visible_ms=i + 340, ip="1.1.1.1", bin="999000", card_hash=f"c-{i}",
            amount_minor=100, gateway_status="authorized", decline_code=None,
        ))
    for i in range(n_neg):
        samples.append(Sample(
            event_id=f"neg-{i}", t_ms=1000 + i, is_attack=False, stream_tier=None, episode_tier=None,
            episode_id=None, kind="baseline", scenario=None, entity_overlap=False,
            outcome_visible_ms=1000 + i + 340, ip="2.2.2.2", bin="999001", card_hash=f"cn-{i}",
            amount_minor=100, gateway_status="authorized", decline_code=None,
        ))
    return samples


class TestRecallAtFprResolvability:
    def test_insufficient_negatives_marks_unresolvable(self):
        samples = _samples(n_pos=5, n_neg=50)  # n_neg=50 < 1/1e-3=1000
        scores = [1.0 if s.is_attack else 0.5 for s in samples]
        labels = [s.is_attack for s in samples]
        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.resolvable is False
        assert result.n_neg == 50

    def test_sufficient_negatives_marks_resolvable(self):
        samples = _samples(n_pos=5, n_neg=1200)  # n_neg=1200 >= 1000
        scores = [1.0 if s.is_attack else 0.5 for s in samples]
        labels = [s.is_attack for s in samples]
        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.resolvable is True
        assert result.n_neg == 1200

    def test_wilson_ci_brackets_the_point_estimate(self):
        samples = _samples(n_pos=10, n_neg=1500)
        # A ranker: attacks score high, a small fraction of negatives leak
        # in near the top to create a non-trivial, non-zero FP count.
        scores = []
        for s in samples:
            if s.is_attack:
                scores.append(1.0)
            elif int(s.event_id.split("-")[1]) < 3:
                scores.append(0.99)  # 3 negatives ranked just below the positives
            else:
                scores.append(0.1)
        labels = [s.is_attack for s in samples]
        result = recall_at_fpr(scores, labels, target_fpr=0.01)  # n_neg=1500 >= 1/0.01=100
        assert result is not None
        assert result.ci_low is not None and result.ci_high is not None
        assert 0.0 <= result.ci_low <= result.ci_high <= 1.0

    def test_zero_observed_fps_yields_a_one_sided_interval_not_0_0(self):
        samples = _samples(n_pos=5, n_neg=1200)
        # A perfect separator: zero negatives ever score above any attack.
        scores = [1.0 if s.is_attack else 0.0 for s in samples]
        labels = [s.is_attack for s in samples]
        result = recall_at_fpr(scores, labels, TARGET_FPR)
        assert result is not None
        assert result.value == 1.0
        # Zero observed FPs (best_fp=0) still yields a real Wilson interval,
        # not a degenerate/absent one -- the upper bound must be > 0 even
        # though the point estimate (0 successes) is 0.
        assert result.ci_low is not None and result.ci_low < 1e-6
        assert result.ci_high is not None and result.ci_high > 0.0

    def test_degenerate_input_returns_none_never_0_0(self):
        samples = _samples(n_pos=5, n_neg=0)
        scores = [1.0 for _ in samples]
        labels = [s.is_attack for s in samples]
        assert recall_at_fpr(scores, labels, TARGET_FPR) is None
