"""
Source: Day-4 Plan (rev. 2) Step 5 -- pure stdlib metrics, no new
dependencies.

TIE CONVENTION (stated on line one, applied everywhere): scores are sorted
DESCENDING; equal scores collapse into a single operating point. This is
what makes the four sanity scorers analytically determinate (F19).

Degenerate input returns `None`, never `0.0` (F1): `None` is a sentinel
the report renders as `n/a (single-class split)` -- `0.0` is
indistinguishable from a real measurement of total failure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from eval.cost import CostModel, roc_convex_hull


def _degenerate(labels: Sequence[bool]) -> bool:
    """True if `labels` has fewer than one positive or one negative -- undefined for ranking metrics."""
    n_pos = sum(1 for lbl in labels if lbl)
    n = len(labels)
    return n == 0 or n_pos == 0 or n_pos == n


def roc_points(scores: Sequence[float], labels: Sequence[bool]) -> List[Tuple[float, float, float]]:
    """
    (fpr, tpr, threshold) at every distinct score value, sorted descending
    by threshold, PLUS the two trivial endpoints (threshold=+inf -> (0,0),
    threshold=-inf -> (1,1)). Equal scores collapse into one operating
    point (tie convention).
    """
    if not scores:
        return []
    n_pos = sum(1 for lbl in labels if lbl)
    n_neg = len(labels) - n_pos

    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    points: List[Tuple[float, float, float]] = [(0.0, 0.0, math.inf)]
    tp = fp = 0
    i = 0
    n = len(scores)
    while i < n:
        j = i
        threshold = scores[order[i]]
        while j < n and scores[order[j]] == threshold:
            if labels[order[j]]:
                tp += 1
            else:
                fp += 1
            j += 1
        fpr = fp / n_neg if n_neg else 0.0
        tpr = tp / n_pos if n_pos else 0.0
        points.append((fpr, tpr, threshold))
        i = j
    if points[-1][2] != -math.inf:
        points.append((points[-1][0], points[-1][1], -math.inf))
    return points


@dataclass(frozen=True)
class RecallAtFpr:
    value: Optional[float]
    n_neg: int
    resolvable: bool
    ci_low: Optional[float]
    ci_high: Optional[float]


def _wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """95% Wilson score interval for a binomial proportion. Handles n=0 (returns (0.0, 1.0))."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return max(0.0, low), min(1.0, high)


def recall_at_fpr(scores: Sequence[float], labels: Sequence[bool], target_fpr: float) -> Optional[RecallAtFpr]:
    """
    Recall (TPR) at the operating point achieving FPR closest to (but not
    exceeding) `target_fpr`. `resolvable = n_neg >= 1/target_fpr`: empirical
    FPR is quantised at 1/n_neg, so resolving 10^-3 needs >=1000 negatives.
    Returns None on degenerate input (no positives or no negatives at all).

    A scorer whose full ROC curve has only the two trivial endpoints
    (0,0)/(1,1) -- e.g. AlwaysPositiveScorer, which assigns one constant
    score to every sample -- has zero discriminating power: it never
    reaches any FPR strictly between 0 and 1, so `value` is `None`
    ("unreachable"), not a real 0.0. A scorer with a genuine (even if
    badly-discriminating, e.g. inverted) third point DOES have a
    well-defined recall at `target_fpr`, even when that recall is 0.0.
    """
    if _degenerate(labels):
        return None
    n_neg = sum(1 for lbl in labels if not lbl)
    resolvable = n_neg >= (1.0 / target_fpr if target_fpr > 0 else math.inf)

    points = roc_points(scores, labels)
    distinct_points = {(fpr, tpr) for fpr, tpr, _threshold in points}
    if len(distinct_points) <= 2:
        return RecallAtFpr(value=None, n_neg=n_neg, resolvable=resolvable, ci_low=None, ci_high=None)

    best_tpr = 0.0
    best_fp = 0
    for fpr, tpr, _threshold in points:
        if fpr <= target_fpr and tpr >= best_tpr:
            best_tpr = tpr
            best_fp = round(fpr * n_neg) if n_neg else 0

    ci_low, ci_high = _wilson_interval(best_fp, n_neg) if n_neg else (0.0, 1.0)
    return RecallAtFpr(value=best_tpr, n_neg=n_neg, resolvable=resolvable, ci_low=ci_low, ci_high=ci_high)


def average_precision(scores: Sequence[float], labels: Sequence[bool]) -> Optional[float]:
    """
    AP = (1/P) * sum over each positive item's rank r (1-indexed,
    descending score, STABLE ties -- Python's sort preserves each tied
    item's original relative order) of (tp_so_far / r). The standard
    rank-based AP definition, evaluated per item rather than per tied
    score group: a mixed tie group's internal order never actually needs
    resolving here because AP only accumulates a term when the CURRENT
    item is itself positive, so same-label ties (the only kind that can
    appear ambiguously ordered) never change the result. This is what
    gives all four sanity scorers an exact closed form (not trapezoid).
    None if degenerate.
    """
    if _degenerate(labels):
        return None
    n_pos = sum(1 for lbl in labels if lbl)
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    ap = 0.0
    tp = 0
    for rank, i in enumerate(order, start=1):
        if labels[i]:
            tp += 1
            ap += tp / rank
    return ap / n_pos


def ap_at_prevalence(scores: Sequence[float], labels: Sequence[bool], pi_target: float) -> Optional[float]:
    """
    Analytic prevalence transformation (F7, replaces empirical resampling):
    at each item's cumulative (fpr, tpr) -- computed the same per-item way
    `average_precision` is -- derive precision at any target prevalence
    pi' via
        precision'(fpr, tpr) = pi' * tpr / (pi' * tpr + (1 - pi') * fpr)
    and accumulate the same rank-based AP sum using that transformed
    precision. At pi_target == the sample's own raw prevalence, this
    reduces exactly to `average_precision` (the transform's pi'=pi_raw
    case simplifies precision'(fpr,tpr) back to tp/(tp+fp)). Exact and
    direction-free (works above or below the raw prevalence).
    """
    if _degenerate(labels):
        return None
    n_pos = sum(1 for lbl in labels if lbl)
    n_neg = len(labels) - n_pos
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    ap = 0.0
    tp = 0
    fp = 0
    for i in order:
        if labels[i]:
            tp += 1
        else:
            fp += 1
        if labels[i]:
            tpr = tp / n_pos
            fpr = fp / n_neg if n_neg else 0.0
            denom = pi_target * tpr + (1 - pi_target) * fpr
            precision = (pi_target * tpr) / denom if denom > 0 else 1.0
            ap += precision / n_pos
    return ap


def roc_auc(scores: Sequence[float], labels: Sequence[bool]) -> Optional[float]:
    """Mann-Whitney U statistic: P(a random positive score > a random negative score), ties -> 0.5. None if degenerate."""
    if _degenerate(labels):
        return None
    pos_scores = [s for s, lbl in zip(scores, labels) if lbl]
    neg_scores = [s for s, lbl in zip(scores, labels) if not lbl]

    combined = sorted(pos_scores + neg_scores)
    ranks = {}
    i = 0
    n = len(combined)
    while i < n:
        j = i
        while j < n and combined[j] == combined[i]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[combined[k]] = avg_rank
        i = j

    rank_sum_pos = sum(ranks[v] for v in pos_scores)
    n1, n2 = len(pos_scores), len(neg_scores)
    u1 = rank_sum_pos - n1 * (n1 + 1) / 2.0
    return u1 / (n1 * n2)


@dataclass(frozen=True)
class OperatingPoint:
    fpr: float
    tpr: float
    precision: Optional[float]
    recall: float
    tp: int
    fp: int
    tn: int
    fn: int


def operating_point(scores: Sequence[float], labels: Sequence[bool], theta: float) -> Optional[OperatingPoint]:
    """The (fpr, tpr, precision, recall, tp, fp, tn, fn) at threshold theta -- how discrete rules are reported (F5)."""
    if not scores:
        return None
    tp = fp = tn = fn = 0
    for s, lbl in zip(scores, labels):
        predicted_positive = s >= theta
        if predicted_positive and lbl:
            tp += 1
        elif predicted_positive and not lbl:
            fp += 1
        elif not predicted_positive and lbl:
            fn += 1
        else:
            tn += 1
    n_pos = tp + fn
    n_neg = tn + fp
    fpr = fp / n_neg if n_neg else 0.0
    tpr = tp / n_pos if n_pos else 0.0
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tpr
    return OperatingPoint(fpr=fpr, tpr=tpr, precision=precision, recall=recall, tp=tp, fp=fp, tn=tn, fn=fn)


def recall_at_matched_fpr(
    model_scores: Sequence[float], labels: Sequence[bool], baseline_fpr: float,
) -> Optional[float]:
    """The model's recall at the FPR a discrete baseline rule natively achieves -- the honest ranker-vs-rule comparator."""
    result = recall_at_fpr(model_scores, labels, baseline_fpr)
    return result.value if result is not None else None


def cost_over_operating_points(
    points: Sequence[Tuple[float, float]], cost_model: CostModel, pi: float, tier: str,
) -> List[Tuple[float, float, float]]:
    """(fpr, tpr, expected_cost_per_10k) over the achievable ROC-convex-hull frontier of `points`."""
    hull = roc_convex_hull(list(points))
    return [
        (fpr, tpr, cost_model.expected_cost_per_10k(tpr, fpr, pi, tier))
        for fpr, tpr in hull
    ]
