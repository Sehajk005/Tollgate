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

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.scorer.deps import ScorerState
from services.scorer.routes_replay import router as replay_router
from services.scorer.routes_score import router as score_router
from services.scorer.routes_stream import router as stream_router

DEV_ORIGINS = ["http://localhost:5173", "http://localhost:5174"]


def create_app(state: Optional[ScorerState] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_state = state if state is not None else ScorerState.build_default()
        app.state.scorer = active_state
        active_state.drainer.drain_from_start()
        active_state.drainer.start()
        try:
            yield
        finally:
            if active_state.replay_task is not None and not active_state.replay_task.done():
                active_state.replay_task.cancel()
            active_state.drainer.stop()
            active_state.spool.close()

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

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
