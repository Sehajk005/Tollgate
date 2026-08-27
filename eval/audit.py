"""
Source: Day-4 Plan (rev. 2) Step 9 -- the discriminability-audit statistic
only. The audit itself (running it over the feature_snapshot corpus,
deciding whether amount_is_floor is reinstated) is Day 5 BY DEPENDENCY,
not preference (F12): it needs Day 5's replay to produce feature_snapshot
rows, and `Sample` (eval/dataset.py) deliberately carries raw event fields
rather than a feature vector -- recomputing features offline is banned by
TRD §6.4.
"""

from __future__ import annotations

from typing import Optional, Sequence

from eval.metrics import roc_auc


def univariate_auc(values: Sequence[float], labels: Sequence[bool]) -> Optional[float]:
    """
    AUC-equivalent separability of one numeric value stream alone (P(a
    random positive's value > a random negative's value), ties -> 0.5).
    Reuses the same Mann-Whitney statistic `eval.metrics.roc_auc` uses --
    one implementation, not a second copy.
    """
    return roc_auc(list(values), list(labels))
