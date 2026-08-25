"""
Source: TRD v2 / Day-3 Plan Step 5 test list, item 5 -- "Redis eviction
under maxmemory is distinguished from TTL expiry -- eviction must degrade
to rules-only, not to silently-wrong counts." Runs against `redis-small`
(docker-compose.yml: maxmemory 2mb, allkeys-lru), which exists solely for
this test and is never used by the application.
"""

from __future__ import annotations

import math
import os
import time

import pytest

redis_lib = pytest.importorskip("redis")

from packages.features.compute import FeatureContext, classify_ua, compute_features  # noqa: E402
from packages.features.redis_store import RedisWindowStore  # noqa: E402
from packages.features.store import ScorePathRequest, WindowRequest  # noqa: E402

SMALL_REDIS_URL = os.environ.get("TOLLGATE_REDIS_SMALL_URL", "redis://localhost:6380")


@pytest.fixture
def small_redis_client():
    try:
        client = redis_lib.Redis.from_url(SMALL_REDIS_URL)
        client.ping()
        client.flushall()
    except Exception:  # noqa: BLE001
        pytest.skip(f"redis-small unreachable at {SMALL_REDIS_URL}")
    return client


@pytest.mark.redis
def test_maxmemory_eviction_latches_untrusted(small_redis_client):
    store = RedisWindowStore(small_redis_client, health_poll_interval_s=0.3)
    time.sleep(0.6)  # let the poller establish its baseline

    for i in range(20000):
        ctx = FeatureContext(
            merchant_id="m_evict", attempt_uid=f"uid-{i}", ingest_ms=1_000_000 + i,
            payload_digest=f"digest-{i}", event_id=f"evt-{i}", ip=f"1.1.1.{i % 50}",
            ua_class=classify_ua("Mozilla/5.0"), card_hash=f"card-{i % 500}",
            bin="999143", amount_minor=1000, session_id=f"s-{i % 50}",
        )
        compute_features(store, ctx)

    time.sleep(1.0)  # let the poller notice the evicted_keys rise

    ctx = FeatureContext(
        merchant_id="m_evict", attempt_uid="uid-final", ingest_ms=2_000_000,
        payload_digest="digest-final", event_id="evt-final", ip="1.1.1.1",
        ua_class=classify_ua("Mozilla/5.0"), card_hash="card-final",
        bin="999143", amount_minor=1000, session_id="s-final",
    )
    fv = compute_features(store, ctx)

    assert fv.trusted is False
    assert fv.degraded_reason == "redis_eviction"
    # Degraded, not NaN/crashed: rules still evaluate on whatever the
    # (possibly undercounted) windows say.
    for name, value in fv.values.items():
        assert math.isfinite(value), f"{name} is not finite under degrade: {value}"

    store.close()


@pytest.mark.redis
def test_plain_ttl_expiry_does_not_trip_the_eviction_latch(small_redis_client):
    store = RedisWindowStore(small_redis_client, health_poll_interval_s=0.3)
    time.sleep(0.6)

    req = ScorePathRequest(
        merchant_id="m_ttl", ingest_ms=1_000_000, idem_digest="idem-ttl",
        payload_digest="digest-ttl", attempt_uid="uid-ttl", idem_ttl_ms=500,
        event_id="evt-ttl", card_hash="card-ttl", card24_ttl_ms=86_400_000,
        windows=(
            WindowRequest(
                merchant_id="m_ttl", space="ip", key="2.2.2.2", metric="ev",
                member="uid-ttl", ingest_ms=1_000_000, window_ms=60_000,
            ),
        ),
        cusum_bucket_s=10, window_ttl_slack_ms=60_000,
    )
    store.score_path(req)
    time.sleep(1.0)  # let the idem key's short TTL lapse naturally
    time.sleep(0.6)  # let the poller run at least once more

    assert store._trusted is True
    assert store._degraded_reason is None

    store.close()
