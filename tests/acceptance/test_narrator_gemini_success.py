"""
Source: Day-8 Plan Step 9 -- the Gemini narrator success case. A valid
stubbed response sets `narrative_source == "llm"`, the narrative is <= 600
chars and charset-clean, and a `narrator_call` row exists with
`fallback_used = 0` and a latency.
"""

from __future__ import annotations

import asyncio
import random

import httpx

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.narrator.template import CHARSET_RE, MAX_NARRATIVE_CHARS
from packages.storage.db import connect
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-gem-ok"
ATTACK_IP = "203.0.113.7"
LLM_TEXT = (
    '{"narrative": "Entity ip_1 (ip) was assigned tier challenge after distinct '
    'card fan-out from one address.", "confidence_note": "LLM summary of the '
    'typed evidence only."}'
)


def _handler(req):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": LLM_TEXT}]}}]})


def _run(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    db = make_db(tmp_path)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    state = build_state(db, tmp_path / "sp", MERCHANT)
    state.gemini_transport = httpx.MockTransport(_handler)

    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("gem-ok"))

    async def _go():
        for i in range(48):
            clock.set_ms(i * 1500)
            body = ScoreRequest(
                event_id=f"e-{i:05d}", card_hash=f"c-{i:03d}", bin="424242",
                amount_minor=1999, currency="INR",
            )
            await score_attempt(state, merchant_id=MERCHANT, ip=ATTACK_IP, body=body, clock=clock, ulid=ulid)
        pending = list(state.gemini_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(_go())
    state.spool.close()
    state.drainer.drain_from_start()
    return db


class TestNarratorGeminiSuccess:
    def test_valid_response_sets_llm_source_and_records_the_call(self, tmp_path, monkeypatch):
        db = _run(tmp_path, monkeypatch)
        conn = connect(db)
        try:
            inc = conn.execute("SELECT narrative, narrative_source FROM incident LIMIT 1").fetchone()
            calls = conn.execute(
                "SELECT backend, status, latency_ms, fallback_used FROM narrator_call"
            ).fetchall()
        finally:
            conn.close()

        assert inc["narrative_source"] == "llm"
        assert len(inc["narrative"]) <= MAX_NARRATIVE_CHARS
        assert CHARSET_RE.match(inc["narrative"]), inc["narrative"]
        assert "Entity ip_1" in inc["narrative"]

        assert len(calls) == 1
        assert calls[0]["backend"] == "gemini"
        assert calls[0]["fallback_used"] == 0
        assert calls[0]["latency_ms"] is not None
