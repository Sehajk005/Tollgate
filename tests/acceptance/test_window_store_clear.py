"""
Source: remediation plan FIX-003 / §10 (AUDIT-001).

`ReplayDriver.reset()` has called `window_store.clear()` since Day 2, but the
method existed only on `InMemoryWindowStore` and was never on the `WindowStore`
protocol. In the DOCUMENTED configuration -- `TOLLGATE_REDIS_URL` set, which is
what `.env.example` ships and what the README tells the operator to run --
`RedisWindowStore` had no `clear`, so reset raised `AttributeError` on its FIRST
line and took the other five clears down with it. `POST /v1/replay/reset`
returned a bare HTTP 500, and Reset -- the single most-used control in the demo
-- had never once worked against Redis.

These tests pin the contract for BOTH backends, identically:

  * deletion is scoped to one merchant;
  * the count of removed keys is returned, so the reset route can report a real
    per-layer result instead of an opaque success;
  * UNRELATED data in the same logical Redis DB survives -- the fix must never
    become `FLUSHDB`;
  * clearing merchant A leaves merchant B intact;
  * clearing an empty store is 0, not an error.
"""

from __future__ import annotations

import os

import pytest

from packages.features.compute import FeatureContext, classify_ua, compute_features
from packages.features.keys import MERCHANT_SCOPED_KEY_RE
from packages.features.memory_store import InMemoryWindowStore

MERCHANT_A = "merchant_clear_a"
MERCHANT_B = "merchant_clear_b"


def _score(store, merchant_id: str, i: int, ingest_ms: int = 1_000_000) -> None:
    compute_features(
        store,
        FeatureContext(
            merchant_id=merchant_id,
            attempt_uid=f"uid-{merchant_id}-{i}",
            ingest_ms=ingest_ms + i,
            payload_digest=f"digest-{merchant_id}-{i}",
            event_id=f"evt-{merchant_id}-{i}",
            ip=f"198.51.100.{i % 250}",
            ua_class=classify_ua("Mozilla/5.0"),
            card_hash=f"card-{merchant_id}-{i}",
            bin="999143",
            amount_minor=1000 + i,
            session_id=f"s-{i}",
        ),
    )


@pytest.fixture
def memory_store():
    return InMemoryWindowStore()


@pytest.fixture
def redis_store():
    redis_lib = pytest.importorskip("redis")
    from packages.features.redis_store import RedisWindowStore

    url = os.environ.get("TOLLGATE_TEST_REDIS_URL", "redis://localhost:6379/9")
    try:
        client = redis_lib.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Redis unreachable at {url}")
    client.flushdb()
    store = RedisWindowStore(client)
    yield store, client
    store.close()
    client.flushdb()
    client.close()


class TestInMemoryClear:
    def test_clear_returns_the_number_of_keys_removed(self, memory_store):
        for i in range(5):
            _score(memory_store, MERCHANT_A, i)
        removed = memory_store.clear(MERCHANT_A)
        assert removed > 0
        assert sum(len(store) for store in memory_store._all_stores()) == 0

    def test_clear_is_scoped_to_one_merchant(self, memory_store):
        for i in range(5):
            _score(memory_store, MERCHANT_A, i)
            _score(memory_store, MERCHANT_B, i)
        memory_store.clear(MERCHANT_A)
        remaining = [k for store in memory_store._all_stores() for k in store]
        assert remaining, "clearing merchant A removed merchant B's state as well"
        assert all(k.startswith(f"tg:{MERCHANT_B}:") for k in remaining), remaining

    def test_every_owned_dict_is_covered(self, memory_store):
        """Appendix item 1 -- `_card24`, `_cusum` and `_shed` must be cleared,
        verified rather than assumed. Redis used to throw first, so this path
        had never been exercised end to end."""
        for i in range(3):
            _score(memory_store, MERCHANT_A, i)
        memory_store.shed_incr(MERCHANT_A, "198.51.100.7", now_ms=1_000_000, ttl_ms=60_000)
        for name in ("_windows", "_idem", "_eidr", "_card24", "_cusum", "_shed"):
            assert getattr(memory_store, name), f"{name} was never populated -- the test proves nothing"
        memory_store.clear(MERCHANT_A)
        for name in ("_windows", "_idem", "_eidr", "_card24", "_cusum", "_shed"):
            assert not getattr(memory_store, name), f"{name} survived clear()"

    def test_clear_on_an_empty_store_is_zero(self, memory_store):
        assert memory_store.clear(MERCHANT_A) == 0

    def test_clear_without_a_merchant_removes_everything(self, memory_store):
        for i in range(3):
            _score(memory_store, MERCHANT_A, i)
            _score(memory_store, MERCHANT_B, i)
        assert memory_store.clear() > 0
        assert sum(len(store) for store in memory_store._all_stores()) == 0

    def test_every_key_is_merchant_scoped(self, memory_store):
        for i in range(3):
            _score(memory_store, MERCHANT_A, i)
        memory_store.shed_incr(MERCHANT_A, "198.51.100.7", now_ms=1_000_000, ttl_ms=60_000)
        for store in memory_store._all_stores():
            for key in store:
                assert MERCHANT_SCOPED_KEY_RE.match(key), f"unscoped key: {key}"


@pytest.mark.redis
class TestRedisClear:
    def test_clear_returns_a_count_and_removes_owned_keys(self, redis_store):
        store, client = redis_store
        for i in range(5):
            _score(store, MERCHANT_A, i)
        assert client.keys(f"tg:{MERCHANT_A}:*"), "nothing was written -- the test proves nothing"
        removed = store.clear(MERCHANT_A)
        assert removed > 0
        assert client.keys(f"tg:{MERCHANT_A}:*") == []

    def test_unrelated_keys_in_the_same_logical_db_survive(self, redis_store):
        """The whole reason the fix is SCAN + UNLINK and not FLUSHDB."""
        store, client = redis_store
        client.set("unrelated:key", "please-do-not-delete-me")
        client.set("someone-elses-app:session:42", "also-not-ours")
        for i in range(3):
            _score(store, MERCHANT_A, i)
        store.clear(MERCHANT_A)
        assert client.get("unrelated:key") == b"please-do-not-delete-me"
        assert client.get("someone-elses-app:session:42") == b"also-not-ours"

    def test_clear_is_scoped_to_one_merchant(self, redis_store):
        store, client = redis_store
        for i in range(3):
            _score(store, MERCHANT_A, i)
            _score(store, MERCHANT_B, i)
        store.clear(MERCHANT_A)
        assert client.keys(f"tg:{MERCHANT_A}:*") == []
        assert client.keys(f"tg:{MERCHANT_B}:*"), "merchant B's keys were removed too"

    def test_clear_on_an_empty_store_is_zero(self, redis_store):
        store, _client = redis_store
        assert store.clear(MERCHANT_A) == 0

    def test_the_shed_counter_is_cleared_too(self, redis_store):
        store, client = redis_store
        store.shed_incr(MERCHANT_A, "198.51.100.7", now_ms=1_000_000, ttl_ms=60_000)
        assert client.exists(f"tg:{MERCHANT_A}:shed:198.51.100.7") == 1
        store.clear(MERCHANT_A)
        assert client.exists(f"tg:{MERCHANT_A}:shed:198.51.100.7") == 0
