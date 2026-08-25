"""
Source: Day-3 Plan Step 5 test list, item 3 -- the boundary set. Event
exactly at t - window (excluded, stated convention, Impl Plan §1.1); two
events at identical timestamps; out-of-order arrival; event timestamped in
the future. Asserted against the in-memory backend, the Redis backend, and
the independent pandas oracle, so a boundary bug cannot hide in only one
of the three.
"""

from __future__ import annotations

import os

import pytest

from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import ScorePathRequest, WindowRequest
from tests.oracles.pandas_windows import window_counts

MERCHANT_ID = "merchant_bound"
WINDOW_MS = 60_000


def _score_path_request(ingest_ms, attempt_uid, member, window_ms=WINDOW_MS):
    return ScorePathRequest(
        merchant_id=MERCHANT_ID,
        ingest_ms=ingest_ms,
        idem_digest=f"idem-{attempt_uid}",
        payload_digest=f"payload-{attempt_uid}",
        attempt_uid=attempt_uid,
        idem_ttl_ms=86_400_000,
        event_id=f"evt-{attempt_uid}",
        card_hash="card-x",
        card24_ttl_ms=86_400_000,
        windows=(
            WindowRequest(
                merchant_id=MERCHANT_ID, space="ip", key="1.1.1.1", metric="ev",
                member=member, ingest_ms=ingest_ms, window_ms=window_ms,
            ),
        ),
        cusum_bucket_s=10,
        window_ttl_slack_ms=60_000,
    )


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


def _counts_via_store(store, ingest_times):
    counts = []
    for i, t in enumerate(ingest_times):
        req = _score_path_request(t, f"uid-{i}", f"uid-{i}")
        snap = store.score_path(req)
        counts.append(snap.counts[0])
    return counts


def _oracle_counts(ingest_times):
    events = [{"t_ms": t, "id": f"uid-{i}"} for i, t in enumerate(ingest_times)]
    return window_counts(
        events, key_fn=lambda e: "k", member_fn=lambda e: e["id"],
        time_fn=lambda e: e["t_ms"], window_ms=WINDOW_MS,
    )


class TestExactBoundaryExcluded:
    """First event at t=0, second event at exactly t=WINDOW_MS: the first
    must be excluded from the second's window (score == floor)."""

    def test_memory(self, memory_store):
        counts = _counts_via_store(memory_store, [0, WINDOW_MS])
        assert counts == [1, 1]

    @pytest.mark.redis
    def test_redis(self, redis_store):
        counts = _counts_via_store(redis_store, [0, WINDOW_MS])
        assert counts == [1, 1]

    def test_oracle_agrees(self):
        assert _oracle_counts([0, WINDOW_MS]) == [1, 1]

    def test_one_ms_inside_boundary_is_included(self, memory_store):
        counts = _counts_via_store(memory_store, [0, WINDOW_MS - 1])
        assert counts == [1, 2]


class TestIdenticalTimestamps:
    def test_memory(self, memory_store):
        counts = _counts_via_store(memory_store, [1000, 1000, 1000])
        assert counts == [1, 2, 3]

    @pytest.mark.redis
    def test_redis(self, redis_store):
        counts = _counts_via_store(redis_store, [1000, 1000, 1000])
        assert counts == [1, 2, 3]

    def test_oracle_agrees(self):
        assert _oracle_counts([1000, 1000, 1000]) == [1, 2, 3]


class TestOutOfOrderArrival:
    """Arrival order, not timestamp order, decides windowing (module
    docstring of tests/oracles/pandas_windows.py)."""

    def test_memory(self, memory_store):
        # Arrives: t=5000, then t=1000 (earlier timestamp, arrives second).
        counts = _counts_via_store(memory_store, [5000, 1000])
        assert counts == [1, 2]

    @pytest.mark.redis
    def test_redis(self, redis_store):
        counts = _counts_via_store(redis_store, [5000, 1000])
        assert counts == [1, 2]

    def test_oracle_agrees(self):
        assert _oracle_counts([5000, 1000]) == [1, 2]


class TestFutureTimestamp:
    """An event timestamped far in the future must not crash and must not
    produce NaN -- it is simply the newest member of its window."""

    def test_memory(self, memory_store):
        far_future = 10**15
        counts = _counts_via_store(memory_store, [0, far_future])
        assert counts == [1, 1]  # 0 is far outside far_future's 60s window

    @pytest.mark.redis
    def test_redis(self, redis_store):
        far_future = 10**15
        counts = _counts_via_store(redis_store, [0, far_future])
        assert counts == [1, 1]
