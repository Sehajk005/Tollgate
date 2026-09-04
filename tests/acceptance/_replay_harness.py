"""
Shared builders for the replay-lifecycle acceptance tests (NOT a test module --
the leading underscore keeps pytest from collecting it).

`tests/conftest.py::scorer_state` deliberately builds a BARE `ScorerState` with
`replay_driver=None`, which is why no existing test exercised `/v1/replay/*`
through a TestClient at all -- and why five lifecycle defects (AUDIT-002, 003,
004, 007, 013) shipped with a green suite. This assembles the state those routes
actually need, against the same merchant the driver scores as
(`deps.DEMO_MERCHANT_ID`), so the API surface is testable in-process.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from fastapi.testclient import TestClient

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.detect.threat_state import ThreatRollup
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import DEMO_MERCHANT_ID, ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

API_KEY = "test-key-replay-lifecycle"
MERCHANT_ID = DEMO_MERCHANT_ID

TIER_LADDER = {
    "throttle": 0.06474820143884892,
    "challenge": 0.2571428571428571,
    "step_up": 0.5094339622641509,
    "block": 0.8737864077669902,
}


def seed(db_path: Path, *, with_layer2: bool = False) -> str:
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'Replay Lifecycle', 'INR', 'Asia/Kolkata', ?, ?, 0)",
            (MERCHANT_ID, hash_api_key(API_KEY), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, 1, ?, 0.08, 300, 5.0, 3.0, 10, 1800, 0, 'challenge', 10, 0.0, '{}', 0)
            """,
            (MERCHANT_ID, json.dumps(TIER_LADDER) if with_layer2 else "{}"),
        )
        if with_layer2:
            conn.execute(
                """
                INSERT OR REPLACE INTO store_baseline (
                    merchant_id, hourly_volume_profile, decline_rate_mean, decline_rate_std,
                    amount_p05_minor, amount_p50_minor, amount_p95_minor, bin_entropy_mean,
                    bin_entropy_std, foreign_bin_share_mean, foreign_bin_share_std,
                    cards_per_ip_quantiles, flagged_rate_mean, sample_count, is_stable, updated_at
                ) VALUES (?, ?, 0, 0, 100, 500, 2000, 0, 0, 0, 0, ?, 1.0, 100, 0, 0)
                """,
                (
                    MERCHANT_ID,
                    json.dumps([60.0] * 24),
                    json.dumps({
                        "5m": [1, 1, 1, 1, 1, 2, 2, 3, 4, 5, 10],
                        "30m": [1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 12],
                    }),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return API_KEY


def build_state(tmp_path: Path, *, with_layer2: bool = False, window_store=None) -> ScorerState:
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "tollgate.db"
    seed(db_path, with_layer2=with_layer2)

    store = window_store if window_store is not None else InMemoryWindowStore()
    clock = SystemClock()
    spool = Spool(tmp_path / "spool")
    state = ScorerState(
        clock=clock,
        ulid=UlidGenerator(clock=clock, rng=random.Random("replay-harness")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=Drainer(db_path=db_path, spool_path=spool.path),
        event_bus=InProcessEventBus(),
        db_path=db_path,
        threat=ThreatRollup(),
    )
    if with_layer2:
        policy, baseline, layer2, incidents, engine, ttl_ms = ScorerState._load_layer2(
            db_path, MERCHANT_ID
        )
        assert policy is not None, "Layer 2 did not load -- the harness seeding is wrong"
        state.policy, state.baseline, state.layer2 = policy, baseline, layer2
        state.incidents, state.policy_engine, state.enforcement_ttl_ms = incidents, engine, ttl_ms
        state.policy_versions = {policy.version: policy}

    from services.scorer.replay import ReplayDriver

    state.replay_driver = ReplayDriver(state, merchant_id=MERCHANT_ID)
    return state


def client_for(state: ScorerState) -> TestClient:
    return TestClient(create_app(state=state))


def auth() -> dict:
    return {"X-Tollgate-Key": API_KEY}
