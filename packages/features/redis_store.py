"""
Source: TRD v2 §6.3, §6.4 -- the production `WindowStore` backend.
`record_and_read()` gives Day-1 rule callers a straightforward
ZADD-then-trim-then-ZCARD sequence; `score_path()` runs `windows.lua`
once via EVALSHA, which is the whole point of TRD §6.3's design: one
Redis round trip covers idempotency, every window, event_id-reuse,
the 24h card counter, and the CUSUM bucket in a single atomic call.

Day-3 Plan Step 4.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import redis as redis_lib

from packages.features.keys import window_key
from packages.features.store import (
    ScorePathRequest,
    ScorePathSnapshot,
    WindowRequest,
    WindowSnapshot,
)

DEFAULT_SCRIPT_PATH = Path(__file__).with_name("windows.lua")


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


class RedisWindowStore:
    def __init__(
        self,
        client: "redis_lib.Redis",
        *,
        script_path: Path = DEFAULT_SCRIPT_PATH,
        health_client: Optional["redis_lib.Redis"] = None,
        health_poll_interval_s: float = 2.0,
    ) -> None:
        self._client = client
        self._script_text = script_path.read_text(encoding="utf-8")
        # Source: Day-3 Plan Step 4 -- SCRIPT LOAD happens once, here, at
        # construction. A lazy first-call load would turn the steady-state
        # score path into two round trips instead of one.
        self._script_sha = self._client.script_load(self._script_text)

        # Source: Day-3 Plan Step 4 -- eviction detection runs on its own
        # connection so the health poll is never counted by the
        # one-round-trip-per-score-call assertion, which only wraps the
        # client instance passed in above.
        self._health_client = health_client or self._make_health_client(client)
        self._eviction_baseline: Optional[int] = None
        self._trusted = True
        self._degraded_reason: Optional[str] = None
        self._health_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._health_thread = threading.Thread(
            target=self._poll_eviction, args=(health_poll_interval_s,), daemon=True
        )
        self._health_thread.start()

    @staticmethod
    def _make_health_client(client: "redis_lib.Redis") -> "redis_lib.Redis":
        pool = client.connection_pool
        kwargs = dict(pool.connection_kwargs)
        return redis_lib.Redis(connection_pool=redis_lib.ConnectionPool(**kwargs))

    def _poll_eviction(self, interval_s: float) -> None:
        while not self._stop_event.wait(interval_s):
            try:
                stats = self._health_client.info("stats")
                evicted = int(stats.get("evicted_keys", 0))
            except Exception:  # noqa: BLE001 -- a transient probe failure is not a degrade signal
                continue
            with self._health_lock:
                if self._eviction_baseline is None:
                    self._eviction_baseline = evicted
                elif evicted > self._eviction_baseline:
                    # Source: Day-3 Plan Step 4 -- latched, not reset: once
                    # maxmemory eviction has happened, past window counts
                    # for this store may already have silently undercounted.
                    self._trusted = False
                    self._degraded_reason = "redis_eviction"

    def close(self) -> None:
        self._stop_event.set()
        self._health_thread.join(timeout=5)

    def record_and_read(self, request: WindowRequest) -> WindowSnapshot:
        key = window_key(
            request.merchant_id, request.space, request.key, request.metric, request.window_ms
        )
        floor = request.ingest_ms - request.window_ms
        pipe = self._client.pipeline(transaction=True)
        pipe.zadd(key, {request.member: request.ingest_ms})
        pipe.zremrangebyscore(key, "-inf", floor)
        pipe.pexpire(key, request.window_ms + 60_000)
        pipe.zcard(key)
        results = pipe.execute()
        return WindowSnapshot(count=int(results[-1]))

    def shed_incr(self, merchant_id: str, ip: str, now_ms: int, ttl_ms: int) -> int:
        """
        Source: Day-7 Plan §4 Step 3 -- `INCR tg:{m}:shed:{ip}` plus a
        `PEXPIRE` on the first increment (value == 1), so the shed counter
        cannot persist past its TTL. Key matches `MERCHANT_SCOPED_KEY_RE`.
        `now_ms` is unused here -- Redis applies the TTL against its own
        clock; the in-memory backend needs it because it has none.
        """
        key = f"tg:{merchant_id}:shed:{ip}"
        count = int(self._client.incr(key))
        if count == 1:
            self._client.pexpire(key, ttl_ms)
        return count

    def score_path(self, request: ScorePathRequest) -> ScorePathSnapshot:
        idem_key = f"tg:{request.merchant_id}:idem:{request.idem_digest}"
        eidr_key = f"tg:{request.merchant_id}:eidr:{request.event_id}"
        card24_key = f"tg:{request.merchant_id}:card24:{request.card_hash}"
        cusum_key = f"tg:{request.merchant_id}:cusum"
        window_keys = [
            window_key(win.merchant_id, win.space, win.key, win.metric, win.window_ms)
            for win in request.windows
        ]
        keys = [idem_key, eidr_key, card24_key, cusum_key, *window_keys]

        argv = [
            request.ingest_ms,
            request.attempt_uid,
            request.idem_ttl_ms,
            request.payload_digest,
            request.card24_ttl_ms,
            request.cusum_bucket_s,
            request.window_ttl_slack_ms,
            len(request.windows),
        ]
        for win in request.windows:
            argv.extend([win.member, win.window_ms, win.read])

        try:
            reply = self._client.evalsha(self._script_sha, len(keys), *keys, *argv)
        except redis_lib.exceptions.NoScriptError:
            self._script_sha = self._client.script_load(self._script_text)
            reply = self._client.evalsha(self._script_sha, len(keys), *keys, *argv)

        idempotent_replay = bool(int(reply[0]))
        stored_attempt_uid_raw = _decode(reply[1])
        stored_attempt_uid = stored_attempt_uid_raw or None
        event_id_reuse_count = int(reply[2])
        card_seen_24h = int(reply[3])
        cusum_bucket_index = int(reply[4])
        cusum_bucket_count = int(reply[5])

        counts = []
        members = []
        window_replies = reply[6:]
        for win, sub in zip(request.windows, window_replies):
            counts.append(int(sub[0]))
            if win.read == "members":
                members.append(tuple(_decode(m) for m in sub[1:]))
            else:
                members.append(None)

        with self._health_lock:
            trusted = self._trusted
            degraded_reason = self._degraded_reason

        return ScorePathSnapshot(
            idempotent_replay=idempotent_replay,
            stored_attempt_uid=stored_attempt_uid,
            counts=tuple(counts),
            members=tuple(members),
            event_id_reuse_count=event_id_reuse_count,
            card_seen_24h=card_seen_24h,
            cusum_bucket_index=cusum_bucket_index,
            cusum_bucket_count=cusum_bucket_count,
            trusted=trusted,
            degraded_reason=degraded_reason,
        )
