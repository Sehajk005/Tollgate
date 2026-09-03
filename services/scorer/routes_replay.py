"""
Source: Day-2 Plan §G -- POST /v1/replay/start|stop|reset, GET .../status.

Remediation plan FIX-005 / FIX-006 / FIX-008 / FIX-009 / FIX-011.

AUTH POSTURE (plan §14, AUDIT-021). Day 2's docstring justified leaving stop
and reset open with "the loop does not re-authenticate per event" -- a true
statement about a different question. Both are STATE-MUTATING and `reset`
destroys live detector state, so both now authenticate exactly like /v1/score
and /v1/incidents, including `AuthBackendUnavailable -> 503` (auth never fails
open, Decision 89).

`GET /v1/replay/status` stays deliberately unauthenticated, consistent with
`/v1/stream` (Decision 94): it discloses strictly less than the stream already
does, and the frontend's mount-time recovery poll has to work unconditionally
for a page refresh to reconstruct correctly.

LIFECYCLE. Every mutating handler runs under the driver's single
`lifecycle_lock`, which is what makes "status says idle while the previous run
is still scoring" (AUDIT-004) unreachable rather than merely unlikely. The lock
is acquired with a bounded wait so a wedged driver returns 409 instead of
hanging the request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from services.scorer.auth import AuthBackendUnavailable, resolve_merchant_id_cached
from services.scorer.deps import ScorerState, get_scorer_state
from services.scorer.replay import BUSY_STATES, ReplayDriver, ReplayRequest

logger = logging.getLogger("tollgate.scorer.replay")

router = APIRouter()

# A lifecycle transition is bounded (stop/cancel each wait at most 2 s), so a
# caller that cannot get the lock inside this window is contending with a
# transition that is itself about to finish -- 409 is the honest answer.
LOCK_WAIT_S = 6.0


class ReplayStartBody(BaseModel):
    tier: str
    seed: int = 42
    speed: int = 0
    epoch_ms: Optional[int] = None
    hours: int = 3
    # Source: remediation plan FIX-011 (AUDIT-014) -- "episode" or null.
    pace_from: Optional[str] = None


def _auth(state: ScorerState, key: Optional[str]) -> str:
    try:
        merchant_id = resolve_merchant_id_cached(state, key)
    except AuthBackendUnavailable:
        raise HTTPException(status_code=503, detail="auth backend unavailable")
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return merchant_id


def _driver(state: ScorerState) -> ReplayDriver:
    driver = state.replay_driver
    if driver is None:
        raise HTTPException(status_code=503, detail="replay driver not configured")
    return driver


async def _acquire(driver: ReplayDriver):
    try:
        await asyncio.wait_for(driver.lifecycle_lock.acquire(), LOCK_WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=409, detail="another replay lifecycle operation is in progress"
        )


def _on_replay_task_done(driver: ReplayDriver, task: "asyncio.Task") -> None:
    """
    Source: remediation plan FIX-007 (AUDIT-007). The task handle was stored and
    never inspected, so the strong reference suppressed even asyncio's "never
    retrieved" warning and a crashed replay looked exactly like a slow one.
    This retrieves the exception on every path.
    """
    if task.cancelled():
        logger.info("replay task cancelled (run_id=%s)", driver.status.run_id)
        return
    exc = task.exception()
    if exc is None:
        return
    # run() already records `failed` for exceptions it sees; this catches the
    # ones it cannot -- a failure in its own `finally`, or a BaseException.
    logger.error("replay task ended with an unhandled exception", exc_info=exc)
    if not driver.status.is_terminal:
        driver._set_status(state="failed", error=f"{type(exc).__name__}: {exc}")


@router.post("/v1/replay/start", status_code=202)
async def replay_start(
    request: Request,
    body: ReplayStartBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    _auth(state, x_tollgate_key)
    driver = _driver(state)

    await _acquire(driver)
    try:
        if driver.status.state in BUSY_STATES:
            raise HTTPException(status_code=409, detail="replay already running")

        # Source: remediation plan §9 -- AUTO-CLEAR ON LAUNCH. Launching from a
        # terminal-but-dirty state used to reuse the previous run's windows,
        # incidents and 24-hour idempotency keys, so the second run of a tier
        # was invisible (AUDIT-005). Reset is still required and still explicit;
        # it is now also the manual form of an invariant the system enforces.
        auto_reset = False
        cleared: dict = {}
        degraded = False
        if driver.status.state != "idle":
            auto_reset = True
            outcome = await driver.reset(stop_reason="reset")
            if not outcome["ok"]:
                raise HTTPException(status_code=409, detail=outcome["reason"])
            cleared = outcome["cleared"]
            degraded = outcome["degraded"]

        replay_request = ReplayRequest(
            tier=body.tier, seed=body.seed, speed=body.speed, epoch_ms=body.epoch_ms,
            hours=body.hours, pace_from=body.pace_from,
        )
        driver.mark_starting(replay_request)
        task = asyncio.create_task(driver.run(replay_request))
        task.add_done_callback(lambda t: _on_replay_task_done(driver, t))
        state.replay_task = task
        await driver.publish_status()

        payload = driver.status.to_dict()
        payload["auto_reset"] = auto_reset
        if auto_reset:
            payload["cleared"] = cleared
            payload["degraded"] = degraded
        return payload
    finally:
        driver.lifecycle_lock.release()


@router.post("/v1/replay/stop")
async def replay_stop(
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    """Authenticated (plan §14). Returns the TRUE terminal snapshot once the
    loop acknowledges, or `stopping` on timeout -- never a stale `running`."""
    _auth(state, x_tollgate_key)
    driver = _driver(state)
    await _acquire(driver)
    try:
        status = await driver.stop(reason="operator")
        return status.to_dict()
    finally:
        driver.lifecycle_lock.release()


@router.post("/v1/replay/reset")
async def replay_reset(
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    """Authenticated (plan §14) -- this destroys live detector state.

    Transactional: cancel -> await termination -> clear -> publish -> idle.
    A per-layer `cleared` map is returned so a partial failure (Redis down, say)
    is reported honestly as `degraded` rather than as a bare 500."""
    _auth(state, x_tollgate_key)
    driver = _driver(state)
    await _acquire(driver)
    try:
        outcome = await driver.reset()
    finally:
        driver.lifecycle_lock.release()

    if not outcome["ok"]:
        raise HTTPException(status_code=409, detail=outcome["reason"])
    payload = driver.status.to_dict()
    payload["cleared"] = outcome["cleared"]
    payload["degraded"] = outcome["degraded"]
    return payload


@router.get("/v1/replay/status")
async def replay_status(state: ScorerState = Depends(get_scorer_state)) -> dict:
    """Deliberately unauthenticated -- see the module docstring and Decision 94.
    This is the recovery path the frontend polls on mount, after a refresh, and
    every second while the run is non-terminal, so it must answer even when the
    dashboard has no key configured."""
    return _driver(state).status.to_dict()
