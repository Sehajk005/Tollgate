"""
Source: Day-7 Plan §4 Step 4, acceptance row 9 (Threat Model §6 / the approved
Day-7 decision). A sustained run of fail-opens must:

  * raise `availability.alert` on the SSE payload once the per-merchant budget
    is exceeded,
  * log ERROR exactly ONCE per clock window (that suppression IS the rate
    limit),
  * and STILL return `allow` every time -- the budget governs alerting, never
    the response (Decision 89).
"""

from __future__ import annotations

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
RAW_KEY = "alert-key"
THRESHOLD = 5
N = 12


@pytest.fixture
def alert_client(tmp_path):
    db = tmp_path / "al.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-al', 'al', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
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
        ulid=UlidGenerator(clock=clock, rng=random.Random("al")),
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
        yield client, state
    state.spool.close()


class TestFailOpenAlert:
    def test_sustained_fail_open_alerts_once_per_window_and_stays_allow(self, alert_client, monkeypatch, caplog):
        client, state = alert_client

        # every score attempt fails
        def _boom(_request):
            raise ConnectionError("down")

        monkeypatch.setattr(state.window_store, "score_path", _boom)

        # record every SSE event the route publishes
        events = []
        original_publish = state.event_bus.publish

        async def _recording_publish(evt):
            events.append(evt)
            await original_publish(evt)

        monkeypatch.setattr(state.event_bus, "publish", _recording_publish)

        with caplog.at_level(logging.ERROR, logger="tollgate.scorer.admission"):
            decisions = []
            for i in range(N):
                r = client.post(
                    "/v1/score",
                    json={"event_id": f"e-{i}", "card_hash": f"c-{i}", "bin": "999123",
                          "amount_minor": 1000, "currency": "INR"},
                    headers={"X-Tollgate-Key": RAW_KEY},
                )
                assert r.status_code == 200
                decisions.append(r.json()["decision"])

        # the response is ALWAYS allow -- the budget never changes the tier
        assert decisions == ["allow"] * N

        alerts = [e["availability"]["alert"] for e in events]
        assert alerts[: THRESHOLD - 1] == [False] * (THRESHOLD - 1), (
            f"alert raised before the budget was exceeded: {alerts}"
        )
        assert alerts[-1] is True, "alert must be set on the SSE payload once the budget is exceeded"

        error_logs = [
            r for r in caplog.records
            if r.name == "tollgate.scorer.admission" and r.levelno == logging.ERROR
        ]
        assert len(error_logs) == 1, (
            f"expected exactly one ERROR per window (the rate limit), got {len(error_logs)}"
        )
