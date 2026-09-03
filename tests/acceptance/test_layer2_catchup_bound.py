"""
Source: remediation plan §11.5 / FIX-002 -- the proof that bounding
`Layer2Engine._commit_through()` is ANSWER-PRESERVING, not a mitigation.

The bound may only be accepted as a fix, rather than a workaround, if crossing
it produces the same statistic the unbounded fold would have produced. That is
asserted here DIFFERENTIALLY: `_reference_commit_through` below is the exact
loop Day 6 shipped, and the bounded implementation must agree with it
field-for-field on every observable of `_MerchantCusum`.

It also pins the two things the plan insisted be measured rather than assumed:

  * the equivalence horizon is COMPUTED from (rho, lambda_min), and
    MAX_CATCHUP_BUCKETS must exceed the worst case a real replay produces;
  * ordinary operation never reaches the bound -- a 3-hour replay spans ~1 076
    buckets, so the discontinuity branches are dead code during a normal run
    and behaviour is byte-identical to Day 6.
"""

from __future__ import annotations

import math

import pytest

from packages.detect.layer2 import MAX_CATCHUP_BUCKETS, Layer2Engine
from tests.acceptance.test_layer2_time_discontinuity import MERCHANT, build_engine

# The four tiers' peak statistic, measured by replaying seed 42 under the
# pessimistic assumption that every attempt is tau_flag-gated. Recorded so a
# future parameter change that invalidates the horizon fails loudly here.
MEASURED_PEAK_S = 948.195
MEASURED_BUCKETS_TO_FLOOR = 11_853
REPLAY_BUCKET_SPAN = 1_076


def _reference_commit_through(engine: Layer2Engine, merchant_id: str, target_bucket: int) -> None:
    """The ORIGINAL unbounded loop, verbatim from Day 6 (`layer2.py:119-133`
    before FIX-002). The differential oracle -- deliberately not sharing code
    with the implementation under test."""
    mc = engine._merchant(merchant_id)
    if mc.pending_bucket is None:
        mc.pending_bucket = target_bucket
        mc.pending_n = 0
        return
    while mc.pending_bucket < target_bucket:
        bucket_start_ms = mc.pending_bucket * engine._cp.bucket_s * 1000
        lam0 = engine._lambda0(bucket_start_ms)
        step = mc.cusum.observe(mc.pending_bucket, mc.pending_n, lam0)
        mc.committed_bucket = mc.pending_bucket
        mc.committed_alarm = step.alarm
        mc.committed_rate_ratio = step.rate_ratio
        mc.pending_bucket += 1
        mc.pending_n = 0


def _observable(engine: Layer2Engine, merchant_id: str = MERCHANT) -> tuple:
    mc = engine._merchant(merchant_id)
    return (
        round(mc.cusum.s, 12),
        mc.cusum.last_bucket,
        mc.committed_bucket,
        mc.committed_alarm,
        round(mc.committed_rate_ratio, 12),
        mc.pending_bucket,
        mc.pending_n,
    )


def _load(engine: Layer2Engine, loaded_buckets: int, n_per_bucket: int) -> int:
    """Drive the merchant CUSUM into a genuinely elevated state -- a crossing
    from S == 0 would prove nothing about equivalence. Returns the next bucket."""
    for bucket in range(loaded_buckets):
        engine._commit_through(MERCHANT, bucket)
        mc = engine._merchant(MERCHANT)
        mc.pending_bucket = bucket
        mc.pending_n = n_per_bucket
    return loaded_buckets


class TestEquivalenceWithTheUnboundedFold:
    @pytest.mark.parametrize(
        "gap",
        [
            MAX_CATCHUP_BUCKETS + 1,       # just past the bound
            2 * MAX_CATCHUP_BUCKETS,       # the plan's 2x horizon
            5 * MAX_CATCHUP_BUCKETS,       # comfortably past it
        ],
    )
    def test_bounded_crossing_equals_the_unbounded_fold(self, gap):
        bounded, reference = build_engine(), build_engine()
        for engine in (bounded, reference):
            _load(engine, loaded_buckets=200, n_per_bucket=12)

        assert reference._merchant(MERCHANT).cusum.s > 0.0, "the prefix did not load the statistic"
        assert _observable(bounded) == _observable(reference), "the prefixes diverged"

        target = 200 + gap
        bounded._commit_through(MERCHANT, target)
        _reference_commit_through(reference, MERCHANT, target)

        assert _observable(bounded) == _observable(reference), (
            "the bounded catch-up produced a different statistic from the unbounded "
            "fold -- the bound is a mitigation, not a fix"
        )

    def test_equivalence_holds_from_an_alarming_state(self):
        bounded, reference = build_engine(), build_engine()
        for engine in (bounded, reference):
            _load(engine, loaded_buckets=400, n_per_bucket=40)
        # Commit the loaded prefix so `committed_alarm` is genuinely True.
        bounded._commit_through(MERCHANT, 401)
        _reference_commit_through(reference, MERCHANT, 401)
        assert bounded._merchant(MERCHANT).committed_alarm is True, "prefix never alarmed"
        assert _observable(bounded) == _observable(reference)

        target = 401 + 3 * MAX_CATCHUP_BUCKETS
        bounded._commit_through(MERCHANT, target)
        _reference_commit_through(reference, MERCHANT, target)
        assert _observable(bounded) == _observable(reference)
        assert bounded._merchant(MERCHANT).committed_alarm is False, (
            "an alarm survived a full horizon of empty buckets -- the statistic did not decay"
        )

    def test_inside_the_horizon_the_loop_is_byte_identical(self):
        """Ordinary operation must not change at all. Anything up to the bound
        takes the same path it always did."""
        bounded, reference = build_engine(), build_engine()
        for engine in (bounded, reference):
            _load(engine, loaded_buckets=120, n_per_bucket=9)
        target = 120 + MAX_CATCHUP_BUCKETS  # exactly AT the bound -- not past it
        bounded._commit_through(MERCHANT, target)
        _reference_commit_through(reference, MERCHANT, target)
        assert _observable(bounded) == _observable(reference)


class TestTheHorizonIsMeasuredNotAssumed:
    def test_max_catchup_buckets_exceeds_the_measured_worst_case(self):
        engine = build_engine()
        to_floor = engine._empty_buckets_to_floor(MEASURED_PEAK_S)
        assert to_floor == MEASURED_BUCKETS_TO_FLOOR, (
            f"the provable decay horizon moved to {to_floor} (was "
            f"{MEASURED_BUCKETS_TO_FLOOR}); re-measure before trusting the bound"
        )
        assert MAX_CATCHUP_BUCKETS > to_floor, (
            f"MAX_CATCHUP_BUCKETS={MAX_CATCHUP_BUCKETS} is below the measured "
            f"{to_floor}-bucket CUSUM memory, so a crossing could not claim "
            f"equivalence. This is exactly why the plan's proposed 8 640 was rejected."
        )

    def test_the_decay_floor_is_derived_from_the_live_parameters(self):
        engine = build_engine()
        rho, lambda_min = engine._cp.rho, engine._cp.lambda_min
        expected = math.ceil(100.0 / ((rho - 1.0) * lambda_min))
        assert engine._empty_buckets_to_floor(100.0) == expected

    def test_a_non_decaying_parameterisation_reports_no_proof(self):
        """rho <= 1 makes lam1 <= lam0, so an empty bucket never reduces S.
        The helper must say so rather than return a number nobody can trust."""
        from packages.detect.cusum import CusumParams

        engine = build_engine()
        engine._cp = CusumParams(rho=1.0, h=3.0, bucket_s=10, lambda_min=0.02)
        assert engine._empty_buckets_to_floor(50.0) is None

    def test_a_non_decaying_parameterisation_still_terminates(self):
        """No proof is available, so the crossing must be bounded and reset --
        never an unbounded spin."""
        from packages.detect.cusum import CusumParams

        engine = build_engine()
        _load(engine, loaded_buckets=50, n_per_bucket=20)
        engine._cp = CusumParams(rho=1.0, h=3.0, bucket_s=10, lambda_min=0.02)
        target = 50 + 40 * MAX_CATCHUP_BUCKETS
        engine._commit_through(MERCHANT, target)
        mc = engine._merchant(MERCHANT)
        assert mc.pending_bucket == target
        assert mc.cusum.s == 0.0


class TestBackwardDiscontinuity:
    def test_a_far_backward_jump_relocates_the_merchant_to_the_new_domain(self):
        engine = build_engine()
        _load(engine, loaded_buckets=50, n_per_bucket=20)
        engine._commit_through(MERCHANT, 175_600_000)
        engine._commit_through(MERCHANT, 0)
        mc = engine._merchant(MERCHANT)
        assert mc.pending_bucket == 0
        assert mc.cusum.s == 0.0
        assert mc.committed_alarm is False

    def test_a_backward_jump_inside_the_horizon_is_unchanged(self):
        """Small out-of-order arrivals keep Day 6's behaviour exactly: the loop
        does not run and no state moves."""
        bounded, reference = build_engine(), build_engine()
        for engine in (bounded, reference):
            _load(engine, loaded_buckets=100, n_per_bucket=5)
        bounded._commit_through(MERCHANT, 90)
        _reference_commit_through(reference, MERCHANT, 90)
        assert _observable(bounded) == _observable(reference)


class TestOrdinaryOperationNeverReachesTheBound:
    def test_a_three_hour_replay_spans_far_fewer_buckets_than_the_bound(self):
        assert REPLAY_BUCKET_SPAN < MAX_CATCHUP_BUCKETS / 4, (
            "a normal replay is close enough to the bound that ordinary "
            "operation could take the discontinuity path"
        )

    def test_the_discontinuity_path_is_never_taken_during_a_full_easy_replay(self):
        from packages.simulator.generate import build_stream

        engine = build_engine()
        calls = []
        forward = engine._commit_forward_discontinuity
        backward = engine._commit_backward_discontinuity

        def spy_forward(*args, **kwargs):
            calls.append(("forward", args))
            return forward(*args, **kwargs)

        def spy_backward(*args, **kwargs):
            calls.append(("backward", args))
            return backward(*args, **kwargs)

        engine._commit_forward_discontinuity = spy_forward  # type: ignore[method-assign]
        engine._commit_backward_discontinuity = spy_backward  # type: ignore[method-assign]

        for ev in build_stream(seed=42, tier="easy", hours=3).events:
            engine._commit_through(MERCHANT, ev.t_ms // 10_000)

        assert calls == [], (
            f"a normal easy replay took the discontinuity path {len(calls)} time(s) -- "
            f"ordinary behaviour is NOT byte-identical to Day 6"
        )
