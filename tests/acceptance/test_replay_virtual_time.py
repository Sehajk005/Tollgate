"""
Source: Day-2 Plan §I acceptance tests A13-A15 -- virtual-clock replay
fidelity. `services/scorer/replay.py` does not exist yet (Day-2 Step 7);
these tests fail with ImportError/ModuleNotFoundError until then.

A synthetic in-line stream (not the real simulator) is used so speed=1's
real wall-clock pacing stays well under a second of test time: 25 events on
one IP/card spanning ~2.4s of *virtual* time is enough to trip R1
(>=20/60s) without needing minutes of wall-clock sleeping.

A15's first half -- "clock-discipline AST scan extended to
packages/simulator + services/scorer/replay.py" -- needs no new test:
tests/acceptance/test_clock_discipline.py already scans all of
packages/services/scripts recursively (SCANNED_DIRS = ["packages",
"services", "scripts"]), so both new module trees are covered by the
existing Day-1 test without editing it (Step 6's "no edits to any Day-1
test" constraint applies to Day-2 too). This file covers A15's second half:
the replay driver's own clock is a VirtualClock instance.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from packages.clock.clock import SystemClock, VirtualClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
MERCHANT_ID = "m_replay_test"


@dataclass(frozen=True)
class SyntheticEvent:
    """Minimal duck-typed stand-in for packages.simulator.stream.Event."""

    event_id: str
    t_ms: int
    ip: str
    card_hash: str = "card-const"
    bin: str = "411111"
    amount_minor: int = 100
    currency: str = "INR"
    session_id: str = "s-const"

    def to_score_request(self) -> dict:
        return {
            "event_id": self.event_id, "card_hash": self.card_hash, "bin": self.bin,
            "amount_minor": self.amount_minor, "currency": self.currency,
            "session_id": self.session_id,
        }


def _synthetic_stream(n: int = 25, spacing_ms: int = 100, ip: str = "203.0.113.5") -> list:
    return [SyntheticEvent(event_id=f"e-{i:04d}", t_ms=i * spacing_ms, ip=ip) for i in range(n)]


def _build_state(tmp_path: Path) -> ScorerState:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    clock = SystemClock()
    ulid = UlidGenerator(clock=clock)
    window_store = InMemoryWindowStore()
    rules = DayOneRules(window_store)
    spool = Spool(spool_dir)
    drainer = Drainer(db_path=db_path, spool_path=spool.path)
    bus = InProcessEventBus()
    return ScorerState(
        clock=clock, ulid=ulid, window_store=window_store, rules=rules,
        spool=spool, drainer=drainer, event_bus=bus, db_path=db_path,
    )


async def _run_and_collect(state: ScorerState, request, stream):
    """Collects the ATTEMPT events published during a run.

    Remediation plan FIX-008 added lifecycle control frames
    (`{"type": "replay_status", ...}`) to the same bus, so "everything the bus
    published" is no longer the same set as "one event per scored attempt". The
    frames are separated here rather than counted: every assertion in this file
    is about attempt events and is unchanged, and `control_frames` is returned
    so the separation itself can be asserted instead of assumed. Control frames
    carry no `attempt_uid`, which is exactly why `bus.recent()`'s cursor logic
    ignores them too (plan F-G).
    """
    from services.scorer.replay import ReplayDriver  # noqa: PLC0415 -- module under test

    events = []
    control_frames = []

    async def _collect():
        async for event in state.event_bus.subscribe():
            if event.get("type") == "replay_status":
                control_frames.append(event)
            else:
                events.append(event)

    collector = asyncio.create_task(_collect())
    await asyncio.sleep(0)  # let the subscriber register before publishing starts

    driver = ReplayDriver(state, merchant_id=MERCHANT_ID)
    status = await driver.run(request, stream=stream)

    # speed=0 publishes on an unbounded asyncio.Queue, which never suspends
    # the publisher -- the whole run() call can complete without ever
    # yielding to the event loop, so the collector task (blocked on
    # queue.get()) hasn't had a turn to drain what was already published.
    # One scheduling opportunity is enough: once resumed, it drains every
    # queued item synchronously (queue.get() on a non-empty queue doesn't
    # suspend either) and re-blocks only once the queue is actually empty.
    await asyncio.sleep(0)

    collector.cancel()
    try:
        await collector
    except asyncio.CancelledError:
        pass
    _run_and_collect.last_control_frames = control_frames
    return driver, status, events


class TestA13SpeedInvarianceOfDecisions:
    # Source: Day-2 Plan §I A13 (metamorphic M6) -- "this single test is
    # what makes the demo's compression claim true".
    def test_speed_zero_and_speed_sixty_produce_identical_sequences(self, tmp_path):
        from services.scorer.replay import ReplayRequest  # noqa: PLC0415

        stream = _synthetic_stream()

        state0 = _build_state(tmp_path / "s0")
        _, _, events0 = asyncio.run(
            _run_and_collect(state0, ReplayRequest(tier="easy", seed=42, speed=0, epoch_ms=0), stream)
        )
        state0.spool.close()

        state60 = _build_state(tmp_path / "s60")
        _, _, events60 = asyncio.run(
            _run_and_collect(state60, ReplayRequest(tier="easy", seed=42, speed=60, epoch_ms=0), stream)
        )
        state60.spool.close()

        def _key(e: dict) -> tuple:
            return (
                e.get("attempt_uid"), e.get("decision"), tuple(e.get("rules_fired") or ()),
                tuple(sorted((e.get("feature_snapshot") or {}).items())), e.get("ingest_time"),
            )

        assert events0, "speed=0 replay produced no events"
        assert [_key(e) for e in events0] == [_key(e) for e in events60], (
            "replay decisions/rules/features/ingest_time diverged between speed=0 and speed=60 "
            "-- a wall-clock leak has entered the windowing path"
        )

    @pytest.mark.slow
    def test_speed_one_takes_measurably_longer_wall_time_than_speed_zero(self, tmp_path):
        # Source: Day-2 Plan §J test-gaming review -- "pass A13 by making
        # both speeds sleep zero" is stopped by asserting a real wall-clock
        # margin, not just sequence equality.
        from services.scorer.replay import ReplayRequest  # noqa: PLC0415

        stream = _synthetic_stream(n=10, spacing_ms=200)  # ~1.8s of virtual span

        state0 = _build_state(tmp_path / "fast")
        start = time.perf_counter()
        asyncio.run(_run_and_collect(state0, ReplayRequest(tier="easy", seed=42, speed=0, epoch_ms=0), stream))
        elapsed_speed0 = time.perf_counter() - start
        state0.spool.close()

        state1 = _build_state(tmp_path / "slow")
        start = time.perf_counter()
        asyncio.run(_run_and_collect(state1, ReplayRequest(tier="easy", seed=42, speed=1, epoch_ms=0), stream))
        elapsed_speed1 = time.perf_counter() - start
        state1.spool.close()

        assert elapsed_speed1 > elapsed_speed0 + 0.5, (
            f"speed=1 ({elapsed_speed1:.2f}s) did not take measurably longer than "
            f"speed=0 ({elapsed_speed0:.2f}s) -- wall pacing may not be implemented"
        )


class TestA14VirtualTimeEqualsEventTime:
    # Source: Day-2 Plan §I A14 -- TRD v2 §4.2-4.3, forced identity:
    # ingest_time - t0 == event.t_ms. The driver scores the stream strictly
    # sequentially (services/scorer/replay.py §G loop) and InProcessEventBus
    # delivers to one subscriber in publish order (packages/storage/bus.py),
    # so positional correlation between the input stream and the collected
    # events is valid without needing event_id echoed on the wire.
    def test_ingest_time_minus_epoch_equals_event_t_ms(self, tmp_path):
        from services.scorer.replay import ReplayRequest  # noqa: PLC0415

        stream = _synthetic_stream()
        epoch_ms = 0
        state = _build_state(tmp_path)
        _, _, events = asyncio.run(
            _run_and_collect(state, ReplayRequest(tier="easy", seed=42, speed=0, epoch_ms=epoch_ms), stream)
        )
        state.spool.close()

        assert len(events) == len(stream), (
            f"expected one published event per stream event, got {len(events)} for {len(stream)} inputs"
        )
        # Remediation plan FIX-008 / AUDIT-002: the lifecycle must also announce
        # itself, and a terminal transition must be one of the announcements --
        # its absence is exactly why a finished run rendered forever as RUNNING.
        frames = _run_and_collect.last_control_frames
        assert frames, "no replay_status control frame was published during the run"
        assert all("attempt_uid" not in f for f in frames), (
            "a control frame carried an attempt_uid, which would corrupt "
            "bus.recent()'s cursor (plan F-G)"
        )
        assert frames[-1]["replay"]["state"] == "finished", (
            f"the terminal transition published {frames[-1]['replay']['state']!r}, not 'finished'"
        )
        assert frames[-1]["replay"]["sent"] == len(stream), (
            "the terminal frame does not carry the final count -- AUDIT-002's signature"
        )
        for source_event, published in zip(stream, events):
            assert published["ingest_time"] - epoch_ms == source_event.t_ms, (
                f"{source_event.event_id}: ingest_time={published['ingest_time']} epoch_ms={epoch_ms} "
                f"t_ms={source_event.t_ms} -- ingest_time - epoch_ms != t_ms"
            )


class TestA15ReplayDriverClockIsVirtual:
    # Source: Day-2 Plan §I A15, second half -- "the driver's clock is a
    # VirtualClock during replay". The AST-scan half is already covered by
    # the existing tests/acceptance/test_clock_discipline.py (see module
    # docstring).
    def test_driver_clock_is_a_virtual_clock_instance(self, tmp_path):
        from services.scorer.replay import ReplayDriver  # noqa: PLC0415

        state = _build_state(tmp_path)
        driver = ReplayDriver(state, merchant_id=MERCHANT_ID)
        assert isinstance(driver.clock, VirtualClock), (
            f"replay driver clock is {type(driver.clock).__name__}, expected VirtualClock"
        )
        state.spool.close()

    def test_storefront_clock_is_unaffected_by_replay(self, tmp_path):
        # Source: Day-2 Plan §E "Coexistence with live storefront traffic" --
        # score_attempt defaults to state.clock, which must remain
        # SystemClock even while a replay driver holds its own VirtualClock.
        state = _build_state(tmp_path)
        assert isinstance(state.clock, SystemClock)
        from services.scorer.replay import ReplayDriver  # noqa: PLC0415

        ReplayDriver(state, merchant_id=MERCHANT_ID)
        assert isinstance(state.clock, SystemClock), "constructing a replay driver must not mutate state.clock"
        state.spool.close()
