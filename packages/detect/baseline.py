"""
Source: Day-6 Plan §3.1 / §3.7 -- `StoreBaseline`, the learned per-merchant
baseline that feeds Layer 2. `hourly_volume_profile` and `flagged_rate_mean`
(p_bar_0) drive lambda_0(t) for the CUSUM; `cards_per_ip_quantiles["30m"]`
gives L2b its q_hi.

Written by scripts/learn_store_baseline.py FROM NEGATIVE-CONTROL DATA ONLY
(the 7 m-eval-12..18 runs). Loaded by packages/storage/repository.py and
passed in here as a value object -- this module reads no DB.

PURE: no I/O, no `eval` import, no label source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

# The quantile grid `cards_per_ip_quantiles[window]` is sampled at, in order.
QUANTILE_GRID: Tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def interp_quantile(grid_values: Sequence[float], q: float) -> float:
    """Linear interpolation of a value at quantile `q` over QUANTILE_GRID."""
    if not grid_values:
        return 0.0
    vals = list(grid_values)
    if len(vals) == 1:
        return float(vals[0])
    q = min(max(q, 0.0), 1.0)
    n = len(vals)
    grid = QUANTILE_GRID if n == len(QUANTILE_GRID) else tuple(i / (n - 1) for i in range(n))
    for i in range(n - 1):
        lo_q, hi_q = grid[i], grid[i + 1]
        if lo_q <= q <= hi_q:
            if hi_q == lo_q:
                return float(vals[i])
            frac = (q - lo_q) / (hi_q - lo_q)
            return float(vals[i] + frac * (vals[i + 1] - vals[i]))
    return float(vals[-1])


@dataclass(frozen=True)
class StoreBaseline:
    merchant_id: str
    hourly_volume_profile: Tuple[float, ...]        # 24 floats -- attempts per hour of day
    flagged_rate_mean: float                        # p_bar_0 -- share with score_calibrated >= tau_flag
    cards_per_ip_quantiles: Dict[str, List[float]]  # {"5m": [...grid...], "30m": [...grid...]}
    is_stable: bool = False
    sample_count: int = 0

    def attempts_this_hour(self, hour: int) -> float:
        if not self.hourly_volume_profile:
            return 0.0
        return float(self.hourly_volume_profile[hour % len(self.hourly_volume_profile)])

    def card_quantile(self, window: str, q: float) -> float:
        grid = self.cards_per_ip_quantiles.get(window) or self.cards_per_ip_quantiles.get("30m") or []
        return interp_quantile(grid, q)
