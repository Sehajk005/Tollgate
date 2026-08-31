"""
Source: Day-7 Plan §4 Step 6, acceptance row 13 (Threat Model §5 -- S1,
indirect prompt injection into the narrator). Replaying a burst whose UA is a
prompt-injection payload:

  (a) the hostile substring IS retained in auth_attempt.client_evidence
      (it was ingested as evidence -- the test has a real subject),
  (b) it is ABSENT from assemble_prompt(bundle) and from the rendered
      incident narrative,
  (c) the assembled prompt passes CHARSET_RE,
  (d) the narrative is byte-identical to the same burst with a benign UA.

The narrator admission point (`build_bundle`) takes no `user_agent`, so the
hostile bytes have no path to the prompt by construction; this test pins that.
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
from packages.features.compute import FeatureContext, compute_features
from packages.features.memory_store import InMemoryWindowStore
from packages.narrator.bundle import build_bundle
from packages.narrator.prompt import assemble_prompt
from packages.narrator.template import CHARSET_RE
from packages.storage.db import connect
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hostile_ua.jsonl"
MERCHANT = "m-inj"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8").splitlines()[0])


def _run_burst(tmp_path, suffix: str, user_agent: str) -> tuple:
    db = make_db(tmp_path / suffix)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    state = build_state(db, tmp_path / suffix / "sp", MERCHANT)

    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("inj"))

    async def _go():
        for i in range(60):
            clock.set_ms(i * 1200)
            body = ScoreRequest(
                event_id=f"e-{i:05d}", card_hash=f"c-{i:05d}", bin="424242",
                amount_minor=1999, currency="INR",
            )
            await score_attempt(
                state, merchant_id=MERCHANT, ip="203.0.113.7", body=body,
                clock=clock, ulid=ulid, user_agent=user_agent,
            )

    asyncio.run(_go())
    state.spool.close()
    state.drainer.drain_from_start()

    conn = connect(db)
    try:
        inc = conn.execute(
            "SELECT narrative, narrative_source FROM incident LIMIT 1"
        ).fetchone()
        evidence = [
            r["client_evidence"]
            for r in conn.execute("SELECT client_evidence FROM auth_attempt")
        ]
    finally:
        conn.close()
    return inc, evidence


class TestNarratorInjection:
    def test_hostile_user_agent_never_reaches_the_assembled_prompt(self, tmp_path):
        fx = _fixture()
        marker = fx["injection_marker"]

        inc_h, ev_h = _run_burst(tmp_path, "hostile", fx["hostile_user_agent"])
        inc_b, ev_b = _run_burst(tmp_path, "benign", fx["benign_user_agent"])

        # (a) the payload WAS ingested and retained as evidence
        assert any(marker in blob for blob in ev_h), "hostile UA missing from client_evidence"
        assert not any(marker in blob for blob in ev_b), "benign run should carry no marker"

        # an incident opened and carries a template narrative
        assert inc_h is not None and inc_h["narrative"] is not None
        assert inc_h["narrative_source"] == "template"

        # (b) the marker is absent from the narrative
        assert marker not in inc_h["narrative"]
        # (c) the narrative is charset-clean
        assert CHARSET_RE.match(inc_h["narrative"])
        # (d) byte-identical to the benign-UA run
        assert inc_h["narrative"] == inc_b["narrative"]

    def test_assemble_prompt_is_marker_free_and_charset_clean(self):
        fx = _fixture()
        marker = fx["injection_marker"]

        store = InMemoryWindowStore()
        rules = DayOneRules(store)
        ctx = FeatureContext(
            merchant_id="m", attempt_uid="a-1", ingest_ms=0, payload_digest="pd",
            event_id="e-1", ip="203.0.113.7", ua_class="desktop_browser",
            card_hash="c-1", bin="999123", amount_minor=1999, session_id="s-1",
        )
        evaluation = rules.evaluate_from_features(compute_features(store, ctx))

        bundle = build_bundle(
            entity_type="ip", pseudonym="ip_1", decision="challenge", evaluation=evaluation,
        )
        prompt = assemble_prompt(bundle)
        assert marker not in prompt
        assert CHARSET_RE.match(prompt)
