"""
Source: Day-6 Plan §4 (tests/unit, advisory) -- Lambda accumulation, the
one-sided clamp, and the threshold A for the L2b Wald SPRT.
"""

from __future__ import annotations

import math

from packages.detect.drift import DriftParams, SequentialDrift, sprt_threshold_A


def _params(enabled=True):
    return DriftParams(exceedance_quantile=0.95, p1=0.5, alpha=0.01, beta=0.05, enabled=enabled)


def test_threshold_A_is_wald_upper_boundary():
    assert math.isclose(sprt_threshold_A(0.01, 0.05), math.log(0.95 / 0.01))
    assert 4.5 < _params().A < 4.6


def test_exceedances_accumulate_and_non_exceedances_clamp_at_zero():
    p = _params()
    d = SequentialDrift(p)
    for _ in range(10):
        step = d.observe(stat=0.0, q_hi=5.0)
        assert step.z == 0
        assert step.lam == 0.0
    up = math.log(p.p1 / p.p0)
    for i in range(1, 6):
        step = d.observe(stat=10.0, q_hi=5.0)
        assert step.z == 1
        assert math.isclose(step.lam, i * up, rel_tol=1e-9)


def test_fires_when_lambda_crosses_A():
    p = _params()
    d = SequentialDrift(p)
    fired_at = None
    for i in range(20):
        step = d.observe(stat=100.0, q_hi=10.0)
        if step.fired and fired_at is None:
            fired_at = i + 1
    up = math.log(p.p1 / p.p0)
    assert fired_at == math.ceil(p.A / up)


def test_disabled_never_fires():
    d = SequentialDrift(_params(enabled=False))
    for _ in range(50):
        assert d.observe(stat=100.0, q_hi=1.0).fired is False


def test_q_hi_zero_is_never_an_exceedance():
    d = SequentialDrift(_params())
    for _ in range(10):
        assert d.observe(stat=0.0, q_hi=0.0).z == 0
