"""
Day 9 -- DEF-D9-008 regression guard (P3).

`POST /v1/replay/reset` closed every open `incident` row
(`ReplayDriver._close_open_incident_rows` -> `resolve_incident(..., "reset")`)
but never released their `enforcement_action` rows -- so after a run+reset cycle
the ledger kept rows with `released_at IS NULL` while `open_incidents = 0`. The
operator resolve route (`routes_incidents.py`) does both; reset did only half.

The live `PolicyEngine` ceiling *is* cleared by reset (it is in the `cleared`
map), so the demo is unaffected -- but `GET /v1/demo/cotenant-ip` and any audit
of the enforcement ledger see stale "still enforced" rows.

Fix: `_close_open_incident_rows` also calls
`release_enforcement_for_incident(conn, incident_id, now)` for each closed
incident, matching the operator path.
"""

from __future__ import annotations

from packages.storage.db import connect
from tests.acceptance._replay_harness import auth, build_state, client_for, MERCHANT_ID


def _seed_open_incident_with_active_enforcement(db_path) -> str:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO incident (incident_id, merchant_id, state, detector, opened_at, "
            "escalated_at, peak_tier, attempts_total, pinned_policy_version) "
            "VALUES ('I-DEF-D9-008', ?, 'ESCALATED', 'drift', 1000, 1000, 'challenge', 5, 1)",
            (MERCHANT_ID,),
        )
        conn.execute(
            "INSERT INTO enforcement_action (action_id, incident_id, merchant_id, entity_type, "
            "entity_key, tier, requires_confirmation, confirmed_by, applied_at, expires_at, "
            "released_at, applied_by) "
            "VALUES ('A-DEF-D9-008', 'I-DEF-D9-008', ?, 'ip', '198.51.100.7', 'challenge', 0, "
            "'auto', 1000, 9999999999999, NULL, 'auto')",
            (MERCHANT_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    return "I-DEF-D9-008"


def test_reset_releases_enforcement_rows_for_the_incidents_it_closes(tmp_path):
    state = build_state(tmp_path)
    try:
        incident_id = _seed_open_incident_with_active_enforcement(state.db_path)

        with client_for(state) as client:
            # sanity: the row is active before the reset
            conn = connect(state.db_path)
            try:
                active = conn.execute(
                    "SELECT COUNT(*) FROM enforcement_action "
                    "WHERE incident_id = ? AND released_at IS NULL",
                    (incident_id,),
                ).fetchone()[0]
            finally:
                conn.close()
            assert active == 1, "test setup: the enforcement row should start active"

            resp = client.post("/v1/replay/reset", headers=auth())
            assert resp.status_code == 200, resp.text
            assert resp.json()["cleared"]["persisted_incidents"] >= 1

            conn = connect(state.db_path)
            try:
                inc_state = conn.execute(
                    "SELECT state FROM incident WHERE incident_id = ?", (incident_id,)
                ).fetchone()[0]
                orphaned = conn.execute(
                    "SELECT COUNT(*) FROM enforcement_action "
                    "WHERE incident_id = ? AND released_at IS NULL",
                    (incident_id,),
                ).fetchone()[0]
            finally:
                conn.close()

        assert inc_state == "CLOSED", f"reset left the incident in {inc_state!r}, not CLOSED"
        assert orphaned == 0, (
            "DEF-D9-008: reset closed the incident but left "
            f"{orphaned} enforcement_action row(s) with released_at IS NULL"
        )
    finally:
        state.spool.close()
