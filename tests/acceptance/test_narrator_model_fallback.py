"""
Source: env-config plan -- the Gemini model fallback chain in
packages/narrator/gemini.call_gemini().

A model that returns HTTP 404/400 (retired / unknown) advances to the next
model in the chain. A 429 -- or any other fault -- does NOT advance: it is
one failed narration attempt that falls straight back to the template.
Either way there is exactly one narrator_call row per narration.
"""

from __future__ import annotations

import asyncio
import random

import httpx

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.storage.db import connect
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-gem-chain"
ATTACK_IP = "203.0.113.9"
GOOD = (
    '{"narrative": "Entity ip_1 (ip) was assigned tier challenge after distinct '
    'card fan-out from one address.", "confidence_note": "typed evidence only"}'
)


def _seed(tmp_path, suffix):
    db = make_db(tmp_path / suffix)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    return db


def _run_burst(state):
    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("gem-chain"))

    async def _go():
        for i in range(48):
            clock.set_ms(i * 1500)
            body = ScoreRequest(
                event_id=f"e-{i:05d}", card_hash=f"c-{i:03d}", bin="424242",
                amount_minor=1999, currency="INR",
            )
            await score_attempt(
                state, merchant_id=MERCHANT, ip=ATTACK_IP, body=body, clock=clock, ulid=ulid
            )
        pending = list(state.gemini_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(_go())
    state.spool.close()
    state.drainer.drain_from_start()


class _Recorder:
    """MockTransport handler that records every request URL."""

    def __init__(self, responder):
        self.urls: list[str] = []
        self._responder = responder

    def __call__(self, request):
        self.urls.append(str(request.url))
        return self._responder(request)


def _configure(monkeypatch, models: str):
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODELS", models)


def test_404_on_primary_advances_to_the_next_model(tmp_path, monkeypatch):
    _configure(monkeypatch, "retired-model,live-model")

    def _responder(request):
        if "retired-model" in str(request.url):
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": GOOD}]}}]})

    rec = _Recorder(_responder)
    db = _seed(tmp_path, "advance")
    state = build_state(db, tmp_path / "advance" / "sp", MERCHANT)
    state.gemini_transport = httpx.MockTransport(rec)

    _run_burst(state)

    conn = connect(db)
    try:
        inc = conn.execute("SELECT narrative_source FROM incident LIMIT 1").fetchone()
        calls = conn.execute("SELECT status, fallback_used FROM narrator_call").fetchall()
    finally:
        conn.close()

    assert inc["narrative_source"] == "llm"
    assert len(calls) == 1
    assert calls[0]["fallback_used"] == 0
    assert any("retired-model" in u for u in rec.urls)
    assert any("live-model" in u for u in rec.urls)


def test_every_model_404s_falls_back_to_template_with_one_row(tmp_path, monkeypatch):
    _configure(monkeypatch, "dead-1,dead-2")

    rec = _Recorder(lambda request: httpx.Response(404, json={"error": "gone"}))
    db = _seed(tmp_path, "alldead")
    state = build_state(db, tmp_path / "alldead" / "sp", MERCHANT)
    state.gemini_transport = httpx.MockTransport(rec)

    _run_burst(state)

    conn = connect(db)
    try:
        inc = conn.execute("SELECT narrative_source FROM incident LIMIT 1").fetchone()
        calls = conn.execute("SELECT status, fallback_used FROM narrator_call").fetchall()
    finally:
        conn.close()

    assert inc["narrative_source"] == "template"
    assert len(calls) == 1
    assert calls[0]["status"] == "http_404"
    assert calls[0]["fallback_used"] == 1
    assert any("dead-1" in u for u in rec.urls)
    assert any("dead-2" in u for u in rec.urls)


def test_429_does_not_advance_the_chain(tmp_path, monkeypatch):
    _configure(monkeypatch, "primary,secondary")

    rec = _Recorder(lambda request: httpx.Response(429, json={"error": "rate limited"}))
    db = _seed(tmp_path, "ratelimited")
    state = build_state(db, tmp_path / "ratelimited" / "sp", MERCHANT)
    state.gemini_transport = httpx.MockTransport(rec)

    _run_burst(state)

    conn = connect(db)
    try:
        calls = conn.execute("SELECT status, fallback_used FROM narrator_call").fetchall()
    finally:
        conn.close()

    assert len(calls) == 1
    assert calls[0]["status"] == "http_429"
    assert calls[0]["fallback_used"] == 1
    assert all("primary" in u for u in rec.urls)
    assert all("secondary" not in u for u in rec.urls)
