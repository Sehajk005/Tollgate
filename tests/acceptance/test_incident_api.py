"""
Source: Day-8 Plan Step 6 -- the D3 backend (read model, confirm, resolve).

  (a) GET /v1/incidents/{id} returns proposed_tier != in_force_tier for a
      step_up/block incident, with a `requires_confirmation = 1` enforcement row
      that carries confirmed_by IS NULL AND applied_at IS NULL.
  (b) after POST /confirm, that row has confirmed_by/applied_at set AND the next
      scored attempt from that entity returns the confirmed tier.
  (c) POST /resolve closes the incident, releases enforcement, and the next
      attempt from that entity is back under the `challenge` ceiling.
  (d) the read model contains no full card hash and no raw PAN-like value.

The state is shared between the direct `score_attempt` path and the HTTP
endpoints (one ScorerState, one PolicyEngine) -- confirmation mutates the
LIVE engine, which is why it affects subsequent attempts. Lifespan is skipped
so the background drainer does not race the test's explicit drains.
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from packages.storage.db import connect
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-d3"
RAW_KEY = "d3-key"
ATTACK_IP = "203.0.113.7"

_PAN_RE = re.compile(r"\b\d{13,19}\b")
_CARD_HASH_RE = re.compile(r"\b[0-9a-f]{32,}\b")


def _burst(n=48):
    return [
        {"t_ms": i * 1500, "ip": ATTACK_IP, "card_hash": f"c-{i:03d}", "bin": "424242"}
        for i in range(n)
    ]


def _setup(tmp_path):
    db = make_db(tmp_path)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=300)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    conn = connect(db)
    try:
        conn.execute(
            "UPDATE merchant SET api_key_hash = ? WHERE merchant_id = ?",
            (hash_api_key(RAW_KEY), MERCHANT),
        )
        conn.commit()
    finally:
        conn.close()
    state = build_state(db, tmp_path / "sp", MERCHANT)
    app = create_app(state=state)
    app.state.scorer = state  # lifespan would do this; we skip it (no bg drainer)
    client = TestClient(app)
    return db, state, client


def _drain(state):
    state.drainer.drain_from_start()


def _incident_id(db):
    conn = connect(db)
    try:
        row = conn.execute("SELECT incident_id FROM incident LIMIT 1").fetchone()
    finally:
        conn.close()
    return row["incident_id"] if row else None


def _next_attempt_decision(state, ip, t_ms, card):
    events = [{"t_ms": t_ms, "ip": ip, "card_hash": card, "bin": "424242"}]
    sse = score_stream(state, MERCHANT, events)
    return sse[-1]["decision"]


class TestIncidentApi:
    def test_read_model_shows_proposed_vs_in_force_and_a_pending_enforcement_row(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)

        iid = _incident_id(db)
        assert iid, "the burst did not open an incident"

        r = client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": RAW_KEY})
        assert r.status_code == 200
        d = r.json()
        assert d["incident"]["proposed_tier"] in ("step_up", "block")
        assert d["incident"]["in_force_tier"] in ("throttle", "challenge")
        assert d["incident"]["proposed_tier"] != d["incident"]["in_force_tier"]

        pending = [a for a in d["enforcement"] if a["tier"] in ("step_up", "block")]
        assert pending, "no proposed step_up/block enforcement row"
        for a in pending:
            assert a["requires_confirmation"] == 1
            assert a["confirmed_by"] is None
            assert a["applied_at"] is None

    def test_confirm_sets_the_row_and_the_next_attempt_returns_the_confirmed_tier(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)
        iid = _incident_id(db)

        d = client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": RAW_KEY}).json()
        action = next(a for a in d["enforcement"] if a["tier"] in ("step_up", "block"))
        tier = action["tier"]

        c = client.post(
            f"/v1/incidents/{iid}/confirm",
            headers={"X-Tollgate-Key": RAW_KEY},
            json={"action_id": action["action_id"], "tier": tier},
        )
        assert c.status_code == 200, c.text

        conn = connect(db)
        try:
            row = conn.execute(
                "SELECT requires_confirmation, confirmed_by, applied_at FROM enforcement_action "
                "WHERE action_id = ?",
                (action["action_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row["requires_confirmation"] == 0
        assert row["confirmed_by"] == "operator"
        assert row["applied_at"] is not None

        # the next scored attempt from that entity returns the confirmed tier
        decision = _next_attempt_decision(state, ATTACK_IP, 90_000, "c-next")
        assert decision == tier, f"expected {tier} after confirmation, got {decision}"

    def test_confirm_rejects_a_tier_that_is_not_a_proposed_row(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)
        iid = _incident_id(db)
        d = client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": RAW_KEY}).json()
        action = next(a for a in d["enforcement"] if a["tier"] in ("step_up", "block"))

        r = client.post(
            f"/v1/incidents/{iid}/confirm",
            headers={"X-Tollgate-Key": RAW_KEY},
            json={"action_id": action["action_id"], "tier": "throttle"},
        )
        assert r.status_code == 409

    def test_resolve_closes_incident_releases_enforcement_and_restores_the_ceiling(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)
        iid = _incident_id(db)
        d = client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": RAW_KEY}).json()
        action = next(a for a in d["enforcement"] if a["tier"] in ("step_up", "block"))

        # confirm first so there is a raised ceiling to restore
        client.post(
            f"/v1/incidents/{iid}/confirm",
            headers={"X-Tollgate-Key": RAW_KEY},
            json={"action_id": action["action_id"], "tier": action["tier"]},
        )
        assert _next_attempt_decision(state, ATTACK_IP, 90_000, "c-a") == action["tier"]

        rr = client.post(
            f"/v1/incidents/{iid}/resolve",
            headers={"X-Tollgate-Key": RAW_KEY},
            json={"resolution": "false_positive"},
        )
        assert rr.status_code == 200, rr.text

        conn = connect(db)
        try:
            inc = conn.execute("SELECT state, resolution, closed_at FROM incident WHERE incident_id = ?", (iid,)).fetchone()
            active = conn.execute(
                "SELECT COUNT(*) AS c FROM enforcement_action WHERE incident_id = ? AND released_at IS NULL",
                (iid,),
            ).fetchone()["c"]
        finally:
            conn.close()
        assert inc["state"] == "CLOSED"
        assert inc["resolution"] == "false_positive"
        assert inc["closed_at"] is not None
        assert active == 0, "resolve did not release enforcement"

        # the entity is back under the challenge ceiling
        decision = _next_attempt_decision(state, ATTACK_IP, 120_000, "c-b")
        assert decision in ("throttle", "challenge"), f"ceiling not restored: {decision}"

    def test_read_model_carries_no_raw_pan_or_full_card_hash(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)
        iid = _incident_id(db)
        d = client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": RAW_KEY}).json()
        blob = json.dumps(d)
        assert not _PAN_RE.search(blob), "a PAN-like digit run is present in the read model"
        assert not _CARD_HASH_RE.search(blob), "a full card-hash-like token is present in the read model"

    def test_merchant_isolation_and_auth(self, tmp_path):
        db, state, client = _setup(tmp_path)
        score_stream(state, MERCHANT, _burst())
        _drain(state)
        iid = _incident_id(db)

        assert client.get(f"/v1/incidents/{iid}").status_code == 401
        assert client.get(f"/v1/incidents/{iid}", headers={"X-Tollgate-Key": "wrong"}).status_code == 401
        assert client.get("/v1/incidents/I-does-not-exist", headers={"X-Tollgate-Key": RAW_KEY}).status_code == 404
