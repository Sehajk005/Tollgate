"""
Day 9 -- DEF-D9-006 regression guard (P3).

`GET /v1/incidents` declared and documented a `?state=` filter that was never
applied: `list_incidents(state="live", ...)` dropped `state` on the floor and
`read_open_incidents(conn, merchant_id)` hard-coded `WHERE state != 'CLOSED'`,
so `?state=live`, `?state=closed` and `?state=bogus` all returned the identical
list.

Fix: honour it. `state in {live, closed, all}` (validated at the boundary ->
422 otherwise); `read_open_incidents` takes `state` and branches the WHERE.
"""

from __future__ import annotations

from packages.storage.db import connect
from tests.acceptance._replay_harness import auth, build_state, client_for, MERCHANT_ID


def _seed(db_path) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO incident (incident_id, merchant_id, state, detector, opened_at, "
            "peak_tier, pinned_policy_version) VALUES "
            "('I-OPEN', ?, 'ESCALATED', 'drift', 2000, 'challenge', 1)",
            (MERCHANT_ID,),
        )
        conn.execute(
            "INSERT INTO incident (incident_id, merchant_id, state, detector, opened_at, "
            "closed_at, peak_tier, pinned_policy_version) VALUES "
            "('I-CLOSED', ?, 'CLOSED', 'drift', 1000, 1500, 'challenge', 1)",
            (MERCHANT_ID,),
        )
        conn.commit()
    finally:
        conn.close()


def _ids(resp) -> set:
    return {r["incident_id"] for r in resp.json()["incidents"]}


def test_state_filter_is_honoured(tmp_path):
    state = build_state(tmp_path)
    try:
        _seed(state.db_path)
        with client_for(state) as client:
            assert client.get("/v1/incidents", headers=auth()).status_code == 200
            assert _ids(client.get("/v1/incidents", headers=auth())) == {"I-OPEN"}
            assert _ids(client.get("/v1/incidents?state=live", headers=auth())) == {"I-OPEN"}
            assert _ids(client.get("/v1/incidents?state=closed", headers=auth())) == {"I-CLOSED"}
            assert _ids(client.get("/v1/incidents?state=all", headers=auth())) == {"I-OPEN", "I-CLOSED"}

            bogus = client.get("/v1/incidents?state=bogus", headers=auth())
            assert bogus.status_code == 422, (
                f"an out-of-set state returned {bogus.status_code}, not a 422 -- "
                "DEF-D9-006 wants the param honoured or rejected, never silently ignored"
            )
    finally:
        state.spool.close()
