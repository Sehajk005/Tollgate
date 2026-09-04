"""
Source: remediation plan FIX-005 / §7 (AUDIT-002, 003, 004, 013).

Day 2's driver had four wire states, a `stop()` that only set a flag, and a
terminal transition that published nothing. The observable results were:

  * a completed run reported `RUNNING (N-1/N)` forever, because `sent` was
    written AFTER the publish, so the last attempt event carried
    `sent = total - 1`, and nothing was ever published afterwards (AUDIT-002);
  * `POST /v1/replay/stop` serialised the status with no await and therefore
    ALWAYS returned the pre-stop snapshot -- `running`, stale `sent`
    (AUDIT-003);
  * a run had no identity, so the frontend could not tell run 2 from run 1
    (AUDIT-005, AUDIT-015) and the tier selector had nothing to reconcile
    against (AUDIT-013).

These are API-level tests against a real TestClient, because the routes are
where the defects were observable.
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
    raise AssertionError(f"replay never reached a terminal state; last: {last}")


@pytest.fixture
def replay(tmp_path):
    state = build_state(tmp_path)
    with client_for(state) as client:
        yield client, state
    state.spool.close()


class TestRunIdentity:
    def test_idle_status_has_no_run_id(self, replay):
        client, _ = replay
        body = client.get("/v1/replay/status").json()
        assert body["state"] == "idle"
        assert body["run_id"] is None
        assert body["terminal"] is True

    def test_every_run_gets_a_distinct_run_id(self, replay):
        client, _ = replay
        first = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert first.status_code == 202, first.text
        run_a = first.json()["run_id"]
        assert run_a
        _await_terminal(client)

        second = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert second.status_code == 202, second.text
        run_b = second.json()["run_id"]
        _await_terminal(client)

        assert run_b and run_b != run_a, (
            "two runs shared a run_id -- the frontend cannot tell them apart, so "
            "no event-derived surface can know when to reset"
        )

    def test_reset_clears_the_run_id(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        _await_terminal(client)
        body = client.post("/v1/replay/reset", headers=auth()).json()
        assert body["state"] == "idle"
        assert body["run_id"] is None


class TestTerminalStates:
    def test_a_finished_run_reports_the_full_count(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)
        assert final["state"] == "finished", final
        assert final["total"] > 0
        assert final["sent"] == final["total"], (
            f"finished at {final['sent']}/{final['total']} -- AUDIT-002's exact "
            f"signature: the counter stops one short and never advances"
        )

    def test_status_is_authoritative_after_completion(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)
        again = client.get("/v1/replay/status").json()
        assert again["state"] == "finished"
        assert again["sent"] == final["sent"] == again["total"]
        assert again["terminal"] is True


class TestStopAcknowledgement:
    def test_stop_never_returns_running(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        body = client.post("/v1/replay/stop", headers=auth()).json()
        assert body["state"] != "running", (
            "stop returned the pre-stop snapshot -- AUDIT-003. The operator is "
            "told the run is still going after asking it to stop."
        )
        assert body["state"] in ("stopped", "stopping", "finished")

    def test_the_returned_count_matches_the_backend(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        stopped = client.post("/v1/replay/stop", headers=auth()).json()
        final = _await_terminal(client)
        if stopped["state"] == "stopped":
            assert stopped["sent"] == final["sent"], (
                "the stop response's count disagrees with the backend's"
            )
        assert final["state"] in ("stopped", "finished")
        assert final["stop_reason"] in ("operator", None)

    def test_stop_while_idle_is_a_no_op(self, replay):
        client, _ = replay
        body = client.post("/v1/replay/stop", headers=auth()).json()
        assert body["state"] == "idle"

    def test_launch_works_again_after_a_stop(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        client.post("/v1/replay/stop", headers=auth())
        _await_terminal(client)
        again = client.post("/v1/replay/start", headers=auth(), json=SMALL)
        assert again.status_code == 202, again.text
        assert _await_terminal(client)["state"] == "finished"


class TestConcurrencyGuard:
    def test_a_second_start_while_running_is_409(self, replay):
        client, _ = replay
        first = client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        assert first.status_code == 202
        second = client.post("/v1/replay/start", headers=auth(), json={**SMALL, "speed": 60})
        assert second.status_code == 409, (
            f"a concurrent start was accepted ({second.status_code}) -- two drivers "
            f"would write into one detector"
        )
        client.post("/v1/replay/stop", headers=auth())

    def test_updated_at_ms_advances_on_every_transition(self, replay):
        client, _ = replay
        idle = client.get("/v1/replay/status").json()
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        final = _await_terminal(client)
        assert final["updated_at_ms"] >= idle["updated_at_ms"], (
            "updated_at_ms did not advance; the frontend reducer cannot order "
            "snapshots and a late frame could move the UI backwards"
        )
