"""
Source: Day-6 Plan §3.2 / TRD v2 §6.6 -- Layer 2b, a one-sided Wald SPRT on
95th-percentile exceedance of `distinct_cards_per_ip_30m`. TRD §6.6 gives
the shape ("sequential test on distinct card hashes per entity over 30
virtual minutes, scored as a quantile against the store's own learned
distribution"); the statistic, firing quantile and threshold are Day-6 Plan
decisions D4/D5.

    q_hi = store_baseline.cards_per_ip_quantiles["30m"] 95th percentile
    z_i  = 1[distinct_cards_per_ip_30m >= q_hi]
    p0   = 1 - exceedance_quantile   (= 0.05 BY CONSTRUCTION of the quantile)
    p1   = 0.5                        (Day-6 Plan D4)
    Lam_i = max(0, Lam_{i-1} + z_i*ln(p1/p0) + (1-z_i)*ln((1-p1)/(1-p0)))
    fire when Lam_i >= A = ln((1 - beta) / alpha)

PURE: no I/O, no wall clock, no `eval` import, no label source. `q_hi` and
every rate arrive as arguments.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def sprt_threshold_A(alpha: float, beta: float) -> float:
    """Wald's upper boundary ln((1 - beta) / alpha). With alpha=0.01,
    beta=0.05 this is ~4.5539."""
    return math.log((1.0 - beta) / alpha)


@dataclass(frozen=True)
class DriftParams:
    exceedance_quantile: float   # 0.95 -> p0 = 0.05  (config/policy.yaml drift.exceedance_quantile)
    p1: float                    # 0.5                 (config/policy.yaml drift.p1)
    alpha: float                 # 0.01
    beta: float                  # 0.05
    enabled: bool = True         # config/policy.yaml drift.enabled -- the L2b cut switch

    @property
    def p0(self) -> float:
        return 1.0 - self.exceedance_quantile

    @property
    def A(self) -> float:
        return sprt_threshold_A(self.alpha, self.beta)


@dataclass(frozen=True)
class DriftStep:
    lam: float          # Lambda_i after this observation
    fired: bool         # Lambda_i >= A  (and params.enabled)
    z: int              # 1[stat >= q_hi]
    q_hi: float
    stat: float         # distinct_cards_per_ip_30m for this attempt


class SequentialDrift:
    """
    One-sided Wald SPRT accumulator for a single entity. `observe(stat,
    q_hi)` adds one Bernoulli exceedance observation. Clamped at 0 (a run of
    non-exceedances cannot bank negative "credit"), sequential, and a pure
    fold over the per-entity observation prefix (M8 holds).

    When `params.enabled` is False the accumulator still runs but `fired` is
    always False -- the Day-6 §9 cut leaves drift.py in place and inert.
    """

    def __init__(self, params: DriftParams) -> None:
        self._p = params
        self._lam = 0.0

    @property
    def lam(self) -> float:
        return self._lam

    def _increment(self, z: int) -> float:
        if z:
            return math.log(self._p.p1 / self._p.p0)
        return math.log((1.0 - self._p.p1) / (1.0 - self._p.p0))

    def peek(self, stat: float, q_hi: float) -> DriftStep:
        z = 1 if (q_hi > 0.0 and stat >= q_hi) else 0
        lam = max(0.0, self._lam + self._increment(z))
        fired = self._p.enabled and lam >= self._p.A
        return DriftStep(lam=lam, fired=fired, z=z, q_hi=q_hi, stat=float(stat))

    def observe(self, stat: float, q_hi: float) -> DriftStep:
        step = self.peek(stat, q_hi)
        self._lam = step.lam
        return step

    def reset(self) -> None:
        self._lam = 0.0
