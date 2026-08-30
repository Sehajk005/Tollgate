"""
Source: Day-6 Plan §3.1 / TRD v2 §6.5 -- Layer 2a, a one-sided Poisson CUSUM
over tau_flag-gated attempt counts per 10-second bucket.

    n_t   = # attempts in bucket t with p_calibrated >= tau_flag
    lam0  = baseline_rate(hour_of_day) * bucket_s * p_bar_0     floored at lam_min
    lam1  = rho * lam0
    S_t   = max(0, S_{t-1} + n_t*ln(lam1/lam0) - (lam1 - lam0))
    alarm when S_t > h

This module is PURE: no I/O, no wall clock, no `eval` import, no label
source (tests/acceptance/test_detect_label_isolation.py). Every parameter
arrives as an argument; `h` is tuned elsewhere (scripts/tune_cusum.py) from
negative controls only and reaches the serving path via policy_config.

`steps_to_alarm(h, lam0, lam1)` is the closed form the analytic test
(tests/acceptance/test_cusum_analytic.py) compares the recursion against --
the test asserts the recursion vs the formula, never vs a recorded number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

MS_PER_HOUR = 3_600_000


def hour_of_day(ingest_ms: int) -> int:
    """Source: Day-6 Plan §3.1 -- derived arithmetically from ingest_ms so
    test_clock_discipline.py's AST scan stays green (no datetime) and M1
    (shift every ingest time by a whole number of hours) holds."""
    return (ingest_ms // MS_PER_HOUR) % 24


def baseline_lambda0(
    *, attempts_this_hour: float, bucket_s: int, flagged_rate_mean: float, lambda_min: float
) -> float:
    """
    lam0(t) = baseline_rate(hour) * bucket_s * p_bar_0, floored at lam_min.

    `attempts_this_hour` is store_baseline.hourly_volume_profile[hour] -- the
    learned mean number of attempts in that hour of day. Divided by 3600 it
    is the per-second baseline rate; * bucket_s gives expected attempts per
    bucket; * flagged_rate_mean (p_bar_0) gives expected tau_flag-gated
    attempts per bucket under H0.
    """
    per_second = max(attempts_this_hour, 0.0) / 3600.0
    lam0 = per_second * float(bucket_s) * max(flagged_rate_mean, 0.0)
    return max(lam0, float(lambda_min))


def poisson_cusum_increment(n_t: int, lam0: float, lam1: float) -> float:
    """One bucket's additive term: n_t*ln(lam1/lam0) - (lam1 - lam0).

    With n_t == 0 this is exactly -(lam1 - lam0) -- the empty-bucket decay
    the analytic test checks to the bit."""
    return n_t * math.log(lam1 / lam0) - (lam1 - lam0)


def steps_to_alarm(h: float, lam0: float, lam1: float) -> float:
    """
    Source: Day-6 Plan §3.1 -- closed form for the number of fully-loaded
    buckets (each carrying n_t = lam1 attempts, the sustained attack rate)
    needed to drive S_t from 0 past h:

        h / (lam1*ln(lam1/lam0) - (lam1 - lam0))

    The denominator is the per-bucket drift under H1; it is > 0 whenever
    lam1 > lam0 (a standard Poisson-CUSUM fact). Raises if lam1 <= lam0.
    """
    if lam1 <= lam0:
        raise ValueError(f"steps_to_alarm requires lam1 > lam0 (got lam0={lam0}, lam1={lam1})")
    drift_per_bucket = lam1 * math.log(lam1 / lam0) - (lam1 - lam0)
    return h / drift_per_bucket


@dataclass(frozen=True)
class CusumParams:
    rho: float          # lam1 = rho * lam0   (policy_config.cusum_rho, TRD §11)
    h: float            # alarm threshold     (policy_config.cusum_h, tuned)
    bucket_s: int       # bucket width, seconds
    lambda_min: float   # lam0 floor          (config/policy.yaml cusum.lambda_min)


@dataclass(frozen=True)
class CusumStep:
    """The result of folding one bucket (or a provisional fold of the live
    bucket) into the statistic."""

    bucket_index: int
    s: float            # S_t after this bucket
    alarm: bool         # S_t > h
    n_t: int            # gated count in this bucket
    lam0: float
    rate_ratio: float   # n_t / lam0  -- feeds serving_prior("alarm", rate_ratio=...)


class PoissonCusum:
    """
    Bucket-indexed one-sided Poisson CUSUM. `observe()` folds a single
    bucket; the caller is responsible for bucket accounting (which bucket a
    given attempt belongs to, and feeding empty buckets for gaps). Holding
    `S_t` on alarm (no reset) is the caller's policy -- this object simply
    reports `alarm = S_t > h` after each fold, and a sustained attack keeps
    S_t elevated because every loaded bucket adds positive drift.

    Pure fold over the bucket sequence: feeding the same buckets in the same
    order always yields the same S_t (Impl Plan §1.4 M8).
    """

    def __init__(self, params: CusumParams) -> None:
        self._p = params
        self._s = 0.0
        self._last_bucket: Optional[int] = None

    @property
    def s(self) -> float:
        return self._s

    @property
    def last_bucket(self) -> Optional[int]:
        return self._last_bucket

    def _step_value(self, s_prev: float, n_t: int, lam0: float) -> float:
        lam1 = self._p.rho * lam0
        return max(0.0, s_prev + poisson_cusum_increment(n_t, lam0, lam1))

    def peek(self, bucket_index: int, n_t: int, lam0: float) -> CusumStep:
        """Compute the step WITHOUT committing it -- used for the provisional
        fold of the still-filling live bucket."""
        s = self._step_value(self._s, n_t, lam0)
        return CusumStep(
            bucket_index=bucket_index, s=s, alarm=s > self._p.h, n_t=n_t, lam0=lam0,
            rate_ratio=(n_t / lam0) if lam0 > 0 else 0.0,
        )

    def observe(self, bucket_index: int, n_t: int, lam0: float) -> CusumStep:
        """Fold one bucket and commit S_t."""
        step = self.peek(bucket_index, n_t, lam0)
        self._s = step.s
        self._last_bucket = bucket_index
        return step

    def reset(self) -> None:
        self._s = 0.0
        self._last_bucket = None
