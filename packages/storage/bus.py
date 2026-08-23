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
from typing import AsyncIterator, Dict, List, Protocol


class EventBus(Protocol):
    async def publish(self, event: Dict) -> None: ...
    def subscribe(self) -> AsyncIterator[Dict]: ...


class InProcessEventBus:
    def __init__(self) -> None:
        self._subscribers: List["asyncio.Queue"] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: Dict) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            await queue.put(event)

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
