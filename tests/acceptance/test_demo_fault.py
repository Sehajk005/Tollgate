"""
Source: Day 9 Plan Phase 3 step 8 -- the in-scorer fail-open fault injector.

  * inert without `TOLLGATE_DEMO_CONTROLS=1` -- the route 404s AND flipping the
    flag by hand does not change /v1/score
  * with the gate + the toggle: /v1/score returns 200 `allow` (never a 5xx),
    writes a `fail_open:model` degraded_reason
  * a sustained breach raises `availability.alert` and logs ERROR exactly once
    per clock window; the response stays `allow`
  * toggling the fault back off restores the full path
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.admission import AvailabilityMonitor
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
RAW_KEY = "demo-fault-key"
THRESHOLD = 4


@pytest.fixture
def fault_client(tmp_path):
    db = tmp_path / "df.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-df', 'df', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
            (hash_api_key(RAW_KEY),),
        )
        conn.commit()
    finally:
        conn.close()

    store = InMemoryWindowStore()
    spool = Spool(tmp_path / "spool")
    clock = SystemClock()
    state = ScorerState(
        clock=clock,
        ulid=UlidGenerator(clock=clock, rng=random.Random("df")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=Drainer(db_path=db, spool_path=spool.path),
        event_bus=InProcessEventBus(),
        db_path=db,
        availability=AvailabilityMonitor(alert_threshold=THRESHOLD, window_ms=60_000),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state, db
    state.spool.close()


def _score(client, i=0, key=RAW_KEY):
    return client.post(
        "/v1/score",
        json={"event_id": f"df-{i}", "card_hash": f"c-{i}", "bin": "999123",
              "amount_minor": 1000, "currency": "INR"},
        headers={"X-Tollgate-Key": key},
    )


def _reasons(db: Path) -> list:
    conn = connect(db)
    try:
        rows = conn.execute("SELECT feature_snapshot FROM attempt_score").fetchall()
    finally:
        conn.close()
    return [json.loads(r["feature_snapshot"]).get("degraded_reason") for r in rows]


class TestInertWithoutTheGate:
    def test_route_404s_when_demo_controls_unset(self, fault_client, monkeypatch):
        client, _, _ = fault_client
        monkeypatch.delenv("TOLLGATE_DEMO_CONTROLS", raising=False)
        r = client.post("/v1/demo/fault", json={"enabled": True}, headers={"X-Tollgate-Key": RAW_KEY})
        assert r.status_code == 404

    def test_flag_set_by_hand_does_not_affect_score_without_the_env_gate(self, fault_client, monkeypatch):
        client, state, db = fault_client
        monkeypatch.delenv("TOLLGATE_DEMO_CONTROLS", raising=False)
        state.demo_fault = True  # the toggle alone must not be enough
        r = _score(client)
        assert r.status_code == 200
        state.drainer.drain_once()
        assert "fail_open:model" not in _reasons(db)


class TestInjectorDrivesRealFailOpen:
    def test_enabled_makes_score_fail_open_to_allow_never_5xx(self, fault_client, monkeypatch):
        client, state, db = fault_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")

        assert client.post("/v1/demo/fault", json={"enabled": True},
                           headers={"X-Tollgate-Key": RAW_KEY}).json() == {"fault": True}

        r = _score(client, i=1)
        assert r.status_code == 200
        assert r.json()["decision"] == "allow"
        state.drainer.drain_once()
        assert "fail_open:model" in _reasons(db)

    def test_auth_still_required(self, fault_client, monkeypatch):
        client, _, _ = fault_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        assert client.post("/v1/demo/fault", json={"enabled": True}).status_code == 401
        assert client.post("/v1/demo/fault", json={"enabled": True},
                           headers={"X-Tollgate-Key": "wrong"}).status_code == 401

    def test_sustained_breach_alerts_once_per_window_and_stays_allow(self, fault_client, monkeypatch, caplog):
        client, state, _ = fault_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        client.post("/v1/demo/fault", json={"enabled": True}, headers={"X-Tollgate-Key": RAW_KEY})

        with caplog.at_level(logging.ERROR, logger="tollgate.scorer.admission"):
            for i in range(THRESHOLD + 6):
                r = _score(client, i=i)
                assert r.status_code == 200 and r.json()["decision"] == "allow"
            errors = [rec for rec in caplog.records if rec.levelno == logging.ERROR]

        assert len(errors) == 1, f"expected exactly one ERROR per window, got {len(errors)}"
        assert state.availability.is_alerting("m-df", state.clock.now_ms())

    def test_toggling_off_restores_the_full_path(self, fault_client, monkeypatch):
        client, state, db = fault_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        client.post("/v1/demo/fault", json={"enabled": True}, headers={"X-Tollgate-Key": RAW_KEY})
        assert _score(client, i=1).json()["decision"] == "allow"

        assert client.post("/v1/demo/fault", json={"enabled": False},
                           headers={"X-Tollgate-Key": RAW_KEY}).json() == {"fault": False}
        r = _score(client, i=2)
        assert r.status_code == 200
        state.drainer.drain_once()
        conn = connect(db)
        try:
            last = conn.execute(
                "SELECT feature_snapshot FROM attempt_score ORDER BY scored_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert json.loads(last["feature_snapshot"]).get("degraded_reason") is None
