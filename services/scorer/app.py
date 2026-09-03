"""
Source: Implementation Plan v2.1 Day 1 -- FastAPI factory. Startup drains any
surviving spool segments before the service accepts traffic (Backend Schema
v2.1 section 1), then starts the background drainer thread.

CORS (decisions.md, decision 11): the Vite dev-server proxy makes the browser
see same-origin requests, which removes the CORS surface rather than
exercising it. CORS middleware is added here so a direct cross-origin call
from either dev app also works and the CORS path stays independently
testable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from packages.config.env import load_env_file, validate_startup
from services.scorer.deps import ScorerState
from services.scorer.routes_incidents import router as incidents_router
from services.scorer.routes_outcome import router as outcome_router
from services.scorer.routes_replay import router as replay_router
from services.scorer.routes_score import router as score_router
from services.scorer.routes_stream import router as stream_router

logger = logging.getLogger("tollgate.scorer")

DEV_ORIGINS = ["http://localhost:5173", "http://localhost:5174"]

# Source: remediation plan §11.2 / FIX-001 -- PERMANENT instrumentation.
#
# AUDIT-006 was a blocked event loop, and the service had no way to say so: the
# replay counter simply stopped and every endpoint timed out, with no evidence
# left behind. This task sleeps for a known interval and logs how much longer
# than that it actually took. It CANNOT preempt a synchronous spin -- nothing
# running on the loop can -- but it records the block the moment the loop is
# free again, so a stall always leaves a trace instead of a mystery.
LOOP_LAG_INTERVAL_S = 1.0
LOOP_LAG_WARN_S = 2.0
_FAULTHANDLER_DUMP_S = 60.0


async def _loop_lag_monitor() -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            before = loop.time()
            await asyncio.sleep(LOOP_LAG_INTERVAL_S)
            lag = loop.time() - before - LOOP_LAG_INTERVAL_S
            if lag > LOOP_LAG_WARN_S:
                logger.warning(
                    "event loop lag %.2fs (threshold %.1fs) -- something ran "
                    "synchronously on the loop thread for that long",
                    lag, LOOP_LAG_WARN_S,
                )
    except asyncio.CancelledError:
        return


def _maybe_enable_faulthandler() -> None:
    """`TOLLGATE_FAULTHANDLER=1` arms native-fault tracebacks and a periodic
    stack dump. Env-gated because the audit's own caveat stands: the two
    SIGSEGVs it recorded happened under `dump_traceback_later`, so the
    diagnostic itself is a suspect and §17 runs the gate BOTH ways."""
    if os.environ.get("TOLLGATE_FAULTHANDLER", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    import faulthandler

    faulthandler.enable()
    faulthandler.dump_traceback_later(_FAULTHANDLER_DUMP_S, repeat=True)
    logger.warning(
        "faulthandler enabled with a %.0fs repeating dump (TOLLGATE_FAULTHANDLER)",
        _FAULTHANDLER_DUMP_S,
    )


def create_app(state: Optional[ScorerState] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Load an optional repo-root .env before any component reads its
        # configuration -- deps.py reads TOLLGATE_REDIS_URL during
        # build_default() and scoring.py reads the narrator vars per request.
        # override=False: a real environment variable always wins, so an
        # inline `KEY=val uvicorn ...` and test monkeypatching are unaffected;
        # with no .env present this is a pure no-op.
        dotenv_path = load_env_file()
        if dotenv_path:
            logger.warning("config: loaded environment from %s", dotenv_path)
        for message in validate_startup():
            logger.warning("config: %s", message)

        _maybe_enable_faulthandler()

        active_state = state if state is not None else ScorerState.build_default()
        app.state.scorer = active_state
        active_state.drainer.drain_from_start()
        active_state.drainer.start()
        lag_task = asyncio.create_task(_loop_lag_monitor())
        try:
            yield
        finally:
            lag_task.cancel()
            # Let any out-of-band Gemini narration tasks finish and spool
            # their narrator_call row before the spool is closed. Bounded
            # (~2x the call timeout) so a hung call cannot block shutdown;
            # on timeout the stragglers are cancelled.
            pending = [t for t in active_state.gemini_tasks if not t.done()]
            if pending:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    for task in pending:
                        task.cancel()
            if active_state.replay_task is not None and not active_state.replay_task.done():
                active_state.replay_task.cancel()
            active_state.drainer.stop()
            active_state.spool.close()
            # Final synchronous flush -- the 50 ms poll loop may not have run
            # since a narration task appended its row just now. Idempotent
            # (INSERT OR IGNORE on the row PKs); the same call the acceptance
            # tests make after closing the spool.
            active_state.drainer.drain_from_start()

    app = FastAPI(title="Tollgate Scorer", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(score_router)
    app.include_router(stream_router)
    app.include_router(replay_router)
    # Day-8 Plan Step 6 -- the D3 incident read model + confirm / resolve.
    app.include_router(incidents_router)
    # Day-7 Plan §4 Step 5 -- POST /v1/outcome. Self-guards: without
    # TOLLGATE_OUTCOME_SECRET the route returns 503 (logged once); the rest of
    # the service is unaffected.
    app.include_router(outcome_router)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Deliberately does no work at all: its only job is to answer, so a
        slow answer means the EVENT LOOP is blocked and nothing else. That is
        precisely the signal AUDIT-006 needed and §17 gates on."""
        scorer = getattr(app.state, "scorer", None)
        if scorer is None:
            return {"status": "ok"}
        drainer = scorer.drainer
        # Source: remediation plan §17 -- the drainer gate ("connect() calls <= 2
        # per run", "the thread is alive at the end of all 23 runs") has to be
        # checkable from OUTSIDE the process, because the runs it gates are
        # subprocesses. Counters only; no work is done here.
        return {
            "status": "ok",
            "drainer_alive": drainer.is_alive(),
            "drainer_connects": drainer.connect_calls,
            "drainer_rows": drainer.rows_drained,
            "drainer_failures": drainer.consecutive_failures,
        }

    return app
