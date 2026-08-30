"""
Source: Day-8 Plan Step 9 -- the Gemini narrator fallback cases.

An injected `httpx` transport produces, in turn: invalid JSON, HTTP 429, a
timeout, and a charset-violating narrative. For each:
  * the incident's narrative is byte-identical to `template.render()`'s output,
  * `narrative_source == "template"`,
  * exactly one `narrator_call` row exists with `fallback_used = 1` and a
    status naming the fault,
  * NO exception reaches the caller.
"""

from __future__ import annotations

import asyncio
import random

import httpx
import pytest

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

MERCHANT = "m-gem-fb"
ATTACK_IP = "203.0.113.7"


def _burst(n=48):
    return [
        {"t_ms": i * 1500, "ip": ATTACK_IP, "card_hash": f"c-{i:03d}", "bin": "424242"}
        for i in range(n)
    ]


def _run_burst(state):
    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("gem-fb"))

    async def _go():
        for i, ev in enumerate(_burst()):
            clock.set_ms(ev["t_ms"])
            body = ScoreRequest(
                event_id=f"e-{i:05d}", card_hash=ev["card_hash"], bin=ev["bin"],
                amount_minor=1999, currency="INR",
            )
            await score_attempt(state, merchant_id=MERCHANT, ip=ev["ip"], body=body, clock=clock, ulid=ulid)
        # await the out-of-band narration tasks before the loop closes
        pending = list(state.gemini_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(_go())
    state.spool.close()
    state.drainer.drain_from_start()


def _seed(tmp_path, suffix):
    db = make_db(tmp_path / suffix)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    return db


def _template_narrative(tmp_path, monkeypatch):
    """The narrative a pure-template run of the same burst produces."""
    monkeypatch.delenv("NARRATOR_BACKEND", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    db = _seed(tmp_path, "tmpl")
    state = build_state(db, tmp_path / "tmpl" / "sp", MERCHANT)
    _run_burst(state)
    conn = connect(db)
    try:
        row = conn.execute("SELECT narrative, narrative_source FROM incident LIMIT 1").fetchone()
    finally:
        conn.close()
    return row["narrative"], row["narrative_source"]


def _candidate(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _fault_invalid_json(req):
    return httpx.Response(200, json=_candidate("not valid json {{{"))


def _fault_http_429(req):
    return httpx.Response(429, json={"error": "rate limited"})


def _fault_timeout(req):
    raise httpx.ReadTimeout("slow", request=req)


def _fault_charset(req):
    # valid JSON, but the narrative carries a byte outside CHARSET_RE (BEL, 0x07)
    return httpx.Response(200, json=_candidate('{"narrative": "hostile \\u0007 bytes", "confidence_note": "x"}'))


_FAULTS = {
    "invalid_json": _fault_invalid_json,
    "http_429": _fault_http_429,
    "timeout": _fault_timeout,
    "charset": _fault_charset,
}


class TestNarratorGeminiFallback:
    @pytest.mark.parametrize("fault", list(_FAULTS))
    def test_each_fault_falls_back_to_the_template_with_a_recorded_call(self, tmp_path, monkeypatch, fault):
        expected_narrative, _ = _template_narrative(tmp_path, monkeypatch)

        monkeypatch.setenv("NARRATOR_ENABLED", "true")
        monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        db = _seed(tmp_path, fault)
        state = build_state(db, tmp_path / fault / "sp", MERCHANT)
        state.gemini_transport = httpx.MockTransport(_FAULTS[fault])

        _run_burst(state)  # must NOT raise

        conn = connect(db)
        try:
            inc = conn.execute("SELECT narrative, narrative_source FROM incident LIMIT 1").fetchone()
            calls = conn.execute(
                "SELECT backend, status, fallback_used FROM narrator_call"
            ).fetchall()
        finally:
            conn.close()

        assert inc["narrative"] == expected_narrative, "narrative diverged from the template"
        assert inc["narrative_source"] == "template"
        assert len(calls) == 1, f"expected exactly one narrator_call row, got {len(calls)}"
        assert calls[0]["backend"] == "gemini"
        assert calls[0]["fallback_used"] == 1
        assert calls[0]["status"] in {"invalid_json", "http_429", "timeout", "charset"}
