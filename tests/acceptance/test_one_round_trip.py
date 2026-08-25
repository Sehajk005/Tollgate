"""
Source: TRD v2 §6.3 -- "One round trip, so the latency budget survives."
Day-3 Plan Step 5 test list, item 4. A `CountingRedis` proxy wraps the
real client passed into `RedisWindowStore` and counts every command
issued through it; `SCRIPT LOAD` happens once at construction (Day-3 Plan
Step 4) and the eviction health poll runs on its own, separately-created
connection (RedisWindowStore._make_health_client), so neither is counted
here -- this test isolates exactly the steady-state score path.
"""

from __future__ import annotations

import os

import pytest

redis_lib = pytest.importorskip("redis")

from packages.features.compute import FeatureContext, classify_ua, compute_features  # noqa: E402

MERCHANT_ID = "merchant_rt"


class CountingRedis:
    """
    Wraps a real redis.Redis client; counts every execute_command call.

    `evalsha` must be defined explicitly: redis-py's own `evalsha()`
    resolves via `__getattr__` to a method already bound to `self._real`,
    so it would call `self._real.execute_command(...)` directly and never
    touch this wrapper's counted override.
    """

    def __init__(self, real_client):
        self._real = real_client
        self.command_count = 0

    def execute_command(self, *args, **kwargs):
        self.command_count += 1
        return self._real.execute_command(*args, **kwargs)

    def evalsha(self, sha, numkeys, *keys_and_args):
        return self.execute_command("EVALSHA", sha, numkeys, *keys_and_args)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def counting_redis():
    url = os.environ.get("TOLLGATE_REDIS_URL", "redis://localhost:6379")
    try:
        real_client = redis_lib.Redis.from_url(url)
        real_client.ping()
        real_client.flushdb()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Redis unreachable at {url}")
    return real_client


@pytest.mark.redis
def test_one_score_call_issues_exactly_one_redis_command(counting_redis):
    from packages.features.redis_store import RedisWindowStore

    # SCRIPT LOAD happens here, at construction -- before counting starts.
    store = RedisWindowStore(counting_redis)

    counter = CountingRedis(counting_redis)
    # Swap the store's client for the counting proxy AFTER construction,
    # so only the steady-state score path is measured, matching Day-3
    # Plan Step 4: "A lazy first-call load would turn the steady-state
    # score path into two round trips instead of one" -- this test proves
    # the opposite already happened.
    store._client = counter

    ctx = FeatureContext(
        merchant_id=MERCHANT_ID, attempt_uid="uid-1", ingest_ms=1_000_000,
        payload_digest="digest-1", event_id="evt-1", ip="9.9.9.9",
        ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999143",
        amount_minor=1000, session_id="s1",
    )
    compute_features(store, ctx)

    assert counter.command_count == 1, (
        f"expected exactly one Redis round trip, got {counter.command_count}"
    )

    store.close()
