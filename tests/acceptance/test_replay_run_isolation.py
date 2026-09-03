"""
Source: remediation plan FIX-004 / §10 (AUDIT-005).

`windows.lua` sets `tg:{m}:idem:{digest}` with `SET NX PX` and a 24-HOUR TTL. A
replay's digests are deterministic per (tier, seed, epoch_ms) BY DESIGN, so the
second run of a tier produced byte-identical digests: every SET NX found the
first run's key, the script returned with every window untouched, and
`scoring.py` took the stored-decision early return -- skipping the spool append
AND the SSE publish. The second run of a tier was therefore invisible for
twenty-four hours. On a shared Redis this also silently poisoned the test suite
(AUDIT-010).

The key -- and ONLY the key -- is namespaced per run. `idem_digest` itself is
unchanged, which is what keeps A1-A4's "two fresh runs agree", the golden
fixtures and `test_idempotency_concurrency` valid.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.features.compute import (
    IDEM_TTL_MS,
    REPLAY_IDEM_TTL_MS,
    FeatureContext,
    classify_ua,
    compute_features,
)
from packages.features.keys import idem_key
from packages.features.memory_store import InMemoryWindowStore
from services.scorer.replay import ReplayRequest
from services.scorer.scoring import score_attempt
from tests.acceptance._replay_harness import MERCHANT_ID, build_state

TIER = "easy"


def _run(state, request, run_id):
    driver = state.replay_driver
    driver.mark_starting(request)
    driver._status.run_id = run_id
    return asyncio.run(driver.run(request))


class TestKeyNamespacing:
    def test_storefront_keys_are_byte_identical_to_before(self):
        """The production path must not move at all: Threat Model §3's retry
        contract depends on the exact key and its 24-hour TTL."""
        assert idem_key("m", "abc") == "tg:m:idem:abc"
        assert idem_key("m", "abc", "") == "tg:m:idem:abc"

    def test_a_replay_namespace_isolates_the_key_only(self):
        assert idem_key("m", "abc", "r01ABC:") == "tg:m:idem:r01ABC:abc"

    def test_the_digest_itself_never_varies_with_the_namespace(self):
        store_a, store_b = InMemoryWindowStore(), InMemoryWindowStore()
        ctx = FeatureContext(
            merchant_id="m", attempt_uid="uid-1", ingest_ms=1_000_000,
            payload_digest="pd", event_id="evt-1", ip="1.1.1.1",
            ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999001",
            amount_minor=1000, session_id="s1",
        )
        plain = compute_features(store_a, ctx)
        namespaced = compute_features(store_b, ctx, "r01ABC:")
        assert plain.idem_digest == namespaced.idem_digest, (
            "the namespace leaked into the digest -- determinism tests, golden "
            "fixtures and the decision cache all observe that value"
        )

    def test_replay_keys_get_the_shorter_ttl(self):
        store = InMemoryWindowStore()
        ctx = FeatureContext(
            merchant_id="m", attempt_uid="uid-1", ingest_ms=1_000_000,
            payload_digest="pd", event_id="evt-1", ip="1.1.1.1",
            ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999001",
            amount_minor=1000, session_id="s1",
        )
        compute_features(store, ctx, "r01ABC:")
        key = idem_key("m", ctx.payload_digest and list(store._idem)[0].rsplit(":", 1)[-1], "r01ABC:")
        _uid, expire_at = store._idem[key]
        assert expire_at - ctx.ingest_ms == REPLAY_IDEM_TTL_MS
        assert REPLAY_IDEM_TTL_MS < IDEM_TTL_MS

    def test_a_genuine_storefront_retry_still_replays_idempotently(self):
        """The contract the namespace must NOT break: same event_id + same
        payload on the production path is still one attempt."""
        store = InMemoryWindowStore()
        ctx = FeatureContext(
            merchant_id="m", attempt_uid="uid-1", ingest_ms=1_000_000,
            payload_digest="pd", event_id="evt-1", ip="1.1.1.1",
            ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999001",
            amount_minor=1000, session_id="s1",
        )
        first = compute_features(store, ctx)
        assert first.idempotent_replay is False
        retry = compute_features(store, ctx)
        assert retry.idempotent_replay is True, (
            "a genuine retry no longer replays idempotently -- Threat Model §3 broken"
        )


class TestRepeatRuns:
    def test_two_runs_of_the_same_tier_both_emit_a_full_stream(self, tmp_path):
        state = build_state(tmp_path)
        request = ReplayRequest(tier=TIER, seed=42, speed=0, epoch_ms=0, hours=1)

        first = _run(state, request, "RUN_A")
        assert first.state == "finished"
        assert first.sent == first.total > 0

        # Between runs, exactly what Launch's auto-clear does.
        asyncio.run(state.replay_driver.reset())

        second = _run(state, request, "RUN_B")
        assert second.state == "finished"
        assert second.sent == second.total, (
            f"the second run of {TIER!r} sent {second.sent}/{second.total} -- "
            f"AUDIT-005: the run was swallowed as an idempotent replay"
        )
        assert second.sent == first.sent
        state.spool.close()

    def test_the_first_attempt_of_a_new_run_is_never_an_idempotent_replay(self, tmp_path):
        """Runs are isolated BY CONSTRUCTION -- without any reset at all."""
        state = build_state(tmp_path)
        store = state.window_store
        clock = VirtualClock(epoch_ms=0)
        clock.set_ms(1_000_000)
        ulid = UlidGenerator(clock=clock, rng=random.Random("iso"))
        body = ScoreRequest(
            event_id="evt-shared", card_hash="card-1", bin="999001",
            amount_minor=1000, currency="INR", session_id="s1",
        )

        async def _go():
            a = await score_attempt(
                state, merchant_id=MERCHANT_ID, ip="1.1.1.1", body=body,
                clock=clock, ulid=ulid, idem_namespace="rRUN_A:",
            )
            b = await score_attempt(
                state, merchant_id=MERCHANT_ID, ip="1.1.1.1", body=body,
                clock=clock, ulid=ulid, idem_namespace="rRUN_B:",
            )
            return a, b

        (_resp_a, event_a), (_resp_b, event_b) = asyncio.run(_go())
        assert event_a.get("attempt_uid"), "run A produced no event"
        assert event_b.get("replayed") is not True, (
            "run B's FIRST attempt was treated as an idempotent replay of run A's"
        )
        assert event_b.get("attempt_uid"), "run B produced no event"
        assert event_a["attempt_uid"] != event_b["attempt_uid"]
        # And the two runs really did write separate keys.
        keys = [k for k in store._idem]
        assert any(":idem:rRUN_A:" in k for k in keys)
        assert any(":idem:rRUN_B:" in k for k in keys)
        state.spool.close()

    def test_different_tiers_do_not_contaminate_each_other(self, tmp_path):
        state = build_state(tmp_path)
        easy = _run(state, ReplayRequest(tier="easy", seed=42, speed=0, epoch_ms=0, hours=1), "RUN_E")
        asyncio.run(state.replay_driver.reset())
        medium = _run(state, ReplayRequest(tier="medium", seed=42, speed=0, epoch_ms=0, hours=1), "RUN_M")
        assert easy.state == medium.state == "finished"
        assert easy.sent == easy.total > 0
        assert medium.sent == medium.total > 0
        state.spool.close()
