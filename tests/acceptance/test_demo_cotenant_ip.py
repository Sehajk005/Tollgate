"""
Source: Day 9 Plan Phase 3 step 6 -- GET /v1/demo/cotenant-ip, the CGNAT
co-tenant "money shot".

  * 404 when `TOLLGATE_DEMO_CONTROLS` is unset (the route does not exist)
  * key-required (401 without / with a bad key)
  * 404 when nothing is under enforcement
  * returns the IP of an `ip`-type live enforcement_action
  * resolves an `ipua`-type enforcement back to its raw IP via auth_attempt
  * a released enforcement is not returned
  * the returned IP, sent as X-Forwarded-For from the declared edge, resolves
    to that IP -- the mechanism the co-tenant checkout depends on
  * the auto-ceiling invariant that stops the co-tenant ever being blocked
"""

from __future__ import annotations

import importlib
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.contracts.decision import Decision
from packages.detect.policy import apply_auto_ceiling
from packages.detect.rules import DayOneRules
from packages.features.compute import ipua_key
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
RAW_KEY = "demo-cot-key"
ENFORCED_IP = "203.0.113.20"  # RFC 5737 TEST-NET-3
UA_CLASS = "browser"


@pytest.fixture
def cot(tmp_path):
    db = tmp_path / "cot.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-cot', 'cot', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
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
        ulid=UlidGenerator(clock=clock, rng=random.Random("cot")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=Drainer(db_path=db, spool_path=spool.path),
        event_bus=InProcessEventBus(),
        db_path=db,
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state, db
    state.spool.close()


def _enforce(db: Path, *, entity_type: str, entity_key: str, released: bool = False):
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO enforcement_action (action_id, incident_id, merchant_id, entity_type, "
            "entity_key, tier, requires_confirmation, confirmed_by, applied_at, expires_at, "
            "released_at, applied_by) VALUES (?, NULL, 'm-cot', ?, ?, 'challenge', 0, 'auto', "
            "1000, 901000, ?, 'auto')",
            (f"act-{entity_type}-{entity_key}", entity_type, entity_key,
             902000 if released else None),
        )
        conn.commit()
    finally:
        conn.close()


def _auth_attempt(db: Path, *, ip: str, ipua: str):
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO auth_attempt (attempt_uid, merchant_id, event_id, payload_digest, "
            "ingest_time, card_hash, bin, amount_minor, currency, ip, ua_class, ipua_key) "
            "VALUES ('att-1', 'm-cot', 'e1', 'pd', 500, 'ch', '999123', 1000, 'INR', ?, ?, ?)",
            (ip, UA_CLASS, ipua),
        )
        conn.commit()
    finally:
        conn.close()


def _get(client, key=RAW_KEY):
    h = {"X-Tollgate-Key": key} if key is not None else {}
    return client.get("/v1/demo/cotenant-ip", headers=h)


class TestGateAndAuth:
    def test_404_without_the_env_gate(self, cot, monkeypatch):
        client, _, db = cot
        monkeypatch.delenv("TOLLGATE_DEMO_CONTROLS", raising=False)
        _enforce(db, entity_type="ip", entity_key=ENFORCED_IP)
        assert _get(client).status_code == 404

    def test_key_required(self, cot, monkeypatch):
        client, _, db = cot
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        _enforce(db, entity_type="ip", entity_key=ENFORCED_IP)
        assert _get(client, key=None).status_code == 401
        assert _get(client, key="wrong").status_code == 401


class TestLedgerLookup:
    def test_404_when_nothing_is_enforced(self, cot, monkeypatch):
        client, _, _ = cot
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        r = _get(client)
        assert r.status_code == 404
        assert "enforcement" in r.json()["detail"]

    def test_returns_the_ip_of_an_ip_type_enforcement(self, cot, monkeypatch):
        client, _, db = cot
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        _enforce(db, entity_type="ip", entity_key=ENFORCED_IP)
        body = _get(client).json()
        assert body["ip"] == ENFORCED_IP
        assert body["entity_type"] == "ip"

    def test_resolves_an_ipua_enforcement_back_to_a_raw_ip(self, cot, monkeypatch):
        client, _, db = cot
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        ipua = ipua_key(ENFORCED_IP, UA_CLASS)
        _enforce(db, entity_type="ipua", entity_key=ipua)
        _auth_attempt(db, ip=ENFORCED_IP, ipua=ipua)
        body = _get(client).json()
        assert body["ip"] == ENFORCED_IP
        assert body["entity_type"] == "ipua"

    def test_a_released_enforcement_is_not_returned(self, cot, monkeypatch):
        client, _, db = cot
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        _enforce(db, entity_type="ip", entity_key=ENFORCED_IP, released=True)
        assert _get(client).status_code == 404


class _FakeReq:
    def __init__(self, peer, xff):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


class TestTheCheckoutMechanism:
    def test_the_returned_ip_is_honoured_as_xff_only_from_the_declared_edge(self, monkeypatch):
        monkeypatch.setenv("TOLLGATE_TRUSTED_EDGE_HOSTS", "10.9.9.9")
        import services.scorer.net as net

        importlib.reload(net)
        try:
            assert net.resolve_client_ip(_FakeReq("10.9.9.9", ENFORCED_IP)) == ENFORCED_IP
            assert net.resolve_client_ip(_FakeReq("172.16.0.9", ENFORCED_IP)) == "172.16.0.9"
        finally:
            monkeypatch.delenv("TOLLGATE_TRUSTED_EDGE_HOSTS", raising=False)
            importlib.reload(net)

    def test_auto_ceiling_stops_the_cotenant_being_blocked(self):
        """Plan step 6: "passes one checkbox, gets the order" -- the automatic
        ceiling is `challenge`, so even a block-grade score cannot block a
        legitimate co-tenant without operator confirmation."""
        assert apply_auto_ceiling(Decision.BLOCK) == Decision.CHALLENGE
        assert apply_auto_ceiling(Decision.CHALLENGE) == Decision.CHALLENGE
        assert apply_auto_ceiling(Decision.ALLOW) == Decision.ALLOW
