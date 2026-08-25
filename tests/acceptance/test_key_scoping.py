"""
Source: TRD v2 §6.1 -- "Every key is merchant-scoped... A test asserts
every key produced by the store matches ^tg:[^:]+:." Day-3 Plan Step 5
test list, item 7 ("fixes F16" -- Backend Schema §4). For Redis, keys are
collected by scanning the keyspace after the run (`client.keys("*")`),
not from the Python key builder alone, so this covers keys the Lua script
itself produces (idem, eidr, card24, cusum, every window), not only
Python-side WindowRequest keys.
"""

from __future__ import annotations

import os

import pytest

redis_lib = pytest.importorskip("redis")

from packages.features.compute import FeatureContext, classify_ua, compute_features  # noqa: E402
from packages.features.keys import MERCHANT_SCOPED_KEY_RE  # noqa: E402
from packages.features.memory_store import InMemoryWindowStore  # noqa: E402
from packages.features.redis_store import RedisWindowStore  # noqa: E402

MERCHANT_ID = "merchant_scope"


def _run_one_attempt(store):
    ctx = FeatureContext(
        merchant_id=MERCHANT_ID, attempt_uid="uid-1", ingest_ms=1_000_000,
        payload_digest="digest-1", event_id="evt-1", ip="7.7.7.7",
        ua_class=classify_ua("Mozilla/5.0"), card_hash="card-1", bin="999143",
        amount_minor=1000, session_id="s1",
    )
    compute_features(store, ctx)


def test_memory_backend_keys_are_merchant_scoped():
    store = InMemoryWindowStore()
    _run_one_attempt(store)
    assert store._windows, "expected at least one window key to have been created"
    for key in store._windows:
        assert MERCHANT_SCOPED_KEY_RE.match(key), f"unscoped key: {key}"


@pytest.mark.redis
def test_redis_backend_keys_are_merchant_scoped():
    url = os.environ.get("TOLLGATE_REDIS_URL", "redis://localhost:6379")
    try:
        client = redis_lib.Redis.from_url(url)
        client.ping()
        client.flushdb()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Redis unreachable at {url}")

    store = RedisWindowStore(client)
    _run_one_attempt(store)

    all_keys = [k.decode("utf-8") if isinstance(k, bytes) else k for k in client.keys("*")]
    assert all_keys, "expected the score path to have created at least one Redis key"
    for key in all_keys:
        assert MERCHANT_SCOPED_KEY_RE.match(key), f"unscoped key: {key}"

    store.close()
