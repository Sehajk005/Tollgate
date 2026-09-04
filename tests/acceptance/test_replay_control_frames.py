"""
Source: remediation plan FIX-008 (AUDIT-002, AUDIT-020).

Two defects, one mechanism -- nothing was ever written to the stream except
attempt events:

  * the terminal replay transition published NOTHING, so the last thing the
    dashboard ever heard about a run was an attempt event carrying
    `sent = total - 1`. A completed run rendered as `RUNNING (820/821)` for as
    long as the tab stayed open (AUDIT-002).
  * `_event_stream` yielded nothing until an event existed, so on an idle
    system the browser's `EventSource.onopen` never fired and the connection
    chip read `reconnecting` while everything was healthy (AUDIT-020).

Plan F-G is what makes adding frames safe: `bus.recent()` matches its cursor on
`attempt_uid`, and a control frame has none, so the existing cursor contract is
untouched.
"""

from __future__ import annotations

import time

import pytest

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
    raise AssertionError(f"never terminal; last: {last}")


@pytest.fixture
def replay(tmp_path):
    state = build_state(tmp_path)
    with client_for(state) as client:
        yield client, state
    state.spool.close()


def _frames(state):
    return [f for f in state.event_bus.recent() if f.get("type") == "replay_status"]


class TestTerminalFrames:
    def test_a_finished_run_publishes_a_terminal_frame_with_the_full_count(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)

        terminal = [f for f in _frames(state) if f["replay"]["state"] == "finished"]
        assert terminal, (
            "no frame announced completion -- the dashboard's last word on the "
            "run is an attempt event carrying sent = total - 1 (AUDIT-002)"
        )
        assert terminal[-1]["replay"]["sent"] == final["total"]

    def test_a_stopped_run_publishes_a_terminal_frame(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        client.post("/v1/replay/stop", headers=auth())
        _await_terminal(client)
        states = [f["replay"]["state"] for f in _frames(state)]
        assert "stopped" in states or "finished" in states, states

    def test_reset_publishes_a_frame_flagged_as_a_reset(self, replay):
        client, state = replay
        client.post("/v1/replay/reset", headers=auth())
        resets = [f for f in _frames(state) if f.get("reset") is True]
        assert resets, "reset published no frame, so no surface knows to clear"
        assert resets[-1]["replay"]["state"] == "idle"
        assert resets[-1]["replay"]["run_id"] is None


class TestCursorContractIsUnchanged:
    def test_control_frames_carry_no_attempt_uid(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        for frame in _frames(state):
            assert "attempt_uid" not in frame, (
                "a control frame carries an attempt_uid, which would corrupt "
                "bus.recent()'s cursor logic (plan F-G)"
            )

    def test_recent_after_a_real_uid_still_slices_correctly(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        attempts = [f for f in state.event_bus.recent() if f.get("attempt_uid")]
        assert len(attempts) >= 3
        cursor = attempts[-3]["attempt_uid"]
        after = state.event_bus.recent(cursor)
        after_attempts = [f for f in after if f.get("attempt_uid")]
        assert len(after_attempts) == 2, (
            f"cursor slicing returned {len(after_attempts)} attempts, expected 2"
        )


class TestHeadersFlushOnSubscribe:
    def test_the_stream_emits_a_comment_before_any_event_exists(self, replay):
        """AUDIT-020: on an idle system the first bytes must still arrive, or
        `onopen` never fires and the chip lies about the connection."""
        client, _ = replay
        with client.stream("GET", "/v1/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            first = next(resp.iter_lines())
            assert first.startswith(":"), (
                f"the first line was {first!r}, not an SSE comment -- the "
                f"response headers do not flush until an event happens"
            )

    def test_the_stream_sets_no_transform_and_no_buffering_headers(self, replay):
        client, _ = replay
        with client.stream("GET", "/v1/stream") as resp:
            assert "no-transform" in resp.headers.get("cache-control", "")
            assert resp.headers.get("x-accel-buffering") == "no"
