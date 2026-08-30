"""
Source: Day-7 Plan §4 Step 4, acceptance rows 6-8 (Impl Plan §Day 7). The
bottom rung: three independent faults all return 200 / `allow` inside the
budget, each leaving a `degraded_reason` row.

  6  Redis down     -- score_path raises ConnectionError -> fail_open:window_store
  7  SQLite locked   -- warm auth cache still authenticates and fail-opens;
                        a COLD cache + unavailable DB returns 503 (auth never
                        fails open, Decision 89)
  8  model raises    -- model.score_one raises -> fail_open:model

Authentication is the one thing that is NEVER allowed to fail open.
"""

from __future__ import annotations

import json
import random
import sqlite3
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
RAW_KEY = "fo-key"


class _Raiser:
    """A stand-in Layer-1 model whose score_one() always raises."""

    model_version = "l1-lgbm-v1"

    def score_one(self, _x):
        raise RuntimeError("model backend exploded")


@pytest.fixture
def fo(tmp_path):
    db = tmp_path / "fo.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-fo', 'fo', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
            (hash_api_key(RAW_KEY),),
        )
        conn.commit()
    finally:
        conn.close()

    store = InMemoryWindowStore()
    spool = Spool(tmp_path / "spool")
    drainer = Drainer(db_path=db, spool_path=spool.path)
    clock = SystemClock()
    state = ScorerState(
        clock=clock,
        ulid=UlidGenerator(clock=clock, rng=random.Random("fo")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=drainer,
        event_bus=InProcessEventBus(),
        db_path=db,
        availability=AvailabilityMonitor(alert_threshold=20),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state, db
    state.spool.close()


def _post(client, key=RAW_KEY, i=0):
    return client.post(
        "/v1/score",
        json={"event_id": f"e-{i}", "card_hash": f"c-{i}", "bin": "999123",
              "amount_minor": 1000, "currency": "INR"},
        headers={"X-Tollgate-Key": key},
    )


def _degraded_reasons(db: Path) -> list:
    conn = connect(db)
    try:
        rows = conn.execute("SELECT feature_snapshot FROM attempt_score").fetchall()
    finally:
        conn.close()
    return [json.loads(r["feature_snapshot"]).get("degraded_reason") for r in rows]


class TestFailOpen:
    def test_redis_down_fails_open_to_allow(self, fo, monkeypatch):
        client, state, db = fo

        def _boom(_request):
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(state.window_store, "score_path", _boom)
        resp = _post(client)

        assert resp.status_code == 200
        assert resp.json()["decision"] == "allow"
        assert resp.json()["latency_ms"] < 150
        state.drainer.drain_once()
        assert "fail_open:window_store" in _degraded_reasons(db)

    def test_model_raises_fails_open_to_allow(self, fo, monkeypatch):
        client, state, db = fo
        state.model = _Raiser()
        state.calibrator = object()  # truthy -- the model branch is entered

        resp = _post(client)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "allow"
        state.drainer.drain_once()
        assert "fail_open:model" in _degraded_reasons(db)

    def test_sqlite_locked_with_warm_cache_authenticates_then_fails_open(self, fo, monkeypatch):
        client, state, db = fo

        # 1. one healthy request warms the api_key_cache
        assert _post(client, i=0).status_code == 200

        # 2. the auth DB is now unavailable
        def _locked():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(state, "db_read_conn", _locked)

        # warm cache -> still authenticates -> 200 allow (never a bypass, never a 5xx)
        warm = _post(client, i=1)
        assert warm.status_code == 200
        assert warm.json()["decision"] == "allow"

        # cold cache (never-seen key) + unavailable DB -> 503, NOT allow
        cold = _post(client, key="never-seen-key", i=2)
        assert cold.status_code == 503
