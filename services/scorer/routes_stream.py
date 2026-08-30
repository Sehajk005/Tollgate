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
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from services.scorer.deps import ScorerState, get_scorer_state

router = APIRouter()


async def _event_stream(state: ScorerState):
    async for event in state.event_bus.subscribe():
        yield f"data: {json.dumps(event)}\n\n"


@router.get("/v1/stream")
async def stream(state: ScorerState = Depends(get_scorer_state)) -> StreamingResponse:
    return StreamingResponse(_event_stream(state), media_type="text/event-stream")


@router.get("/v1/stream/recent")
async def stream_recent(
    after: Optional[str] = None,
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    """Events published after `after` (an `attempt_uid` cursor), in order.
    `after` omitted -> the whole bounded buffer. Same unauthenticated posture
    as `/v1/stream` (Decision 94)."""
    return {"events": state.event_bus.recent(after)}
