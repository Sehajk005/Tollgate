"""
Source: remediation plan FIX-009 / §14 (AUDIT-021).

`POST /v1/replay/stop` and `POST /v1/replay/reset` accepted unauthenticated
calls and returned 200. Both are STATE-MUTATING and `reset` destroys live
detector state -- windows, the CUSUM, open incidents and the enforcement
ladder -- so anything that can reach the port could wipe the demo mid-run.
Day 2's docstring justified the gap with "the loop does not re-authenticate per
event", which is a true statement about a different question.

`GET /v1/replay/status` stays deliberately open, consistent with `/v1/stream`
(Decision 94): it discloses strictly less than the stream already does, and the
frontend's mount-time recovery poll must work unconditionally.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from tests.acceptance._replay_harness import auth, build_state, client_for

SMALL = {"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0, "hours": 1}
PACED = {**SMALL, "speed": 60}


@pytest.fixture
def replay(tmp_path):
    state = build_state(tmp_path)
    with client_for(state) as client:
        yield client, state
    state.spool.close()


class TestMutatingRoutesRequireAKey:
    @pytest.mark.parametrize("path", ["stop", "reset"])
    def test_no_key_is_401(self, replay, path):
        client, _ = replay
        resp = client.post(f"/v1/replay/{path}")
        assert resp.status_code == 401, (
            f"/v1/replay/{path} accepted an unauthenticated call "
            f"({resp.status_code}) -- it mutates state"
        )

    @pytest.mark.parametrize("path", ["stop", "reset"])
    def test_a_wrong_key_is_401(self, replay, path):
        client, _ = replay
        resp = client.post(f"/v1/replay/{path}", headers={"X-Tollgate-Key": "not-the-key"})
        assert resp.status_code == 401

    @pytest.mark.parametrize("path", ["stop", "reset"])
    def test_a_valid_key_is_accepted(self, replay, path):
        client, _ = replay
        resp = client.post(f"/v1/replay/{path}", headers=auth())
        assert resp.status_code == 200, resp.text

    def test_start_still_requires_a_key(self, replay):
        client, _ = replay
        assert client.post("/v1/replay/start", json=SMALL).status_code == 401


class TestARejectedCallChangesNothing:
    def test_an_unauthenticated_stop_does_not_stop_the_run(self, replay):
        client, _ = replay
        client.post("/v1/replay/start", headers=auth(), json=PACED)
        time.sleep(0.2)
        assert client.post("/v1/replay/stop").status_code == 401
        # The run must still be going: a 401 that stops the replay anyway would
        # be an authentication check in name only.
        assert client.get("/v1/replay/status").json()["state"] in ("starting", "running")
        client.post("/v1/replay/stop", headers=auth())

    def test_an_unauthenticated_reset_does_not_clear_state(self, replay):
        client, state = replay
        client.post("/v1/replay/start", headers=auth(), json=SMALL)
        deadline = time.time() + 60
        while time.time() < deadline and not client.get("/v1/replay/status").json()["terminal"]:
            time.sleep(0.05)
        before = sum(len(store) for store in state.window_store._all_stores())
        assert before > 0, "no window state was written -- the test proves nothing"
        assert client.post("/v1/replay/reset").status_code == 401
        after = sum(len(store) for store in state.window_store._all_stores())
        assert after == before, "a rejected reset cleared state anyway"


class TestStatusStaysOpen:
    def test_status_is_readable_without_a_key(self, replay):
        client, _ = replay
        resp = client.get("/v1/replay/status")
        assert resp.status_code == 200, (
            "status now requires a key -- the frontend's mount-time recovery "
            "poll would fail and a page refresh could not reconstruct"
        )
        assert resp.json()["state"] == "idle"


class TestAuthBackendUnavailable:
    def test_a_cold_cache_and_an_unavailable_db_is_503_not_a_bypass(self, tmp_path, monkeypatch):
        """Decision 89: auth never fails open. A locked merchant DB with a COLD
        key cache must be 503, never 200."""
        state = build_state(tmp_path)

        def _locked(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        with client_for(state) as client:
            monkeypatch.setattr(type(state), "db_read_conn", _locked, raising=False)
            state.api_key_cache.clear()
            for path in ("stop", "reset"):
                resp = client.post(f"/v1/replay/{path}", headers=auth())
                assert resp.status_code == 503, (
                    f"/v1/replay/{path} returned {resp.status_code} with an "
                    f"unavailable auth backend; it must be 503, never a bypass"
                )
        state.spool.close()
