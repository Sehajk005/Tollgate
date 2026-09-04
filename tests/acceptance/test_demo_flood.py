"""
Source: Day 9 Plan Phase 3 step 7 -- the flood toggle.

The flood is a REAL concurrent `POST /v1/score` load (DemoFloodRunner) that
drains the merchant token bucket exactly as an attacker flood would; the
rules-only shed rung is then reached by the genuine
`AdmissionController.try_consume` path. The plan says the shed states
(`X-Tollgate-Shed: 1`, `degraded_reason: "shed"`, `availability.shed: true`)
are OBSERVED on the running stack, not asserted into -- see
`evidence/day-9/phase-3-j6-6-8.md`. These tests pin the parts that are
unit-checkable:

  * the route 404s without `TOLLGATE_DEMO_CONTROLS=1`
  * key-required
  * `enabled: true` with no merchant key in the environment -> 503 (loud
    refusal), never a silent success
  * `enabled: false` is a safe no-op
  * the flood NEVER sets `shed` directly -- it only issues `POST /v1/score`
"""

from __future__ import annotations

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
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
RAW_KEY = "demo-flood-key"


@pytest.fixture
def flood_client(tmp_path, monkeypatch):
    monkeypatch.delenv("VITE_TOLLGATE_API_KEY", raising=False)
    monkeypatch.delenv("TOLLGATE_API_KEY", raising=False)
    db = tmp_path / "fld.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES ('m-fld', 'fld', 'INR', 'Asia/Kolkata', ?, 'k', 0)",
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
        ulid=UlidGenerator(clock=clock, rng=random.Random("fld")),
        window_store=store,
        rules=DayOneRules(store),
        spool=spool,
        drainer=Drainer(db_path=db, spool_path=spool.path),
        event_bus=InProcessEventBus(),
        db_path=db,
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        yield client, state
    state.spool.close()


def _post(client, enabled, key=RAW_KEY):
    h = {"X-Tollgate-Key": key} if key is not None else {}
    return client.post("/v1/demo/flood", json={"enabled": enabled}, headers=h)


class TestGateAndAuth:
    def test_404_without_the_env_gate(self, flood_client, monkeypatch):
        client, _ = flood_client
        monkeypatch.delenv("TOLLGATE_DEMO_CONTROLS", raising=False)
        assert _post(client, True).status_code == 404

    def test_key_required(self, flood_client, monkeypatch):
        client, _ = flood_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        assert _post(client, True, key=None).status_code == 401
        assert _post(client, True, key="wrong").status_code == 401


class TestFloodContract:
    def test_enable_without_a_merchant_key_in_env_refuses_loudly(self, flood_client, monkeypatch):
        client, state = flood_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        r = _post(client, True)
        assert r.status_code == 503
        assert "key" in r.json()["detail"].lower()
        assert getattr(state, "demo_flood", None) is None or not state.demo_flood.running

    def test_disable_is_a_safe_noop_when_not_running(self, flood_client, monkeypatch):
        client, _ = flood_client
        monkeypatch.setenv("TOLLGATE_DEMO_CONTROLS", "1")
        r = _post(client, False)
        assert r.status_code == 200
        assert r.json()["flood"] is False

    def test_flood_never_sets_shed_directly(self):
        """The flood may only reach the shed rung through the real
        AdmissionController. Its modules must not touch any window-store /
        shed API."""
        import services.scorer.demo as demo_mod
        import services.scorer.routes_demo as routes_mod

        forbidden = ("shed_incr", "window_store", "_shed(", "availability.shed", "degraded_reason")
        for mod in (demo_mod, routes_mod):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in src, (
                    f"{mod.__name__} references {token!r} -- the flood must not "
                    f"drive shed except through /v1/score + AdmissionController"
                )
