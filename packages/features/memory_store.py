"""
Day 1 WindowStore backend.

Source: TRD v2 §6.1 -- sorted-set semantics: ZADD-then-trim-then-ZCARD.
Implemented here as a plain dict of {member: last_seen_ingest_ms} per window
key, mirroring Redis exactly: re-adding a member updates its score rather
than incrementing a counter, so cardinality after trimming is the correct
sliding "distinct entities active in window" statistic -- and when `member`
is unique per event (the `ev` metric), that same cardinality is simply the
event count. One operation, one meaning, both statistics (R1 uses `ev`;
R2/R3 use `card`).

Windows are half-open (t - window, t]: an entry whose score equals exactly
t - window is excluded (Impl Plan §1.1's stated convention). Features are
inclusive of the current attempt (TRD §6.3): the member being recorded is
added, THEN the window is trimmed and counted, so the Nth attempt that meets
a threshold is the one that fires it.

Day-3 Plan Step 2 -- `score_path()` adds the one-round-trip batched
operation TRD §6.3 specifies for the real feature path: idempotency check,
every window in one pass, event_id-reuse tracking, the 24h card counter, and
the CUSUM bucket counter, all under the single existing lock so it is one
atomic logical operation, exactly mirroring what `windows.lua` does for
Redis. This is also the pre-committed Day-3 fallback backend, so it is a
real implementation, not a stub. `trusted` is always True here: nothing in
an in-memory dict evicts under memory pressure the way Redis maxmemory can.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

from packages.features.keys import window_key
from packages.features.store import (
    ScorePathRequest,
    ScorePathSnapshot,
    WindowRequest,
    WindowSnapshot,
)


class InMemoryWindowStore:
    def __init__(self) -> None:
        self._windows: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()
        # score_path()-only state -- Day-3 Plan Step 2.
        self._idem: Dict[str, Tuple[str, int]] = {}  # digest -> (attempt_uid, expire_at_ms)
        self._eidr: Dict[str, set] = {}  # event_id -> {payload_digest, ...}
        self._card24: Dict[str, Tuple[int, int]] = {}  # card_hash -> (count, expire_at_ms)
        self._cusum: Dict[str, Tuple[int, int]] = {}  # merchant_id -> (bucket_index, count)

    def record_and_read(self, request: WindowRequest) -> WindowSnapshot:
        key = window_key(
            request.merchant_id, request.space, request.key, request.metric, request.window_ms
        )
        with self._lock:
            window = self._windows.setdefault(key, {})
            window[request.member] = request.ingest_ms

            floor = request.ingest_ms - request.window_ms
            expired = [member for member, score in window.items() if score <= floor]
            for member in expired:
                del window[member]

            return WindowSnapshot(count=len(window))

    def score_path(self, request: ScorePathRequest) -> ScorePathSnapshot:
        with self._lock:
            existing = self._idem.get(request.idem_digest)
            if existing is not None and existing[1] > request.ingest_ms:
                # Source: TRD §6.3 step 1 -- SET NX found the key already
                # set: this is a replay. Return immediately without
                # touching any window, eidr set, card24 counter, or the
                # CUSUM bucket (Impl Plan §1.6 M7 -- idempotency).
                return ScorePathSnapshot(
                    idempotent_replay=True,
                    stored_attempt_uid=existing[0],
                    counts=tuple(0 for _ in request.windows),
                    members=tuple(None for _ in request.windows),
                    event_id_reuse_count=0,
                    card_seen_24h=0,
                    cusum_bucket_index=0,
                    cusum_bucket_count=0,
                    trusted=True,
                    degraded_reason=None,
                )

            self._idem[request.idem_digest] = (
                request.attempt_uid,
                request.ingest_ms + request.idem_ttl_ms,
            )

            counts = []
            members = []
            for win_req in request.windows:
                key = window_key(
                    win_req.merchant_id, win_req.space, win_req.key, win_req.metric, win_req.window_ms
                )
                window = self._windows.setdefault(key, {})
                window[win_req.member] = win_req.ingest_ms

                floor = win_req.ingest_ms - win_req.window_ms
                expired = [member for member, score in window.items() if score <= floor]
                for member in expired:
                    del window[member]

                counts.append(len(window))
                if win_req.read == "members":
                    members.append(tuple(window.keys()))
                else:
                    members.append(None)

            eidr_set = self._eidr.setdefault(request.event_id, set())
            eidr_set.add(request.payload_digest)
            event_id_reuse_count = len(eidr_set)

            card_state = self._card24.get(request.card_hash)
            if card_state is None or card_state[1] <= request.ingest_ms:
                card_count = 1
            else:
                card_count = card_state[0] + 1
            self._card24[request.card_hash] = (
                card_count,
                request.ingest_ms + request.card24_ttl_ms,
            )

            bucket_index = request.ingest_ms // (request.cusum_bucket_s * 1000)
            cusum_state = self._cusum.get(request.merchant_id)
            if cusum_state is None or cusum_state[0] != bucket_index:
                bucket_count = 1
            else:
                bucket_count = cusum_state[1] + 1
            self._cusum[request.merchant_id] = (bucket_index, bucket_count)

            return ScorePathSnapshot(
                idempotent_replay=False,
                stored_attempt_uid=None,
                counts=tuple(counts),
                members=tuple(members),
                event_id_reuse_count=event_id_reuse_count,
                card_seen_24h=card_count,
                cusum_bucket_index=bucket_index,
                cusum_bucket_count=bucket_count,
                trusted=True,
                degraded_reason=None,
            )

    def clear(self) -> None:
        """
        Source: Day-2 Plan Decision 36 -- Reset is required, not convenient:
        VirtualClock cannot move backwards and windows accumulate, so
        without this the demo (services/scorer/replay.py) runs once per
        process. Not exercised by any Day-1 code path.
        """
        with self._lock:
            self._windows.clear()
            self._idem.clear()
            self._eidr.clear()
            self._card24.clear()
            self._cusum.clear()
