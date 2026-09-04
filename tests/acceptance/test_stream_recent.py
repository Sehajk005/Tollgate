"""
Source: Day-8 Plan Step 2 -- the backend seams for the degraded-state banners
and the SSE polling fallback.

  * a shed request publishes EXACTLY ONE event carrying `availability.shed == True`
    (the rules-only banner / the rail's hollow tick had no data source before);
  * `InProcessEventBus.recent(after=<attempt_uid>)` returns exactly the events
    published after that cursor, in order;
  * the recent buffer is bounded at RECENT_BUFFER_MAXLEN;
  * `GET /v1/stream/recent` returns `{"events": [...]}` and keeps the same
    unauthenticated posture as `/v1/stream` (Decision 94 -- no X-Tollgate-Key).
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import RECENT_BUFFER_MAXLEN, InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.admission import AdmissionConfig, AdmissionController, AvailabilityMonitor
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

BURST = 3
RAW_KEY = "recent-key"


def _seed(db: Path) -> None:
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-r', 'r', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
            (hash_api_key(RAW_KEY),),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def recent_client(tmp_path):
    db = tmp_path / "r.db"
    initialize_schema(db, SCHEMA_PATH)
    _seed(db)

    store = InMemoryWindowStore()
    spool = Spool(tmp_path / "spool")
    clock = SystemClock()
    cfg = AdmissionConfig(
        rate_per_s=0.0, burst=BURST, shed_ttl_s=60,
        fail_open_budget_per_min=120, fail_open_alert_threshold=20,
    )
    state = ScorerState(
        clock=clock,
        ulid=UlidGenerator(clock=clock, rng=random.Random("r")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=Drainer(db_path=db, spool_path=spool.path),
        event_bus=InProcessEventBus(),
        db_path=db,
        admission=AdmissionController(cfg),
        availability=AvailabilityMonitor(alert_threshold=20),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state
    state.spool.close()


def _post(client, i):
    return client.post(
        "/v1/score",
        json={"event_id": f"e-{i}", "card_hash": f"c-{i}", "bin": "999123",
              "amount_minor": 1000, "currency": "INR"},
        headers={"X-Tollgate-Key": RAW_KEY},
    )


class TestStreamRecent:
    def test_shed_request_publishes_exactly_one_shed_event(self, recent_client):
        client, state = recent_client

        for i in range(BURST):
            r = _post(client, i)
            assert r.status_code == 200
            assert r.headers.get("X-Tollgate-Shed") is None

        shed = _post(client, 99)
        assert shed.status_code == 200
        assert shed.headers.get("X-Tollgate-Shed") == "1"

        events = state.event_bus.recent()
        shed_events = [e for e in events if e["availability"].get("shed") is True]
        assert len(shed_events) == 1, f"expected exactly one shed event, got {len(shed_events)}"
        se = shed_events[0]
        assert se["attempt_uid"] == shed.json()["attempt_uid"]
        assert se["decision"] in {"allow", "throttle"}
        assert se["availability"]["fail_open"] is False
        assert se["feature_snapshot"].get("degraded_reason") == "shed"
        # every fully-scored event carries the total availability shape too
        for e in events:
            assert set(e["availability"]) >= {"fail_open", "alert", "shed"}

    def test_recent_after_cursor_returns_events_published_after_it_in_order(self, recent_client):
        client, state = recent_client
        for i in range(BURST):
            _post(client, i)
        _post(client, 99)  # one shed
        _post(client, 98)  # another shed

        events = state.event_bus.recent()
        assert len(events) >= 3
        cursor = events[1]["attempt_uid"]
        tail = state.event_bus.recent(after=cursor)
        assert tail == events[2:]

        # the HTTP endpoint mirrors bus.recent(), unauthenticated (Decision 94)
        resp = client.get(f"/v1/stream/recent?after={cursor}")
        assert resp.status_code == 200
        uids = [e["attempt_uid"] for e in resp.json()["events"]]
        assert uids == [e["attempt_uid"] for e in events[2:]]

    def test_recent_buffer_is_bounded(self):
        bus = InProcessEventBus()

        async def _fill():
            for i in range(RECENT_BUFFER_MAXLEN + 50):
                await bus.publish({"attempt_uid": f"a-{i}", "availability": {}})

        asyncio.run(_fill())
        buf = bus.recent()
        assert len(buf) == RECENT_BUFFER_MAXLEN
        assert buf[0]["attempt_uid"] == "a-50"
        assert buf[-1]["attempt_uid"] == f"a-{RECENT_BUFFER_MAXLEN + 49}"

    def test_recent_with_unknown_cursor_returns_whole_buffer(self):
        bus = InProcessEventBus()

        async def _fill():
            for i in range(5):
                await bus.publish({"attempt_uid": f"a-{i}"})

        asyncio.run(_fill())
        assert len(bus.recent(after="a-does-not-exist")) == 5
