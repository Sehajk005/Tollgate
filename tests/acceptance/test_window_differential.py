"""
Source: Day-3 Plan Step 5 / TRD §6.4 -- primary Day-3 exit gate. Replays
all 821 golden events through the production window path
(compute_features over a real WindowStore backend) and asserts every raw
window statistic equals the independent tests/oracles/pandas_windows.py
brute-force oracle, event by event, for every (space, metric, window)
compute.py actually queries.

Parametrised over both backends (Impl Plan Day-3 §Deliverables: "Redis and
InMemoryWindowStore implement the same WindowStore protocol"), so this one
test also verifies the pre-committed 20:00 fallback: if Redis cannot pass,
InMemoryWindowStore already does, under the identical assertions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from packages.features.compute import FeatureContext, classify_ua, compute_features, ipua_key
from packages.features.memory_store import InMemoryWindowStore
from tests.oracles.pandas_windows import window_counts

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "tests" / "fixtures" / "golden.jsonl"
MERCHANT_ID = "merchant_diff"
EPOCH_MS = 0  # Source: ReplayDriver -- vclock.set_ms(epoch_ms + ev.t_ms)


def _load_golden():
    events = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            events.append(json.loads(line))
    return events


@pytest.fixture
def redis_store():
    try:
        import redis as redis_lib

        from packages.features.redis_store import RedisWindowStore
    except Exception:  # noqa: BLE001
        pytest.skip("redis package not installed")

    url = os.environ.get("TOLLGATE_REDIS_URL", "redis://localhost:6379")
    try:
        client = redis_lib.Redis.from_url(url)
        client.ping()
        client.flushdb()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Redis unreachable at {url}")
    store = RedisWindowStore(client)
    yield store
    store.close()


@pytest.fixture
def memory_store():
    return InMemoryWindowStore()


def _run_production_path(store, events):
    """
    Replays golden events through the real compute_features() -- the exact
    function services/scorer/scoring.py calls -- and returns, per event,
    the raw counts this test cross-checks against the oracle.
    """
    per_event = []
    for ev in events:
        ua_class = classify_ua("")
        ctx = FeatureContext(
            merchant_id=MERCHANT_ID,
            attempt_uid=ev["event_id"],
            ingest_ms=EPOCH_MS + ev["t_ms"],
            payload_digest=f"digest-{ev['event_id']}",
            event_id=ev["event_id"],
            ip=ev["ip"],
            ua_class=ua_class,
            card_hash=ev["card_hash"],
            bin=ev["bin"],
            amount_minor=ev["amount_minor"],
            session_id=ev["session_id"],
        )
        fv = compute_features(store, ctx)
        per_event.append(
            {
                "attempts_per_ip_60s": fv.values["attempts_per_ip_60s"],
                "attempts_per_ip_5m": fv.values["attempts_per_ip_5m"],
                "attempts_per_ipua_5m": fv.values["attempts_per_ipua_5m"],
                "distinct_cards_per_ip_5m": fv.distinct_cards_per_ip_5m_raw,
                "distinct_bins_per_ip_5m": fv.values["distinct_bins_per_ip_5m"],
                "distinct_ips_per_bin_5m": fv.values["distinct_ips_per_bin_5m"],
                "distinct_cards_per_bin_5m": fv.values["distinct_cards_per_bin_5m"],
                "distinct_amounts_per_ip_5m": fv.values["distinct_amounts_per_ip_5m"],
            }
        )
    return per_event


def _oracle_series(events):
    ua_class = classify_ua("")
    enriched = [
        {**ev, "ipua": ipua_key(ev["ip"], ua_class)}
        for ev in events
    ]
    t_fn = lambda e: EPOCH_MS + e["t_ms"]  # noqa: E731

    return {
        "attempts_per_ip_60s": window_counts(
            enriched, key_fn=lambda e: e["ip"], member_fn=lambda e: e["event_id"],
            time_fn=t_fn, window_ms=60_000,
        ),
        "attempts_per_ip_5m": window_counts(
            enriched, key_fn=lambda e: e["ip"], member_fn=lambda e: e["event_id"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "attempts_per_ipua_5m": window_counts(
            enriched, key_fn=lambda e: e["ipua"], member_fn=lambda e: e["event_id"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "distinct_cards_per_ip_5m": window_counts(
            enriched, key_fn=lambda e: e["ip"], member_fn=lambda e: e["card_hash"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "distinct_bins_per_ip_5m": window_counts(
            enriched, key_fn=lambda e: e["ip"], member_fn=lambda e: e["bin"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "distinct_ips_per_bin_5m": window_counts(
            enriched, key_fn=lambda e: e["bin"], member_fn=lambda e: e["ip"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "distinct_cards_per_bin_5m": window_counts(
            enriched, key_fn=lambda e: e["bin"], member_fn=lambda e: e["card_hash"],
            time_fn=t_fn, window_ms=300_000,
        ),
        "distinct_amounts_per_ip_5m": window_counts(
            enriched, key_fn=lambda e: e["ip"], member_fn=lambda e: str(e["amount_minor"]),
            time_fn=t_fn, window_ms=300_000,
        ),
    }


def _assert_matches_oracle(per_event, oracle):
    events = _load_golden()
    for feature_name, oracle_series in oracle.items():
        for i in range(len(events)):
            actual = per_event[i][feature_name]
            expected = oracle_series[i]
            assert actual == expected, (
                f"{feature_name} mismatch at event index {i} "
                f"(event_id={events[i]['event_id']}): "
                f"production={actual} oracle={expected}"
            )


class TestWindowDifferentialMemory:
    def test_memory_backend_matches_pandas_oracle(self, memory_store):
        events = _load_golden()
        per_event = _run_production_path(memory_store, events)
        oracle = _oracle_series(events)
        _assert_matches_oracle(per_event, oracle)


@pytest.mark.redis
class TestWindowDifferentialRedis:
    def test_redis_backend_matches_pandas_oracle(self, redis_store):
        events = _load_golden()
        per_event = _run_production_path(redis_store, events)
        oracle = _oracle_series(events)
        _assert_matches_oracle(per_event, oracle)
