"""
Source: v2.1 reconciliation, finding K9 -- Backend Schema section 5 maps SSE
/v1/stream to Redis pub/sub, but Redis is Day 3. This EventBus protocol with
an in-process asyncio backend mirrors the WindowStore two-backend pattern
(TRD section 11 decision #1): Day 3 swaps the backend, not the callers.

Consequence: Day 1 runs one uvicorn worker. Multi-worker fan-out is what
Redis pub/sub exists for.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import AsyncIterator, Deque, Dict, List, Optional, Protocol

# Source: Day-8 Plan Step 2 (G5) -- a bounded recent-event buffer so a dropped
# SSE connection can catch up via GET /v1/stream/recent?after=<attempt_uid>
# rather than losing every event between the drop and the reconnect.
RECENT_BUFFER_MAXLEN = 200


class EventBus(Protocol):
    async def publish(self, event: Dict) -> None: ...
    def subscribe(self) -> AsyncIterator[Dict]: ...
    def recent(self, after: Optional[str] = None) -> List[Dict]: ...


class InProcessEventBus:
    def __init__(self) -> None:
        self._subscribers: List["asyncio.Queue"] = []
        self._lock = asyncio.Lock()
        # Day-8 Plan Step 2 -- bounded FIFO of the last N published events, for
        # the polling fallback. Trimmed automatically by deque(maxlen=...).
        self._recent: Deque[Dict] = deque(maxlen=RECENT_BUFFER_MAXLEN)

    async def publish(self, event: Dict) -> None:
        async with self._lock:
            self._recent.append(event)
            subscribers = list(self._subscribers)
        for queue in subscribers:
            await queue.put(event)

    def recent(self, after: Optional[str] = None) -> List[Dict]:
        """Source: Day-8 Plan Step 2 -- events published after the one whose
        `attempt_uid` == `after`, in publication order. `after=None` returns the
        whole (bounded) buffer; an `after` that has already rotated out of the
        buffer also returns the whole buffer (best-effort catch-up for a long
        disconnect), never an error."""
        events = list(self._recent)
        if after is None:
            return events
        for i, event in enumerate(events):
            if event.get("attempt_uid") == after:
                return events[i + 1:]
        return events

    async def subscribe(self) -> AsyncIterator[Dict]:
        queue: "asyncio.Queue" = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)
