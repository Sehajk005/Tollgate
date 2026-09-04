"""
Source: Implementation Plan v2.1 Day 1 -- GET /v1/stream (SSE). Backend
today is InProcessEventBus (packages/storage/bus.py); Redis pub/sub replaces
it on Day 3 without touching this route.

Day-8 Plan Step 2 -- GET /v1/stream/recent?after=<attempt_uid> is the polling
fallback the dashboard's `useEventStream` hook hits when the SSE connection
drops. It returns the bounded recent-event buffer (bus.recent()), the exact
events `/v1/stream` publishes, in order. Decision 94: it ships with the SAME
auth posture as `/v1/stream` (loopback-bound, unauthenticated) -- it discloses
nothing `/v1/stream` does not already, and no Day-8 gate needs auth here.

Remediation plan FIX-008 (AUDIT-020) -- HEADERS FLUSH ON SUBSCRIBE. The stream
used to yield nothing until an event was published, so on an idle dashboard the
browser's `EventSource.onopen` never fired and the connection chip read
`reconnecting` while the system was perfectly healthy: the one indicator whose
whole job is to tell the operator whether to trust the screen was lying. A
comment line is emitted immediately, which flushes the response headers, plus a
15 s keepalive so an idle connection is not reaped by an intermediary.

Comment lines (`: text`) are part of the SSE grammar and are ignored by every
conforming client, so no consumer sees them as data.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from services.scorer.deps import ScorerState, get_scorer_state

router = APIRouter()

KEEPALIVE_INTERVAL_S = 15.0


async def _event_stream(state: ScorerState):
    # Emitted BEFORE the first `await` on the subscriber, so the response
    # headers reach the browser immediately and `onopen` fires on an idle
    # system. This is the whole of the AUDIT-020 fix.
    yield ": ping\n\n"

    subscriber = state.event_bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    subscriber.__anext__(), timeout=KEEPALIVE_INTERVAL_S
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            except StopAsyncIteration:
                return
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        aclose = getattr(subscriber, "aclose", None)
        if aclose is not None:
            await aclose()


@router.get("/v1/stream")
async def stream(state: ScorerState = Depends(get_scorer_state)) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(state),
        media_type="text/event-stream",
        headers={
            # Proxies and the Vite dev server must not buffer an event stream;
            # buffering reintroduces exactly the "headers never arrive" symptom
            # this route was fixed to remove.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/v1/stream/recent")
async def stream_recent(
    after: Optional[str] = None,
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    """Events published after `after` (an `attempt_uid` cursor), in order.
    `after` omitted -> the whole bounded buffer. Same unauthenticated posture
    as `/v1/stream` (Decision 94).

    Remediation plan F-G: lifecycle control frames carry no `attempt_uid`, so
    `bus.recent()`'s cursor logic ignores them and this endpoint's contract is
    unchanged by their presence."""
    return {"events": state.event_bus.recent(after)}
