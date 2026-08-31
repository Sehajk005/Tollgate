"""
Source: Day-7 Plan §4 Step 1 / Step 2, acceptance rows 1-2 (Threat Model §3/3,
§3/4). Pins the idempotency invariants Days 1-6 already satisfy, then (Step 2)
the stored-decision replay reply.

  R1  40 concurrent identical submissions   -> exactly one window increment,
                                               one auth_attempt row, and 39
                                               responses carrying the winner's
                                               stored (attempt_uid, decision).
  R2  same event_id, mutated payload        -> two window increments and
                                               feature_snapshot["event_id_reuse_count"] == 2
                                               on the second.

No production code is exercised beyond `score_attempt`; the SET-NX guard lives
in `windows.lua` / `memory_store.score_path` and is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.deps import ScorerState
from services.scorer.scoring import score_attempt

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
MERCHANT = "m-idem"


def _make_state(tmp_path: Path) -> ScorerState:
    db = tmp_path / "idem.db"
    initialize_schema(db, SCHEMA_PATH)
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'idem', 'INR', 'Asia/Kolkata', 'k', 'k', 0)",
            (MERCHANT,),
        )
        conn.commit()
    finally:
        conn.close()
    window_store = InMemoryWindowStore()
    spool = Spool(tmp_path / "spool")
    drainer = Drainer(db_path=db, spool_path=spool.path)
    return ScorerState(
        clock=VirtualClock(epoch_ms=0),
        ulid=UlidGenerator(clock=VirtualClock(epoch_ms=0), rng=random.Random("idem")),
        window_store=window_store,
        rules=DayOneRules(window_store),
        spool=spool,
        drainer=drainer,
        event_bus=InProcessEventBus(),
        db_path=db,
    )


def _body(event_id: str, *, amount_minor: int = 1999) -> ScoreRequest:
    return ScoreRequest(
        event_id=event_id, card_hash="card-x", bin="999123",
        amount_minor=amount_minor, currency="INR", session_id="s-1",
    )


class TestR1FortyConcurrentIdentical:
    def test_forty_concurrent_identical_yield_one_increment_and_39_replayed_decisions(self, tmp_path):
        state = _make_state(tmp_path)
        clock = VirtualClock(epoch_ms=0)
        clock.set_ms(1_000_000)
        ulid = UlidGenerator(clock=clock, rng=random.Random("idem-r1"))

        async def _run():
            return await asyncio.gather(*[
                score_attempt(
                    state, merchant_id=MERCHANT, ip="198.51.100.7",
                    body=_body("evt-r1"), clock=clock, ulid=ulid,
                )
                for _ in range(40)
            ])

        results = asyncio.run(_run())
        state.spool.close()
        state.drainer.drain_from_start()

        responses = [resp for resp, _event in results]
        uids = {r.attempt_uid for r in responses}
        decisions = {r.decision for r in responses}
        # Exactly one distinct attempt_uid + decision across all 40 -- the
        # SET-NX winner's, replayed to the other 39 (Day-7 §R1).
        assert len(uids) == 1, f"expected one stored attempt_uid, got {len(uids)}"
        assert len(decisions) == 1, f"expected one stored decision, got {decisions}"

        conn = connect(state.db_path)
        try:
            n_attempts = conn.execute(
                "SELECT COUNT(*) AS c FROM auth_attempt WHERE merchant_id = ?", (MERCHANT,)
            ).fetchone()["c"]
            rows = conn.execute(
                "SELECT s.feature_snapshot AS fs FROM attempt_score s "
                "JOIN auth_attempt a ON a.attempt_uid = s.attempt_uid WHERE a.merchant_id = ?",
                (MERCHANT,),
            ).fetchall()
        finally:
            conn.close()

        assert n_attempts == 1, f"expected exactly one auth_attempt row, got {n_attempts}"
        assert len(rows) == 1, f"expected exactly one attempt_score row, got {len(rows)}"
        snap = json.loads(rows[0]["fs"])
        assert snap["attempts_per_ip_60s"] == 1.0, (
            f"the winner's own window increment must be exactly 1, got {snap['attempts_per_ip_60s']}"
        )


class TestR2MutatedPayload:
    def test_same_event_id_different_amount_yields_two_increments_and_reuse_count_two(self, tmp_path):
        state = _make_state(tmp_path)
        clock = VirtualClock(epoch_ms=0)
        ulid = UlidGenerator(clock=clock, rng=random.Random("idem-r2"))

        async def _run():
            clock.set_ms(2_000_000)
            r1 = await score_attempt(
                state, merchant_id=MERCHANT, ip="198.51.100.9",
                body=_body("evt-r2", amount_minor=1000), clock=clock, ulid=ulid,
            )
            clock.set_ms(2_000_500)
            r2 = await score_attempt(
                state, merchant_id=MERCHANT, ip="198.51.100.9",
                body=_body("evt-r2", amount_minor=2000), clock=clock, ulid=ulid,
            )
            return r1, r2

        (resp1, _e1), (resp2, _e2) = asyncio.run(_run())
        assert resp1.attempt_uid != resp2.attempt_uid, "a mutated payload is not a replay"

        state.spool.close()
        state.drainer.drain_from_start()

        conn = connect(state.db_path)
        try:
            n_attempts = conn.execute(
                "SELECT COUNT(*) AS c FROM auth_attempt WHERE merchant_id = ?", (MERCHANT,)
            ).fetchone()["c"]
            snap2 = json.loads(conn.execute(
                "SELECT feature_snapshot AS fs FROM attempt_score WHERE attempt_uid = ?",
                (resp2.attempt_uid,),
            ).fetchone()["fs"])
        finally:
            conn.close()

        assert n_attempts == 2, f"a mutated payload must produce a second row, got {n_attempts}"
        assert snap2["event_id_reuse_count"] == 2.0, (
            f"event_id seen with two distinct payload digests -> reuse count 2, got "
            f"{snap2['event_id_reuse_count']}"
        )
        assert snap2["attempts_per_ip_5m"] == 2.0, (
            f"the second attempt is a real observation -> two window increments, got "
            f"{snap2['attempts_per_ip_5m']}"
        )
