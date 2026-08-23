"""
Source: Implementation Plan v2.1 Day 1 acceptance test 13 -- /v1/score
API-key auth, validation, scoring, persistence.
"""

from __future__ import annotations

from packages.contracts.decision import Decision
from packages.storage.db import connect

VALID_BODY = {
    "event_id": "evt-1", "card_hash": "card-1", "bin": "411111",
    "amount_minor": 100, "currency": "INR",
}


def test_missing_api_key_is_rejected(client):
    resp = client.post("/v1/score", json=VALID_BODY)
    assert resp.status_code == 401


def test_invalid_api_key_is_rejected(client):
    resp = client.post(
        "/v1/score", json=VALID_BODY, headers={"X-Tollgate-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_valid_request_reaches_scorer_and_returns_decision(client):
    resp = client.post(
        "/v1/score", json=VALID_BODY,
        headers={"X-Tollgate-Key": client.tollgate_api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] in {d.value for d in Decision}
    assert "attempt_uid" in body
    assert "latency_ms" in body


def test_missing_required_field_is_rejected(client):
    bad_body = dict(VALID_BODY)
    del bad_body["card_hash"]
    resp = client.post(
        "/v1/score", json=bad_body, headers={"X-Tollgate-Key": client.tollgate_api_key},
    )
    assert resp.status_code == 422


def test_body_supplied_ip_is_ignored(client, scorer_state):
    body_with_ip = dict(VALID_BODY, ip="203.0.113.9")
    resp = client.post(
        "/v1/score", json=body_with_ip, headers={"X-Tollgate-Key": client.tollgate_api_key},
    )
    assert resp.status_code == 200
    attempt_uid = resp.json()["attempt_uid"]
    scorer_state.drainer.drain_once()
    conn = connect(scorer_state.db_path)
    try:
        row = conn.execute(
            "SELECT ip FROM auth_attempt WHERE attempt_uid = ?", (attempt_uid,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    # The stored ip must be the real TestClient peer address, never the
    # attacker-suppliable body value (Threat Model v2 section 2 / finding K8).
    assert row["ip"] != "203.0.113.9"


def test_three_hard_rules_produce_meaningfully_non_allow_decision(client):
    # Fire R1 by sending 20 attempts from the same IP within the window.
    # card_hash is held CONSTANT so R2 (distinct cards per IP) does not fire
    # first -- this isolates R1's attempt-volume signal specifically.
    key = client.tollgate_api_key
    last_body = None
    for i in range(20):
        resp = client.post(
            "/v1/score",
            json={
                "event_id": f"evt-r1-{i}", "card_hash": "card-r1-constant",
                "bin": "411111", "amount_minor": 100, "currency": "INR",
            },
            headers={"X-Tollgate-Key": key},
        )
        last_body = resp.json()
    assert last_body["decision"] == Decision.THROTTLE.value
