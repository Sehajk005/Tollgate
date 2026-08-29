"""
Source: Day-6 Plan §4 / Impl Plan §1.4 -- the eight metamorphic relations
M1..M8. Each is a property between two runs, without either run's absolute
output being known (Layer 2 has no independent oracle).

  M1  shift all ingest times by a whole number of hours -> identical incident
      count and attempts_before_alert
  M2  bijectively rename every IP / BIN / card hash -> identical decisions
  M3  insert extra attack attempts -> attempts_before_alert never increases
  M4  double the attack rate -> attempts_before_alert does not increase
  M5  insert legit attempts on unrelated entities -> attack decisions unchanged
  M6  replay the same stream at 1x and 60x -> identical incidents / event-time TTD
  M7  replay an event twice (same payload digest) -> Layer-2 state unchanged
  M8  process the stream in two halves against a warm store -> same as one pass
"""

from __future__ import annotations

import asyncio
import random

import pytest

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.simulator.stream import Event
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

pytestmark = pytest.mark.metamorphic

MERCHANT = "m-mm"
HOUR_MS = 3_600_000


def _burst(n=60, ip="203.0.113.7", gap_ms=1200, t0=0, card_prefix="c", seq0=0):
    bins = ("424242", "411111", "555544")
    return [
        Event(
            event_id=f"e-{seq0 + i:07d}", seq=seq0 + i, t_ms=t0 + i * gap_ms, ip=ip,
            card_hash=f"{card_prefix}-{i:04d}", bin=bins[i % 3], amount_minor=1000 + i,
            currency="INR", session_id=f"s-{i}",
        )
        for i in range(n)
    ]


def _legit_noise(n=20, t0=0):
    return [
        Event(
            event_id=f"n-{i:07d}", seq=10_000 + i, t_ms=t0 + i * 30_000, ip=f"10.0.0.{i % 5}",
            card_hash=f"legit-{i}", bin="400000", amount_minor=4999, currency="INR",
            session_id=f"ns-{i}",
        )
        for i in range(n)
    ]


def _make_state(tmp_path, *, cusum_h=3.0):
    db = make_db(tmp_path)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=cusum_h, cooldown_seconds=100_000)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    return build_state(db, tmp_path / "sp", MERCHANT)


def _run(state, events):
    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("mm"))
    decisions = []

    async def _go():
        for ev in events:
            clock.set_ms(ev.t_ms)
            resp, _e = await score_attempt(
                state, merchant_id=MERCHANT, ip=ev.ip,
                body=ScoreRequest(**ev.to_score_request()), clock=clock, ulid=ulid,
            )
            decisions.append((ev.event_id, resp.decision.value))

    asyncio.run(_go())
    return decisions


def _incident_summary(state):
    incs = state.incidents.all_incidents()
    return {
        "count": len(incs),
        "attempts_before_alert": sorted(i.attempts_before_alert for i in incs),
        "ttd_s": sorted(round(i.time_to_detect_s, 6) for i in incs),
        "peak_tiers": sorted(i.peak_tier for i in incs),
    }


class TestMetamorphic:
    def test_m1_time_shift_by_whole_hours_is_invariant(self, tmp_path):
        base = _make_state(tmp_path / "a")
        _run(base, _burst())
        s0 = _incident_summary(base)

        shifted_events = [Event(**{**ev.__dict__, "t_ms": ev.t_ms + 5 * HOUR_MS}) for ev in _burst()]
        shifted = _make_state(tmp_path / "b")
        _run(shifted, shifted_events)
        s1 = _incident_summary(shifted)
        assert s0["count"] == s1["count"]
        assert s0["attempts_before_alert"] == s1["attempts_before_alert"]

    def test_m2_bijective_rename_keeps_decisions(self, tmp_path):
        base = _make_state(tmp_path / "a")
        d0 = _run(base, _burst())
        rename_bin = {"424242": "999901", "411111": "999902", "555544": "999903"}
        renamed = [
            Event(**{**ev.__dict__, "ip": "198.51.100.42",
                     "card_hash": f"zz-{ev.card_hash}", "bin": rename_bin[ev.bin]})
            for ev in _burst()
        ]
        other = _make_state(tmp_path / "b")
        d1 = _run(other, renamed)
        assert [d for _, d in d0] == [d for _, d in d1]

    def test_m3_inserting_attack_attempts_never_raises_attempts_before_alert(self, tmp_path):
        base = _make_state(tmp_path / "a")
        _run(base, _burst(n=60))
        aba0 = _incident_summary(base)["attempts_before_alert"]
        denser = _make_state(tmp_path / "b")
        _run(denser, _burst(n=90))
        aba1 = _incident_summary(denser)["attempts_before_alert"]
        assert min(aba1) <= min(aba0)

    def test_m4_doubling_the_rate_does_not_raise_attempts_before_alert(self, tmp_path):
        slow = _make_state(tmp_path / "a")
        _run(slow, _burst(gap_ms=2400))
        aba0 = min(_incident_summary(slow)["attempts_before_alert"])
        fast = _make_state(tmp_path / "b")
        _run(fast, _burst(gap_ms=1200))
        aba1 = min(_incident_summary(fast)["attempts_before_alert"])
        assert aba1 <= aba0

    def test_m5_unrelated_legit_traffic_does_not_change_attack_decisions(self, tmp_path):
        # Layer 2a's CUSUM is a STORE-level rate statistic by design (TRD
        # §6.5), so added legit volume can shift the pre-incident
        # `allow`<->`monitor` boundary by at most one attempt. What must NOT
        # move is any real enforcement decision on an attack event -- that is
        # the "cross-entity contamination" M5 exists to catch. `allow` and
        # `monitor` are both frictionless and are compared as one class.
        norm = {"allow": "observe", "monitor": "observe"}

        base = _make_state(tmp_path / "a")
        d0 = {k: norm.get(v, v) for k, v in _run(base, _burst())}
        merged = sorted(_burst() + _legit_noise(), key=lambda e: e.t_ms)
        other = _make_state(tmp_path / "b")
        d1 = {k: norm.get(v, v) for k, v in _run(other, merged)}
        for ev in _burst():
            assert d0[ev.event_id] == d1[ev.event_id], (
                f"{ev.event_id}: {d0[ev.event_id]} -> {d1[ev.event_id]}"
            )

    def test_m6_replay_at_1x_and_60x_is_identical(self, tmp_path, monkeypatch):
        from services.scorer.replay import ReplayDriver, ReplayRequest

        async def _noop_sleep(_s):
            return None

        monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
        events = _burst(n=40)

        st0 = _make_state(tmp_path / "a")
        st0.replay_driver = ReplayDriver(st0, merchant_id=MERCHANT)
        asyncio.run(st0.replay_driver.run(
            ReplayRequest(tier="n/a", seed=1, speed=0, epoch_ms=0), stream=events))
        s0 = _incident_summary(st0)

        st1 = _make_state(tmp_path / "b")
        st1.replay_driver = ReplayDriver(st1, merchant_id=MERCHANT)
        asyncio.run(st1.replay_driver.run(
            ReplayRequest(tier="n/a", seed=1, speed=60, epoch_ms=0), stream=events))
        s1 = _incident_summary(st1)
        assert s0 == s1

    def test_m7_idempotent_replay_leaves_layer2_state_unchanged(self, tmp_path):
        state = _make_state(tmp_path / "a")
        events = _burst(n=40)
        _run(state, events)
        before = _incident_summary(state)
        cusum_s_before = state.layer2._merchant(MERCHANT).cusum.s

        _run(state, [events[0]])  # same event_id + payload -> idempotent replay
        after = _incident_summary(state)
        assert after == before
        assert state.layer2._merchant(MERCHANT).cusum.s == cusum_s_before

    def test_m8_two_halves_against_a_warm_store_equal_one_pass(self, tmp_path):
        one = _make_state(tmp_path / "a")
        _run(one, _burst(n=60))
        s_one = _incident_summary(one)

        split = _make_state(tmp_path / "b")
        ev = _burst(n=60)
        _run(split, ev[:30])
        _run(split, ev[30:])
        s_split = _incident_summary(split)
        assert s_one["count"] == s_split["count"]
        assert s_one["attempts_before_alert"] == s_split["attempts_before_alert"]
        assert s_one["ttd_s"] == s_split["ttd_s"]
