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

from packages.features.keys import (
    card24_key,
    cusum_key,
    eidr_key,
    idem_key,
    merchant_prefix,
    shed_key,
    window_key,
)
from packages.features.store import (
    ScorePathRequest,
    ScorePathSnapshot,
    WindowRequest,
    WindowSnapshot,
)


class InMemoryWindowStore:
    # Source: remediation plan FIX-003 -- every dict below is keyed with the
    # SAME merchant-scoped strings the Redis backend uses (packages/features/
    # keys.py). Before that, `_idem` / `_eidr` / `_card24` were keyed on a bare
    # digest / event_id / card_hash with no merchant in them, so the two
    # backends of one protocol had two different key spaces: `clear(merchant)`
    # could not be honest here, and two merchants sharing a card hash silently
    # shared a 24-hour counter. Values and semantics are unchanged.
    def __init__(self) -> None:
        self._windows: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()
        # score_path()-only state -- Day-3 Plan Step 2.
        self._idem: Dict[str, Tuple[str, int]] = {}  # tg:{m}:idem:{ns}{digest} -> (uid, expire_at_ms)
        self._eidr: Dict[str, set] = {}  # tg:{m}:eidr:{event_id} -> {payload_digest, ...}
        self._card24: Dict[str, Tuple[int, int]] = {}  # tg:{m}:card24:{hash} -> (count, expire_at_ms)
        self._cusum: Dict[str, Tuple[int, int]] = {}  # tg:{m}:cusum -> (bucket_index, count)
        # Day-7 Plan §4 Step 3 -- shed counter: tg:{m}:shed:{ip} -> (count, expire_at_ms).
        self._shed: Dict[str, Tuple[int, int]] = {}

    def _all_stores(self):
        """Every dict this backend owns. One list, so `clear()` cannot fall out
        of step with `__init__` the way it silently could before."""
        return (self._windows, self._idem, self._eidr, self._card24, self._cusum, self._shed)

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
        ikey = idem_key(request.merchant_id, request.idem_digest, request.idem_namespace)
        with self._lock:
            existing = self._idem.get(ikey)
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

            self._idem[ikey] = (
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

            ekey = eidr_key(request.merchant_id, request.event_id)
            eidr_set = self._eidr.setdefault(ekey, set())
            eidr_set.add(request.payload_digest)
            event_id_reuse_count = len(eidr_set)

            ckey = card24_key(request.merchant_id, request.card_hash)
            card_state = self._card24.get(ckey)
            if card_state is None or card_state[1] <= request.ingest_ms:
                card_count = 1
            else:
                card_count = card_state[0] + 1
            self._card24[ckey] = (
                card_count,
                request.ingest_ms + request.card24_ttl_ms,
            )

            bucket_index = request.ingest_ms // (request.cusum_bucket_s * 1000)
            bkey = cusum_key(request.merchant_id)
            cusum_state = self._cusum.get(bkey)
            if cusum_state is None or cusum_state[0] != bucket_index:
                bucket_count = 1
            else:
                bucket_count = cusum_state[1] + 1
            self._cusum[bkey] = (bucket_index, bucket_count)

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

    def shed_incr(self, merchant_id: str, ip: str, now_ms: int, ttl_ms: int) -> int:
        """
        Source: Day-7 Plan §4 Step 3 -- the merchant-scoped shed counter
        `tg:{m}:shed:{ip}`, mirroring the Redis backend's INCR + PEXPIRE.
        Expires `ttl_ms` after the FIRST increment (like Redis SET ... PX on
        the first INCR), driven by the injected `now_ms` -- no wall clock.
        """
        key = shed_key(merchant_id, ip)
        with self._lock:
            state = self._shed.get(key)
            if state is None or state[1] <= now_ms:
                count = 1
                expire_at = now_ms + ttl_ms
            else:
                count = state[0] + 1
                expire_at = state[1]
            self._shed[key] = (count, expire_at)
            return count

    def clear(self, merchant_id: Optional[str] = None) -> int:
        """
        Source: Day-2 Plan Decision 36 -- Reset is required, not convenient:
        VirtualClock cannot move backwards and windows accumulate, so without
        this the demo (services/scorer/replay.py) runs once per process.

        Remediation plan FIX-003: `merchant_id` scopes the deletion so this
        backend matches `RedisWindowStore.clear()` exactly, and the return value
        is the number of keys removed so `POST /v1/replay/reset` can report a
        real per-layer `cleared` map instead of an opaque success.

        `merchant_id=None` clears everything this store owns (the previous
        behaviour, which both existing callers rely on). Every dict in
        `_all_stores()` is covered -- `_windows`, `_idem`, `_eidr`, `_card24`,
        `_cusum` and `_shed` -- so a future field cannot be added to `__init__`
        and silently survive a Reset.
        """
        with self._lock:
            if merchant_id is None:
                removed = sum(len(store) for store in self._all_stores())
                for store in self._all_stores():
                    store.clear()
                return removed

            prefix = merchant_prefix(merchant_id)
            removed = 0
            for store in self._all_stores():
                doomed = [key for key in store if key.startswith(prefix)]
                for key in doomed:
                    del store[key]
                removed += len(doomed)
            return removed
