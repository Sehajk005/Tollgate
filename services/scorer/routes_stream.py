"""
Source: Implementation Plan v2.1 Day 1 -- GET /v1/stream (SSE). Backend
today is InProcessEventBus (packages/storage/bus.py); Redis pub/sub replaces
it on Day 3 without touching this route.
"""

from __future__ import annotations

import json

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
