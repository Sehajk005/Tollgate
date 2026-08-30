"""
Source: Day-6 Plan §4 (tests/unit, advisory) -- S_t arithmetic edge cases,
lambda_min flooring, hour_of_day wrap. Advisory, builder-written, never
cited as a gate.
"""

from __future__ import annotations

import math

from packages.detect.cusum import (
    CusumParams,
    PoissonCusum,
    baseline_lambda0,
    hour_of_day,
    poisson_cusum_increment,
    steps_to_alarm,
)


def test_hour_of_day_is_arithmetic_and_wraps():
    assert hour_of_day(0) == 0
    assert hour_of_day(3_600_000) == 1
    assert hour_of_day(23 * 3_600_000) == 23
    assert hour_of_day(24 * 3_600_000) == 0  # wrap
    assert hour_of_day(49 * 3_600_000) == 1


def test_baseline_lambda0_is_floored_at_lambda_min():
    assert baseline_lambda0(
        attempts_this_hour=0.0, bucket_s=10, flagged_rate_mean=0.5, lambda_min=0.01
    ) == 0.01
    lam = baseline_lambda0(
        attempts_this_hour=3600.0, bucket_s=10, flagged_rate_mean=0.5, lambda_min=0.01
    )
    assert math.isclose(lam, 1.0 * 10 * 0.5)  # 3600/3600 = 1 per second


def test_empty_bucket_decays_S_by_exactly_lam1_minus_lam0():
    lam0 = 2.0
    params = CusumParams(rho=5.0, h=100.0, bucket_s=10, lambda_min=0.01)
    lam1 = params.rho * lam0
    cusum = PoissonCusum(params)
    for b in range(5):
        cusum.observe(b, 20, lam0)
    s_before = cusum.s
    step = cusum.observe(5, 0, lam0)
    assert math.isclose(s_before - step.s, lam1 - lam0, rel_tol=1e-12)


def test_S_is_clamped_at_zero():
    lam0 = 1.0
    params = CusumParams(rho=4.0, h=50.0, bucket_s=10, lambda_min=0.01)
    cusum = PoissonCusum(params)
    for b in range(20):
        step = cusum.observe(b, 0, lam0)
        assert step.s >= 0.0
    assert cusum.s == 0.0


def test_increment_with_zero_n_is_negative_drift():
    assert math.isclose(poisson_cusum_increment(0, 2.0, 10.0), -(10.0 - 2.0))


def test_steps_to_alarm_matches_recursion_on_a_sustained_step():
    lam0, rho, h = 1.5, 5.0, 40.0
    lam1 = rho * lam0
    params = CusumParams(rho=rho, h=h, bucket_s=10, lambda_min=0.01)
    cusum = PoissonCusum(params)
    predicted = steps_to_alarm(h, lam0, lam1)
    steps = 0
    for b in range(1000):
        steps += 1
        step = cusum.observe(b, round(lam1), lam0)
        if step.alarm:
            break
    # closed form uses exact lam1; recursion here uses round(lam1) -- agree
    # to within one bucket for a clean integer-ish lam1.
    assert abs(steps - predicted) <= 1.5


def test_steps_to_alarm_raises_when_lam1_not_greater_than_lam0():
    raised = False
    try:
        steps_to_alarm(10.0, 2.0, 2.0)
    except ValueError:
        raised = True
    assert raised
