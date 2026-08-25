"""
Builder-authored, advisory (Impl Plan v2.1 §1.8) -- not an acceptance gate.

Day-3 Plan Step 6 -- DayOneRules.evaluate() (three record_and_read() calls)
and DayOneRules.evaluate_from_features() (one compute_features() call) must
agree on identical input, since Step 7 wires the score path through the
batched path while the locked Day-1 acceptance tests still exercise the
per-call path directly.
"""

from __future__ import annotations

from packages.detect.rules import DayOneRules, RuleInput
from packages.features.compute import FeatureContext, classify_ua, compute_features
from packages.features.memory_store import InMemoryWindowStore


def test_evaluate_and_evaluate_from_features_agree_across_a_burst():
    store_a = InMemoryWindowStore()
    store_b = InMemoryWindowStore()
    rules_a = DayOneRules(store_a)
    rules_b = DayOneRules(store_b)

    for i in range(25):
        attempt_uid = f"uid-{i}"
        ingest_ms = 1_000_000 + i * 1000
        ip = "5.5.5.5"
        card_hash = f"card-{i}"
        bin_ = "999143"

        result_a = rules_a.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=attempt_uid, ingest_ms=ingest_ms,
            ip=ip, card_hash=card_hash, bin=bin_,
        ))

        ctx = FeatureContext(
            merchant_id="m1", attempt_uid=attempt_uid, ingest_ms=ingest_ms,
            payload_digest=f"dig-{i}", event_id=f"evt-{i}", ip=ip,
            ua_class=classify_ua("Mozilla/5.0"), card_hash=card_hash, bin=bin_,
            amount_minor=1000, session_id="s1",
        )
        features = compute_features(store_b, ctx)
        result_b = rules_b.evaluate_from_features(features)

        assert result_a.minimum_tier == result_b.minimum_tier
        assert result_a.feature_snapshot == result_b.feature_snapshot
