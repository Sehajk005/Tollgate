"""
Source: remediation plan FIX-016 (AUDIT-017).

The D1 "Attempts · 5 min" tile counted `events` -- the dashboard's 200-entry SSE
buffer -- filtered to the last five minutes of EVENT time. Two consequences, both
worst during the exact burst the tile exists to show:

  * it is capped at 200 by construction, so an attack that produces more than
    200 attempts in five minutes is silently under-reported;
  * it is non-monotonic as the event-time window slides across a fixed-size
    buffer, so the number can fall while attempts are still rising.

A frontend buffer limit was, in effect, deciding what a displayed metric meant.

The fix is a merchant-scoped 5-minute attempts window computed inside the SAME
one-round-trip Lua call, published as `feature_snapshot.attempts_per_merchant_5m`.

GATE (plan Appendix item 2), verified before implementing: neither
`test_model_feature_list.py` nor `test_window_differential.py` pins the window
list. The first pins FEATURE_NAMES against the trained artifact; the second
reads named features against the pandas oracle. Adding a window changes neither,
and that is asserted below rather than assumed.
"""

from __future__ import annotations

import pytest

from packages.features.compute import (
    FEATURE_NAMES,
    FeatureContext,
    classify_ua,
    compute_features,
)
from packages.features.keys import MERCHANT_SCOPED_KEY_RE
from packages.features.memory_store import InMemoryWindowStore

MERCHANT = "merchant_attempts"
FIVE_MIN_MS = 5 * 60_000


def _ctx(i: int, ingest_ms: int, ip: str = "198.51.100.5") -> FeatureContext:
    return FeatureContext(
        merchant_id=MERCHANT, attempt_uid=f"uid-{i:06d}", ingest_ms=ingest_ms,
        payload_digest=f"pd-{i}", event_id=f"evt-{i}", ip=ip,
        ua_class=classify_ua("Mozilla/5.0"), card_hash=f"card-{i}", bin="999143",
        amount_minor=1000 + i, session_id=f"s-{i}",
    )


class TestTheMerchantWindow:
    def test_it_counts_every_attempt_regardless_of_ip(self, store=None):
        store = InMemoryWindowStore()
        last = None
        for i in range(50):
            last = compute_features(store, _ctx(i, 1_000_000 + i * 100, ip=f"203.0.113.{i % 40}"))
        assert last.attempts_per_merchant_5m == 50, (
            "the merchant window is scoped to an IP or an entity; it must count "
            "the merchant's whole stream"
        )

    def test_it_exceeds_the_two_hundred_event_frontend_cap(self):
        """The defect in one assertion: the old tile could not report past 200."""
        store = InMemoryWindowStore()
        last = None
        for i in range(450):
            last = compute_features(store, _ctx(i, 1_000_000 + i * 100))
        assert last.attempts_per_merchant_5m == 450, (
            f"the window reported {last.attempts_per_merchant_5m}; a real burst "
            f"exceeds 200 and the tile must be able to say so"
        )

    def test_it_is_monotonic_while_the_window_is_not_sliding(self):
        store = InMemoryWindowStore()
        seen = []
        for i in range(120):
            fv = compute_features(store, _ctx(i, 1_000_000 + i * 100))
            seen.append(fv.attempts_per_merchant_5m)
        assert seen == sorted(seen), "the count went backwards inside its own window"
        assert seen[-1] == 120

    def test_it_expires_with_the_window(self):
        store = InMemoryWindowStore()
        for i in range(10):
            compute_features(store, _ctx(i, 1_000_000 + i * 100))
        # Half an hour later, everything before has aged out.
        late = compute_features(store, _ctx(99, 1_000_000 + 30 * 60_000))
        assert late.attempts_per_merchant_5m == 1, (
            f"stale attempts survived the 5-minute window: "
            f"{late.attempts_per_merchant_5m}"
        )

    def test_it_is_scoped_to_the_merchant(self):
        store = InMemoryWindowStore()
        for i in range(5):
            compute_features(store, _ctx(i, 1_000_000 + i * 100))
        other = FeatureContext(
            merchant_id="merchant_other", attempt_uid="uid-other", ingest_ms=1_000_500,
            payload_digest="pd-o", event_id="evt-o", ip="198.51.100.5",
            ua_class=classify_ua("Mozilla/5.0"), card_hash="card-o", bin="999143",
            amount_minor=1000, session_id="s-o",
        )
        fv = compute_features(store, other)
        assert fv.attempts_per_merchant_5m == 1, (
            "another merchant's attempts leaked into this merchant's window"
        )

    def test_the_window_key_is_merchant_scoped(self):
        store = InMemoryWindowStore()
        compute_features(store, _ctx(0, 1_000_000))
        merchant_keys = [k for k in store._windows if ":w:merchant:" in k]
        assert merchant_keys, "no merchant window key was written"
        for key in merchant_keys:
            assert MERCHANT_SCOPED_KEY_RE.match(key), f"unscoped key: {key}"


class TestTheModelContractIsUnchanged:
    def test_feature_names_is_still_the_documented_twenty_four(self):
        assert len(FEATURE_NAMES) == 24
        assert "attempts_per_merchant_5m" not in FEATURE_NAMES, (
            "the merchant window leaked into the model's feature contract; the "
            "trained artifact would no longer match (test_model_feature_list.py)"
        )

    def test_the_model_input_vector_is_unchanged_in_length_and_order(self):
        store = InMemoryWindowStore()
        fv = compute_features(store, _ctx(0, 1_000_000))
        model_input = [fv.values[name] for name in FEATURE_NAMES]
        assert len(model_input) == 24

    def test_the_snapshot_publishes_the_window_for_the_tile(self):
        store = InMemoryWindowStore()
        fv = compute_features(store, _ctx(0, 1_000_000))
        snapshot = fv.snapshot()
        assert snapshot["attempts_per_merchant_5m"] == 1.0, (
            "the tile has no server-side source to render"
        )

    def test_one_score_path_call_per_invocation(self, monkeypatch):
        """The window must ride along in the SAME round trip -- adding a second
        one would break TRD §6.3's one-round-trip invariant."""
        store = InMemoryWindowStore()
        calls = {"n": 0}
        real = store.score_path

        def counted(request):
            calls["n"] += 1
            return real(request)

        monkeypatch.setattr(store, "score_path", counted)
        compute_features(store, _ctx(0, 1_000_000))
        assert calls["n"] == 1
