"""
Source: Day-8 Plan Step 9 / G14 -- the evaluation harness makes ZERO Gemini
calls. `NARRATOR_ENABLED` is `"false"` throughout the eval path, and even with
`NARRATOR_BACKEND=gemini` + a key set, a transport that raises on any call is
never invoked.
"""

from __future__ import annotations

import asyncio
import os
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

MERCHANT = "m-eval-narr"


class _RaisingTransport(httpx.BaseTransport):
    def __init__(self):
        self.calls = 0

    def handle_request(self, request):  # pragma: no cover - must never run
        self.calls += 1
        raise AssertionError("a Gemini call was dispatched during the eval path")


class TestNarratorEvalDisabled:
    def test_replay_corpus_forces_narrator_enabled_false(self, tmp_path):
        from eval.corpus import build_runs, replay_corpus

        os.environ["NARRATOR_ENABLED"] = "true"  # deliberately wrong going in
        runs = build_runs(42)[:1]  # one tier block is enough to exercise the path
        replay_corpus(runs, db_path=tmp_path / "c.db", spool_dir=tmp_path / "sp", rebuild=True)

        assert os.environ.get("NARRATOR_ENABLED") == "false"
        conn = connect(tmp_path / "c.db")
        try:
            n = conn.execute("SELECT COUNT(*) AS c FROM narrator_call").fetchone()["c"]
        finally:
            conn.close()
        assert n == 0, "the eval replay wrote narrator_call rows"

    def test_disabled_flag_suppresses_dispatch_even_with_gemini_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NARRATOR_ENABLED", "false")
        monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp2", MERCHANT)
        transport = _RaisingTransport()
        state.gemini_transport = transport

        clock = VirtualClock(epoch_ms=0)
        ulid = UlidGenerator(clock=clock, rng=random.Random("eval-narr"))

        async def _go():
            for i in range(48):
                clock.set_ms(i * 1500)
                body = ScoreRequest(
                    event_id=f"e-{i:05d}", card_hash=f"c-{i:03d}", bin="424242",
                    amount_minor=1999, currency="INR",
                )
                await score_attempt(state, merchant_id=MERCHANT, ip="203.0.113.7", body=body, clock=clock, ulid=ulid)
            pending = list(state.gemini_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run(_go())
        state.spool.close()
        state.drainer.drain_from_start()

        assert transport.calls == 0
        assert not state.gemini_tasks, "a narration task was scheduled despite NARRATOR_ENABLED=false"
        conn = connect(db)
        try:
            inc = conn.execute("SELECT narrative_source FROM incident LIMIT 1").fetchone()
            n = conn.execute("SELECT COUNT(*) AS c FROM narrator_call").fetchone()["c"]
        finally:
            conn.close()
        assert inc["narrative_source"] == "template"
        assert n == 0
