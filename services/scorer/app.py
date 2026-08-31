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

        active_state = state if state is not None else ScorerState.build_default()
        app.state.scorer = active_state
        active_state.drainer.drain_from_start()
        active_state.drainer.start()
        try:
            yield
        finally:
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
        return {"status": "ok"}

    return app
