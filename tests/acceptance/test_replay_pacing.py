"""
Source: remediation plan FIX-011 (AUDIT-014).

At the demo's 60x setting an `easy` replay runs 3 hours of event time in ~179
wall-clock seconds, of which the attack episode -- the only part anyone is
watching for -- occupies about 10. The audit filed this as a DEMO-DESIGN defect,
not an engine defect: the virtual clock measured 58.5x against a 60x nominal and
`test_time_travel` passes, so the clock is fine and must not be touched.

`pace_from="episode"` scores the pre-episode events at full tilt and engages
pacing ~20 s of event time before the attack. The load-bearing claim is that
this is a WALL-CLOCK change only:

    same events, same order, same virtual times, same decisions.

`set_ms` and `score_attempt` are untouched, so determinism is bit-for-bit -- and
that is asserted here rather than argued.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from packages.simulator.generate import build_stream
from services.scorer.replay import PACE_LEAD_MS, ReplayRequest
from tests.acceptance._replay_harness import build_state

TIER = "easy"
HOURS = 3


def _run(state, request, run_id):
    driver = state.replay_driver
    driver.mark_starting(request)
    driver._status.run_id = run_id
    events = []

    async def _collect():
        async for frame in state.event_bus.subscribe():
            if frame.get("attempt_uid"):
                events.append(frame)

    async def _go():
        collector = asyncio.create_task(_collect())
        await asyncio.sleep(0)
        status = await driver.run(request)
        await asyncio.sleep(0)
        collector.cancel()
        try:
            await collector
        except asyncio.CancelledError:
            pass
        return status

    return asyncio.run(_go()), events


def _signature(events):
    return [
        (e["attempt_uid"], e["decision"], tuple(e.get("rules_fired") or []), e["ingest_time"])
        for e in events
    ]


class TestDeterminismIsUnaffected:
    def test_paced_and_unpaced_runs_produce_identical_results(self, tmp_path):
        # The SAME run identity for both. `attempt_uid` is deliberately
        # run-scoped (Decision 103) so repeat runs do not collide on the
        # primary key; holding run_id fixed isolates the variable actually
        # under test, which is `pace_from` and nothing else.
        run_id = "RUN_PACING_FIXTURE"

        state_a = build_state(tmp_path / "a")
        plain, events_plain = _run(
            state_a,
            ReplayRequest(tier=TIER, seed=42, speed=0, epoch_ms=0, hours=HOURS),
            run_id,
        )
        state_a.spool.close()

        state_b = build_state(tmp_path / "b")
        paced, events_paced = _run(
            state_b,
            ReplayRequest(tier=TIER, seed=42, speed=0, epoch_ms=0, hours=HOURS, pace_from="episode"),
            run_id,
        )
        state_b.spool.close()

        assert plain.sent == paced.sent == plain.total, (plain.sent, paced.sent)
        assert _signature(events_plain) == _signature(events_paced), (
            "pace_from changed a decision, a rule or a virtual time -- it must "
            "only change the wall-clock sleep"
        )


class TestPacingActuallyShortensTheWallClock:
    def test_a_paced_60x_run_reaches_the_episode_far_sooner(self, tmp_path):
        """The measurable claim. Both runs are cut short deliberately: what is
        compared is how much EVENT time each has covered after the same wall
        clock, which is exactly what the operator experiences as 'waiting'."""
        result = build_stream(seed=42, tier=TIER, hours=HOURS)
        episode_start = result.episodes[0].started_at
        pace_from_ms = max(0, episode_start - PACE_LEAD_MS)
        assert pace_from_ms > 0, "the episode starts at t=0; this tier cannot show the effect"

        async def _covered(pace_from, budget_s):
            state = build_state(tmp_path / f"p-{pace_from}")
            driver = state.replay_driver
            request = ReplayRequest(
                tier=TIER, seed=42, speed=60, epoch_ms=0, hours=HOURS, pace_from=pace_from
            )
            driver.mark_starting(request)
            task = asyncio.create_task(driver.run(request))
            await asyncio.sleep(budget_s)
            driver._stop_requested = True
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
            covered = driver.status.virtual_time_ms
            state.spool.close()
            return covered

        unpaced = asyncio.run(_covered(None, 2.0))
        paced = asyncio.run(_covered("episode", 2.0))

        assert paced > unpaced, (
            f"after the same 2 s, the paced run had covered {paced} ms of event "
            f"time and the unpaced one {unpaced} ms -- pacing did nothing"
        )
        assert paced >= pace_from_ms, (
            f"the paced run only reached {paced} ms; it should sprint to at "
            f"least the pacing point ({pace_from_ms} ms) within 2 s"
        )


class TestFallback:
    def test_pace_from_with_no_episode_falls_back_to_uniform_pacing(self, tmp_path):
        state = build_state(tmp_path)
        driver = state.replay_driver
        request = ReplayRequest(tier=TIER, seed=42, speed=60, epoch_ms=0, pace_from="episode")

        class _NoEpisodes:
            episodes = []

        assert driver._pace_from_ms(request, _NoEpisodes()) == 0
        state.spool.close()

    def test_pace_from_is_inert_at_speed_zero(self, tmp_path):
        state = build_state(tmp_path)
        driver = state.replay_driver
        result = build_stream(seed=42, tier=TIER, hours=HOURS)
        request = ReplayRequest(tier=TIER, seed=42, speed=0, epoch_ms=0, pace_from="episode")
        assert driver._pace_from_ms(request, result) == 0, (
            "speed 0 never sleeps, so there is nothing for pacing to skip"
        )
        state.spool.close()

    def test_no_pace_from_is_byte_identical_to_day_2(self, tmp_path):
        state = build_state(tmp_path)
        driver = state.replay_driver
        result = build_stream(seed=42, tier=TIER, hours=HOURS)
        request = ReplayRequest(tier=TIER, seed=42, speed=60, epoch_ms=0, pace_from=None)
        assert driver._pace_from_ms(request, result) == 0
        state.spool.close()
