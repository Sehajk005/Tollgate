"""
Source: remediation plan FIX-006 / §9 (AUDIT-001, 004, 005, 015).

Day 2's `reset()` mutated state with no reference to `state.replay_task`, so a
reset issued mid-run cleared the windows while the loop kept scoring into them
-- and the loop then overwrote `status` on its next iteration, so the UI showed
`idle` while the backend was still running. The correct order is

    cancel/stop -> AWAIT termination -> clear -> publish cleared -> idle

and the system must NEVER report idle while the previous replay is alive.
"""

from __future__ import annotations

import time

import pytest

from tests.acceptance._replay_harness import auth, build_state, client_for

SMALL = {"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0, "hours": 1}
PACED = {**SMALL, "speed": 60}


def _await_terminal(client, timeout_s: float = 60.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = client.get("/v1/replay/status").json()
        if last["terminal"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"replay never reached a terminal state; last: {last}")


@pytest.fixture
def replay(tmp_path):
    state = build_state(tmp_path)
    with client_for(state) as client:
        yield client, state
    state.spool.close()


class TestResetContract:
    def test_reset_while_idle_is_an_idempotent_200(self, replay):
        client, _ = replay
        resp = client.post("/v1/replay/reset", headers=auth())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "idle"
        assert body["degraded"] is False
        assert "cleared" in body

    def test_reset_reports_every_layer_it_cleared(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        body = client.post("/v1/replay/reset", headers=auth()).json()
        cleared = body["cleared"]
        # The per-layer map is what turns "reset failed" from an opaque 500 into
        # something an operator can act on.
        assert "window_store" in cleared
        assert "threat" in cleared
        assert "decision_cache" in cleared, (
            "the in-process decision cache is not cleared -- plan F-E: an attempt "
            "could then take idempotent_replay=True against zeroed features and "
            "fall through to full scoring on an empty vector"
        )
        assert body["degraded"] is False

    def test_reset_returns_200_and_degraded_when_one_layer_fails(self, tmp_path):
        """Redis unreachable must NOT produce a bare 500: the other five layers
        still clear, and the operator is told exactly which one did not."""
        class BrokenStore:
            def clear(self, merchant_id=None):
                raise RuntimeError("redis is unreachable")

            def score_path(self, request):  # pragma: no cover - not exercised
                raise AssertionError

            def record_and_read(self, request):  # pragma: no cover
                raise AssertionError

            def shed_incr(self, *a, **k):  # pragma: no cover
                raise AssertionError

        state = build_state(tmp_path, window_store=BrokenStore())
        with client_for(state) as client:
            resp = client.post("/v1/replay/reset", headers=auth())
            assert resp.status_code == 200, (
                f"a broken window store produced HTTP {resp.status_code} -- "
                f"AUDIT-001 was exactly this, a bare 500 from one failing layer"
            )
            body = resp.json()
            assert body["cleared"]["window_store"] is False
            assert body["degraded"] is True
            assert "RuntimeError" in body["cleared"]["window_store_error"]
            assert body["cleared"]["threat"] is not False, "the other layers must still clear"
            assert body["state"] == "idle"
        state.spool.close()


class TestResetWhileRunning:
    def test_reset_terminates_the_run_before_clearing_anything(self, replay):
        client, state = replay
        started = client.post("/v1/replay/start", headers=auth(), json=PACED)
        assert started.status_code == 202
        time.sleep(0.3)

        body = client.post("/v1/replay/reset", headers=auth()).json()
        assert body["state"] == "idle"
        # THE invariant. AUDIT-004's signature is a live task behind an idle
        # status; if the task is still running, the clear happened underneath it.
        assert state.replay_task is None or state.replay_task.done(), (
            "reset reported idle while the replay task was still alive"
        )

    def test_no_attempt_event_is_published_after_the_reset_frame(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json=PACED)
        time.sleep(0.3)
        client.post("/v1/replay/reset", headers=auth())
        time.sleep(0.3)

        frames = state.event_bus.recent()
        reset_positions = [
            i for i, f in enumerate(frames)
            if f.get("type") == "replay_status" and f.get("reset") is True
        ]
        assert reset_positions, "no reset control frame was published"
        after = frames[reset_positions[-1] + 1:]
        stragglers = [f for f in after if f.get("attempt_uid")]
        assert not stragglers, (
            f"{len(stragglers)} attempt event(s) were published AFTER the reset "
            f"frame -- the loop was still scoring into freshly-cleared state"
        )

    def test_a_run_after_a_mid_run_reset_is_complete(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=PACED)
        time.sleep(0.3)
        client.post("/v1/replay/reset", headers=auth())
        again = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert again.status_code == 202, again.text
        final = _await_terminal(client)
        assert final["state"] == "finished"
        assert final["sent"] == final["total"] > 0


class TestAutoClearOnLaunch:
    def test_launching_from_a_terminal_dirty_state_auto_clears(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        first = _await_terminal(client)
        assert first["state"] == "finished"

        resp = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["auto_reset"] is True, (
            "Launch from a finished run did not auto-clear -- the second run "
            "would reuse the first's windows and idempotency keys (AUDIT-005)"
        )
        assert body["cleared"]["window_store"] is not False
        second = _await_terminal(client)
        assert second["state"] == "finished"
        assert second["sent"] == first["sent"], (
            f"the second run emitted {second['sent']} events against the first's "
            f"{first['sent']} -- state leaked across the run boundary"
        )

    def test_launching_from_idle_does_not_report_an_auto_reset(self, replay):
        client, _ = replay
        body = client.post("/v1/replay/start", headers=auth(), json=SMALL).json()
        assert body["auto_reset"] is False
        _await_terminal(client)
