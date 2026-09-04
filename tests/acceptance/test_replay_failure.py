"""
Source: remediation plan FIX-007 (AUDIT-007).

`ReplayDriver.run()` had no `try/except`, and `state.replay_task` was stored
(`routes_replay.py:54`) and never awaited or inspected. The strong reference
suppressed even asyncio's "Task exception was never retrieved" warning, so a
replay that crashed on attempt 1 was indistinguishable from one that was merely
slow: the counter froze, the status stayed `running` forever, and Launch stayed
disabled. There was no path by which the operator could learn anything had
happened.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import services.scorer.replay as replay_module
from services.scorer.replay import ReplayRequest
from tests.acceptance._replay_harness import auth, build_state, client_for

SMALL = {"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0, "hours": 1}


def _await_terminal(client, timeout_s: float = 60.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = client.get("/v1/replay/status").json()
        if last["terminal"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"never reached a terminal state; last: {last}")


@pytest.fixture
def replay(tmp_path):
    state = build_state(tmp_path)
    with client_for(state) as client:
        yield client, state
    state.spool.close()


class TestExceptionsSurface:
    def test_an_injected_exception_becomes_a_failed_run_with_a_reason(
        self, replay, monkeypatch
    ):
        client, state = replay

        async def _boom(*args, **kwargs):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(replay_module, "score_attempt", _boom)
        resp = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert resp.status_code == 202

        final = _await_terminal(client)
        assert final["state"] == "failed", (
            f"a crashed replay reported {final['state']!r} -- AUDIT-007: the "
            f"exception vanished and the counter simply froze"
        )
        assert "RuntimeError" in (final["error"] or "")
        assert "scoring exploded" in (final["error"] or "")
        assert final["terminal"] is True, "Launch would stay disabled forever"

    def test_the_task_exception_is_retrieved(self, replay, monkeypatch):
        """A never-retrieved task exception is the mechanism that hid this."""
        client, state = replay

        async def _boom(*args, **kwargs):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(replay_module, "score_attempt", _boom)
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        task = state.replay_task
        assert task is not None and task.done()
        # `run()` handles its own exception, so the task completes normally --
        # the point is that nothing is left un-retrieved.
        assert task.exception() is None

    def test_a_failed_run_publishes_a_control_frame(self, replay, monkeypatch):
        client, state = replay

        async def _boom(*args, **kwargs):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(replay_module, "score_attempt", _boom)
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        frames = [
            f for f in state.event_bus.recent()
            if f.get("type") == "replay_status" and f["replay"]["state"] == "failed"
        ]
        assert frames, "no control frame announced the failure"
        assert "RuntimeError" in (frames[-1]["replay"]["error"] or "")

    def test_reset_recovers_and_a_new_run_succeeds(self, replay, monkeypatch):
        client, _ = replay

        async def _boom(*args, **kwargs):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(replay_module, "score_attempt", _boom)
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert _await_terminal(client)["state"] == "failed"

        monkeypatch.undo()
        client.post("/v1/replay/reset", headers=auth())
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)
        assert final["state"] == "finished"
        assert final["error"] is None


class TestCancellation:
    def test_a_cancelled_run_reports_stopped_not_running(self, tmp_path):
        state = build_state(tmp_path)
        driver = state.replay_driver

        async def _go():
            request = ReplayRequest(tier="easy", seed=42, speed=60, epoch_ms=0, hours=1)
            driver.mark_starting(request)
            task = asyncio.create_task(driver.run(request))
            state.replay_task = task
            await asyncio.sleep(0.2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_go())
        assert driver.status.state == "stopped", (
            f"a cancelled run reported {driver.status.state!r}; nothing would "
            f"ever move it out of that state"
        )
        assert driver.status.stop_reason == "reset"
        state.spool.close()


class TestWatchdog:
    def test_a_stalled_loop_is_marked_failed(self, tmp_path, monkeypatch):
        """The watchdog catches await-starvation and hung I/O. It cannot catch a
        SYNCHRONOUS spin -- that is FIX-002's job, and the limitation is stated
        in the driver rather than papered over."""
        state = build_state(tmp_path)
        driver = state.replay_driver
        monkeypatch.setattr(replay_module, "WATCHDOG_UNPACED_MS", 200)
        monkeypatch.setattr(replay_module, "WATCHDOG_POLL_S", 0.05)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(30)

        monkeypatch.setattr(replay_module, "score_attempt", _hang)

        async def _go():
            request = ReplayRequest(tier="easy", seed=42, speed=0, epoch_ms=0, hours=1)
            driver.mark_starting(request)
            task = asyncio.create_task(driver.run(request))
            state.replay_task = task
            for _ in range(60):
                await asyncio.sleep(0.1)
                if driver.status.state == "failed":
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_go())
        assert driver.status.state == "failed", "the watchdog never fired on a stalled loop"
        assert driver.status.stop_reason == "watchdog"
        assert "no progress" in (driver.status.error or "")
        state.spool.close()

    def test_a_normal_run_is_never_marked_failed_by_the_watchdog(self, replay):
        """The threshold must not fire on a legitimate 60x inter-event sleep.
        The audit measured that maximum at 4.6 s; the paced threshold is 30 s."""
        client, _ = replay
        assert replay_module.WATCHDOG_PACED_MS >= 6 * 4_600, (
            "the paced watchdog threshold is under a 6x margin on the measured "
            "4.6 s maximum inter-event sleep at 60x"
        )
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)
        assert final["state"] == "finished"
        assert final["stop_reason"] is None
