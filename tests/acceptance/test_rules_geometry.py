"""
Source: Implementation Plan v2.1 Day 1 -- "R3 geometry test"
(decisions.md, decision 2): proves distinct_cards_per_bin is measured, not
distinct_bins_per_ip.
"""

from __future__ import annotations

from packages.contracts.decision import Decision
from packages.detect.rules import DayOneRules, RuleInput
from packages.features.memory_store import InMemoryWindowStore


def test_bin_concentration_across_many_ips_fires_r3_not_r2():
    # (a) one BIN, 20 distinct cards spread over 20 IPs -> R3 fires, R2 does not.
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = None
    for i in range(20):
        result = rules.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=f"attempt-{i}", ingest_ms=1000,
            ip=f"10.0.0.{i}", card_hash=f"card-{i}", bin="411111",
        ))
    fired = set(result.fired_names)
    assert "distinct_cards_per_bin_5m" in fired
    assert "distinct_cards_per_ip_5m" not in fired
    assert result.minimum_tier == Decision.CHALLENGE


def test_bin_diversity_from_one_ip_fires_r2_not_r3():
    # (b) one IP, 20 distinct BINs, one card each -> R2 fires, R3 does not.
    # An implementation that computed distinct_bins_per_ip would wrongly
    # fire R3 here.
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = None
    for i in range(20):
        result = rules.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=f"attempt-{i}", ingest_ms=1000,
            ip="10.0.0.1", card_hash=f"card-{i}", bin=f"{400000 + i}",
        ))
    fired = set(result.fired_names)
    assert "distinct_cards_per_ip_5m" in fired
    assert "distinct_cards_per_bin_5m" not in fired
    assert result.minimum_tier == Decision.CHALLENGE
