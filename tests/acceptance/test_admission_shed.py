"""
Source: Day-7 Plan §4 Step 3, acceptance rows 4-5 (Threat Model §4/P4,
Decision 15). The middle rung of FULL -> RULES-ONLY/SHED -> FAIL-OPEN.

  * an over-budget request returns 200 with `X-Tollgate-Shed: 1`
  * the merchant-scoped shed counter `tg:{m}:shed:{ip}` increments
  * ZERO `store.score_path()` calls occur on the shed path (a counting store)
  * the handler-measured latency is < 5 ms (the shed path skips features /
    model / Layer 2 entirely)
  * `attempt_score.shed == 1` after the drain
  * shed is merchant-scoped: merchant A's flood never sheds merchant B, and
    every shed key matches `MERCHANT_SCOPED_KEY_RE`
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.features.keys import MERCHANT_SCOPED_KEY_RE
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.admission import AdmissionConfig, AdmissionController, AvailabilityMonitor
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

BURST = 3  # first 3 requests per merchant pass the full path; the rest shed


class CountingStore:
    """Wraps InMemoryWindowStore and counts score_path() calls."""

    def __init__(self) -> None:
        self._inner = InMemoryWindowStore()
        self.score_path_calls = 0

    def record_and_read(self, request):
        return self._inner.record_and_read(request)

    def score_path(self, request):
        self.score_path_calls += 1
        return self._inner.score_path(request)

    def shed_incr(self, merchant_id, ip, now_ms, ttl_ms):
        return self._inner.shed_incr(merchant_id, ip, now_ms, ttl_ms)

    def clear(self):
        self._inner.clear()

    @property
    def shed_keys(self):
        return dict(self._inner._shed)


def _seed(db: Path, merchant_id: str, raw_key: str) -> None:
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'adm', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
            (merchant_id, hash_api_key(raw_key)),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def shed_client(tmp_path):
    db = tmp_path / "adm.db"
    initialize_schema(db, SCHEMA_PATH)
    _seed(db, "m-a", "key-a")
    _seed(db, "m-b", "key-b")

    store = CountingStore()
    spool = Spool(tmp_path / "spool")
    drainer = Drainer(db_path=db, spool_path=spool.path)
    cfg = AdmissionConfig(
        rate_per_s=0.0, burst=BURST, shed_ttl_s=60,
        fail_open_budget_per_min=120, fail_open_alert_threshold=20,
    )
    clock = SystemClock()
    state = ScorerState(
        clock=clock,
        ulid=UlidGenerator(clock=clock, rng=random.Random("adm")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=drainer,
        event_bus=InProcessEventBus(),
        db_path=db,
        admission=AdmissionController(cfg),
        availability=AvailabilityMonitor(alert_threshold=20),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state, store, db
    state.spool.close()


def _post(client, key, i):
    return client.post(
        "/v1/score",
        json={
            "event_id": f"e-{i}", "card_hash": f"c-{i}", "bin": "999123",
            "amount_minor": 1000, "currency": "INR",
        },
        headers={"X-Tollgate-Key": key},
    )


class TestAdmissionShed:
    def test_over_budget_request_is_shed_without_touching_the_score_path(self, shed_client):
        client, state, store, db = shed_client

        for i in range(BURST):
            r = _post(client, "key-a", i)
            assert r.status_code == 200
            assert r.headers.get("X-Tollgate-Shed") is None

        calls_before = store.score_path_calls
        shed_resp = _post(client, "key-a", 99)

        assert shed_resp.status_code == 200
        assert shed_resp.headers.get("X-Tollgate-Shed") == "1"
        assert store.score_path_calls == calls_before, "shed path must not call score_path()"
        assert shed_resp.json()["latency_ms"] < 5, "shed path skips features/model/Layer 2"

        shed_keys = store.shed_keys
        assert any(k.startswith("tg:m-a:shed:") for k in shed_keys), shed_keys
        assert all(MERCHANT_SCOPED_KEY_RE.match(k) for k in shed_keys)

        state.drainer.drain_once()
        conn = connect(db)
        try:
            n_shed = conn.execute(
                "SELECT COUNT(*) AS c FROM attempt_score WHERE shed = 1"
            ).fetchone()["c"]
        finally:
            conn.close()
        assert n_shed >= 1, "the shed attempt must land as attempt_score.shed = 1"

    def test_shed_is_merchant_scoped(self, shed_client):
        client, state, store, db = shed_client

        # Merchant A exhausts its bucket and then floods.
        for i in range(BURST + 5):
            _post(client, "key-a", i)

        # Merchant B has a full bucket of its own -- it is never shed.
        for i in range(BURST):
            r = _post(client, "key-b", 1000 + i)
            assert r.status_code == 200
            assert r.headers.get("X-Tollgate-Shed") is None, "merchant B must not be shed by A's flood"

        assert not any(k.startswith("tg:m-b:shed:") for k in store.shed_keys)
