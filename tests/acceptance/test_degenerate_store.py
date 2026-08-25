"""
Source: Day-3 Plan Step 5 test list, item 6 -- "Degenerate-but-not-cold:
store idle four hours, windows empty, baseline exists -> no NaN, no
divide-by-zero, no 'cold start' misclassification." Tests both the
in-memory and Redis backends against ingest timestamps four hours apart
with no intervening traffic.
"""

from __future__ import annotations

import math
import os

import pytest

from packages.features.compute import FeatureContext, classify_ua, compute_features
from packages.features.memory_store import InMemoryWindowStore

MERCHANT_ID = "merchant_idle"
FOUR_HOURS_MS = 4 * 60 * 60 * 1000


def _idle_then_score(store):
    """One attempt at t=0 (to prove the store was previously initialized),
    then nothing until t=0+4h, then one attempt -- windows are empty by
    the time the second attempt is scored."""
    ctx0 = FeatureContext(
        merchant_id=MERCHANT_ID, attempt_uid="uid-0", ingest_ms=0,
        payload_digest="digest-0", event_id="evt-0", ip="8.8.8.8",
        ua_class=classify_ua("Mozilla/5.0"), card_hash="card-0", bin="999143",
        amount_minor=1000, session_id="s0",
    )
    compute_features(store, ctx0)

    ctx1 = FeatureContext(
        merchant_id=MERCHANT_ID, attempt_uid="uid-1", ingest_ms=FOUR_HOURS_MS,
        payload_digest="digest-1", event_id="evt-1", ip="8.8.8.8",
        ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999143",
        amount_minor=1000, session_id="s1",
    )
    return compute_features(store, ctx1)


def _assert_well_defined(fv):
    for name, value in fv.values.items():
        assert math.isfinite(value), f"{name} is not finite after idle period: {value}"
    # A store that has scored exactly one attempt after a long idle gap is
    # not "cold": there is no separate cold-start classification anywhere
    # in FeatureVector to accidentally trip -- the vector is simply the
    # honest values for a fresh 60s/5m/30m window (this attempt only).
    assert fv.values["attempts_per_ip_60s"] == 1.0
    assert fv.values["distinct_bins_per_ip_5m"] == 1.0


def test_memory_backend_idle_four_hours_then_score():
    store = InMemoryWindowStore()
    fv = _idle_then_score(store)
    _assert_well_defined(fv)


@pytest.mark.redis
def test_redis_backend_idle_four_hours_then_score():
    redis_lib = pytest.importorskip("redis")
    from packages.features.redis_store import RedisWindowStore

    url = os.environ.get("TOLLGATE_REDIS_URL", "redis://localhost:6379")
    try:
        client = redis_lib.Redis.from_url(url)
        client.ping()
        client.flushdb()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Redis unreachable at {url}")

    store = RedisWindowStore(client)
    fv = _idle_then_score(store)
    _assert_well_defined(fv)
    store.close()
