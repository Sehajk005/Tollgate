"""
Source: env-config plan -- graceful shutdown in services/scorer/app.create_app().

A Gemini narration task that is still in flight when the process shuts down
must be awaited (so it appends its narrator_call row) and the spool must be
flushed, rather than the task being abandoned. Deterministic: the patched
call_gemini blocks on an event until the test releases it from inside the
lifespan, guaranteeing the task is pending at shutdown.
"""

from __future__ import annotations

import asyncio
import random

import packages.narrator.gemini as gemini_mod
from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.storage.db import connect
from services.scorer.app import create_app
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-gem-shutdown"
ATTACK_IP = "203.0.113.11"
GOOD = (
    '{"narrative": "Entity ip_1 (ip) was assigned tier challenge after distinct '
    'card fan-out from one address.", "confidence_note": "typed evidence only"}'
)


def test_shutdown_awaits_pending_narration_and_flushes_its_row(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    db = make_db(tmp_path / "sd")
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    state = build_state(db, tmp_path / "sd" / "sp", MERCHANT)

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_call_gemini(prompt, *, api_key, models=None, transport=None, **_):
        started.set()
        await release.wait()
        chain = list(models) if models else ["m"]
        return gemini_mod.GeminiResponse(text=GOOD, latency_ms=1, model=chain[0])

    monkeypatch.setattr(gemini_mod, "call_gemini", _slow_call_gemini)

    async def _scenario():
        app = create_app(state=state)
        async with app.router.lifespan_context(app):
            clock = VirtualClock(epoch_ms=0)
            ulid = UlidGenerator(clock=clock, rng=random.Random("sd"))
            for i in range(48):
                clock.set_ms(i * 1500)
                body = ScoreRequest(
                    event_id=f"e-{i:05d}", card_hash=f"c-{i:03d}", bin="424242",
                    amount_minor=1999, currency="INR",
                )
                await score_attempt(
                    state, merchant_id=MERCHANT, ip=ATTACK_IP, body=body, clock=clock, ulid=ulid
                )
            await asyncio.wait_for(started.wait(), timeout=2.0)
            assert [t for t in state.gemini_tasks if not t.done()], "narration task should be pending"
            release.set()  # shutdown must now await it to completion
        # lifespan shutdown has run

    asyncio.run(_scenario())

    conn = connect(db)
    try:
        inc = conn.execute("SELECT narrative_source FROM incident LIMIT 1").fetchone()
        calls = conn.execute("SELECT status, fallback_used FROM narrator_call").fetchall()
    finally:
        conn.close()

    assert inc["narrative_source"] == "llm"
    assert len(calls) == 1
    assert calls[0]["fallback_used"] == 0
