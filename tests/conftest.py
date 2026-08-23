"""
Shared fixtures for the acceptance and unit suites.
"""

from __future__ import annotations

import secrets
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
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


@pytest.fixture
def tmp_workspace(tmp_path: Path):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    return db_path, spool_dir


def seed_merchant(db_path: Path, merchant_id: str = "merchant_test") -> str:
    raw_key = secrets.token_urlsafe(16)
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES (?, 'Test Merchant', 'INR', 'Asia/Kolkata', ?, ?, 0)
            """,
            (merchant_id, hash_api_key(raw_key), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
                      'challenge', 10, 0.05, '{}', 0)
            """,
            (merchant_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return raw_key


@pytest.fixture
def scorer_state(tmp_workspace):
    db_path, spool_dir = tmp_workspace
    clock = SystemClock()
    ulid = UlidGenerator(clock=clock)
    window_store = InMemoryWindowStore()
    rules = DayOneRules(window_store)
    spool = Spool(spool_dir)
    drainer = Drainer(db_path=db_path, spool_path=spool.path)
    bus = InProcessEventBus()
    state = ScorerState(
        clock=clock, ulid=ulid, window_store=window_store, rules=rules,
        spool=spool, drainer=drainer, event_bus=bus, db_path=db_path,
    )
    yield state
    state.spool.close()


@pytest.fixture
def client(scorer_state, tmp_workspace):
    db_path, _ = tmp_workspace
    api_key = seed_merchant(db_path)
    app = create_app(state=scorer_state)
    with TestClient(app) as test_client:
        test_client.tollgate_api_key = api_key
        yield test_client
