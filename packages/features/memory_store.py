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
"""

from __future__ import annotations

import threading
from typing import Dict

from packages.features.keys import window_key
from packages.features.store import WindowRequest, WindowSnapshot


class InMemoryWindowStore:
    def __init__(self) -> None:
        self._windows: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    def record_and_read(self, request: WindowRequest) -> WindowSnapshot:
        key = window_key(request.merchant_id, request.space, request.key, request.metric)
        with self._lock:
            window = self._windows.setdefault(key, {})
            window[request.member] = request.ingest_ms

            floor = request.ingest_ms - request.window_ms
            expired = [member for member, score in window.items() if score <= floor]
            for member in expired:
                del window[member]

            return WindowSnapshot(count=len(window))
