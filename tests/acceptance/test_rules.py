"""
Source: Implementation Plan v2.1 Day 1 -- R1/R2/R3 threshold behavior
(decisions.md, decision 1).
"""

from __future__ import annotations

from packages.contracts.decision import Decision
from packages.detect.rules import DayOneRules, RuleInput
from packages.features.memory_store import InMemoryWindowStore


def _fire_r1(count: int) -> Decision:
    # Isolate R1: card_hash and bin are held CONSTANT across every attempt so
    # R2 (distinct cards per IP) and R3 (distinct cards per BIN) never
    # accumulate past 1 -- only attempt volume (R1's signal) varies.
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = None
    for i in range(count):
        result = rules.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=f"attempt-{i}", ingest_ms=1000,
            ip="9.9.9.9", card_hash="card-constant", bin="bin-constant",
        ))
    return result.minimum_tier


class TestR1Velocity:
    # Source: Impl Plan Day 1 -- "R1: 19 qualifying attempts within 60s -> no
    # fire; 20 -> fire, minimum throttle"
    def test_19_attempts_does_not_fire(self):
        assert _fire_r1(19) == Decision.ALLOW

    def test_20_attempts_fires_minimum_throttle(self):
        assert _fire_r1(20) == Decision.THROTTLE


def _fire_r2(distinct_cards: int) -> Decision:
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = None
    for i in range(distinct_cards):
        result = rules.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=f"attempt-{i}", ingest_ms=1000,
            ip="9.9.9.9", card_hash=f"card-{i}", bin="411111",
        ))
    return result.minimum_tier


class TestR2CardFanOut:
    # Source: Impl Plan Day 1 -- "R2: 14 distinct cards from one IP within 5m
    # -> no fire; 15 -> fire, minimum challenge"
    def test_14_distinct_cards_does_not_fire(self):
        assert _fire_r2(14) == Decision.ALLOW

    def test_15_distinct_cards_fires_minimum_challenge(self):
        assert _fire_r2(15) == Decision.CHALLENGE


def _fire_r3(distinct_cards: int) -> Decision:
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = None
    for i in range(distinct_cards):
        result = rules.evaluate(RuleInput(
            merchant_id="m1", attempt_uid=f"attempt-{i}", ingest_ms=1000,
            ip=f"9.9.9.{i % 250}", card_hash=f"card-{i}", bin="411111",
        ))
    return result.minimum_tier


class TestR3BinConcentration:
    # Source: Impl Plan Day 1 -- "R3: 19 distinct cards within one BIN over
    # 5m -> no fire; 20 -> fire, minimum challenge"
    def test_19_distinct_cards_in_one_bin_does_not_fire(self):
        assert _fire_r3(19) == Decision.ALLOW

    def test_20_distinct_cards_in_one_bin_fires_minimum_challenge(self):
        assert _fire_r3(20) == Decision.CHALLENGE


def test_no_rule_fires_baseline_is_allow():
    store = InMemoryWindowStore()
    rules = DayOneRules(store)
    result = rules.evaluate(RuleInput(
        merchant_id="m1", attempt_uid="attempt-lonely", ingest_ms=1000,
        ip="1.1.1.1", card_hash="card-lonely", bin="555555",
    ))
    assert result.minimum_tier == Decision.ALLOW
    assert result.fired_names == []
