"""
Source: Implementation Plan v2.1 Day 1 -- POST /v1/score. Auth -> validation
-> three hard rules -> Decision -> spool-always -> SSE publish -> respond.

Day-2 Plan §L Step 6 / Decision 26: the route now does auth + IP resolution
+ Stopwatch only, delegating steps 5-11 to services/scorer/scoring.py::
score_attempt() -- the seam the replay driver (Step 7) also calls. Pure
extraction; no behaviour change (55 Day-1 tests, unedited, are the proof).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from packages.clock.stopwatch import Stopwatch
from packages.contracts.wire import ScoreRequest, ScoreResponse
from services.scorer.auth import resolve_merchant_id
from services.scorer.deps import ScorerState, get_scorer_state
from services.scorer.net import resolve_client_ip
from services.scorer.scoring import score_attempt

router = APIRouter()


@router.post("/v1/score", response_model=ScoreResponse)
async def score(
    request: Request,
    body: ScoreRequest,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> ScoreResponse:
    stopwatch = Stopwatch()

    conn = state.db_read_conn()
    try:
        merchant_id = resolve_merchant_id(conn, x_tollgate_key)
    finally:
        conn.close()
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    ip = resolve_client_ip(request)

    response, _event = await score_attempt(
        state,
        merchant_id=merchant_id,
        ip=ip,
        body=body,
        stopwatch=stopwatch,
        user_agent=request.headers.get("user-agent", ""),
    )
    return response
