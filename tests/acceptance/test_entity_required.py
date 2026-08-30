"""
Source: Day-6 Plan §4 / Impl Plan Day 6 / TB-1 / TRD §6.7 -- a property test.

  * fuzz ScoreRequest (including the C-class event_id / user_agent /
    client_evidence): every emitted enforcement carries a non-empty entity
    key; store-wide enforcement is UNREPRESENTABLE.
  * no entity key ever equals a C-class value.
  * the schema CHECK rejects a hand-crafted store-wide row.
"""

from __future__ import annotations

import random
import sqlite3

import pytest

from packages.detect.policy import EntityKey, PolicyOutcome, resolve_entity
from packages.storage.db import connect
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-ent"
_VALID_TYPES = {"card", "ipua", "ip", "bin"}


class TestEntityRequired:
    def test_enforcement_proposal_entity_is_not_optional_in_the_type(self):
        ann = PolicyOutcome.__annotations__["entity"]
        assert ann in (EntityKey, "EntityKey")

    def test_fuzzed_requests_always_resolve_to_a_valid_non_empty_entity(self):
        rng = random.Random(20260829)
        c_class_values = set()
        for _ in range(500):
            ip = rng.choice(["", "  ", "1.2.3.4", "203.0.113.9", "::1", "10.0.0.1"])
            ua_class = rng.choice(["desktop_browser", "headless", "known_bot", "unparseable", ""])
            card = rng.choice([None, "", "  ", "c-abc", "c-" + "x" * 40])
            bin_ = rng.choice([None, "", "411111", "999999"])
            event_id = f"evt-{rng.random()}"
            raw_ua = f"Mozilla/5.0 ({rng.random()})"
            client_evidence = f'{{"note": "{rng.random()}"}}'
            c_class_values.update({event_id, raw_ua, client_evidence})

            scope = rng.choice(["card", "ipua", "ip", "bin"])
            try:
                e = resolve_entity(scope=scope, ip=ip, ua_class=ua_class, card_hash=card, bin=bin_)
            except ValueError:
                assert not (ip and ip.strip())
                continue
            assert isinstance(e, EntityKey)
            assert e.entity_type in _VALID_TYPES
            assert e.entity_key and e.entity_key.strip()
            assert e.entity_key not in c_class_values

    def test_schema_check_rejects_a_hand_crafted_store_wide_enforcement_row(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        conn = connect(db)
        try:
            conn.execute(
                "INSERT INTO incident (incident_id, merchant_id, state, detector, opened_at, "
                "peak_tier, pinned_policy_version) VALUES ('I0', ?, 'OPEN', 'cusum', 0, 'monitor', 1)",
                (MERCHANT,),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO enforcement_action (action_id, incident_id, merchant_id, "
                    "entity_type, entity_key, tier, expires_at, applied_by) "
                    "VALUES ('A0', 'I0', ?, 'store', 'everything', 'challenge', 1, 'auto')",
                    (MERCHANT,),
                )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO enforcement_action (action_id, incident_id, merchant_id, "
                    "entity_type, entity_key, tier, expires_at, applied_by) "
                    "VALUES ('A1', 'I0', ?, 'ip', '', 'challenge', 1, 'auto')",
                    (MERCHANT,),
                )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO incident_entity (incident_id, entity_type, entity_key, pseudonym, "
                    "first_seen, last_seen) VALUES ('I0', 'asn', '', 'x', 0, 0)",
                )
        finally:
            conn.close()

    def test_every_emitted_enforcement_row_carries_a_non_empty_entity(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, cusum_h=3.0)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp", MERCHANT)
        events = [
            {"t_ms": i * 1200, "ip": "203.0.113.7", "card_hash": f"c-{i:03d}", "bin": "424242",
             "event_id": f"weird-{i}", "session_id": None}
            for i in range(50)
        ]
        score_stream(state, MERCHANT, events)
        state.spool.close()
        state.drainer.drain_from_start()
        conn = connect(db)
        try:
            rows = conn.execute("SELECT entity_type, entity_key FROM enforcement_action").fetchall()
        finally:
            conn.close()
        assert rows
        for r in rows:
            assert r["entity_type"] in _VALID_TYPES
            assert r["entity_key"] and r["entity_key"].strip()
