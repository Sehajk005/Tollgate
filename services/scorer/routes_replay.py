"""
Source: Day-2 Plan §G -- POST /v1/replay/start|stop|reset, GET .../status.
Same API-key auth as /v1/score (Day-2 Plan §G: "Auth still gates *starting*
a replay; the loop does not re-authenticate per event") -- stop/reset/status
don't re-check the key.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from services.scorer.auth import resolve_merchant_id
from services.scorer.deps import ScorerState, get_scorer_state
from services.scorer.replay import ReplayRequest

router = APIRouter()


class ReplayStartBody(BaseModel):
    tier: str
    seed: int = 42
    speed: int = 0
    epoch_ms: Optional[int] = None
    hours: int = 3


@router.post("/v1/replay/start", status_code=202)
async def replay_start(
    request: Request,
    body: ReplayStartBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    conn = state.db_read_conn()
    try:
        merchant_id = resolve_merchant_id(conn, x_tollgate_key)
    finally:
        conn.close()
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    driver = state.replay_driver
    if driver.status.state == "running":
        raise HTTPException(status_code=409, detail="replay already running")

    replay_request = ReplayRequest(
        tier=body.tier, seed=body.seed, speed=body.speed, epoch_ms=body.epoch_ms, hours=body.hours,
    )
    driver.mark_starting(replay_request)
    state.replay_task = asyncio.create_task(driver.run(replay_request))
    return driver.status.to_dict()


@router.post("/v1/replay/stop")
async def replay_stop(state: ScorerState = Depends(get_scorer_state)) -> dict:
    state.replay_driver.stop()
    return state.replay_driver.status.to_dict()


@router.post("/v1/replay/reset")
async def replay_reset(state: ScorerState = Depends(get_scorer_state)) -> dict:
    state.replay_driver.reset()
    return state.replay_driver.status.to_dict()


@router.get("/v1/replay/status")
async def replay_status(state: ScorerState = Depends(get_scorer_state)) -> dict:
    return state.replay_driver.status.to_dict()
