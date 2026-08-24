"""
Source: Day-2 Plan §G "Replay Design" -- the virtual-clock replay driver,
exactly the loop described there: `vclock.set_ms(t0 + ev.t_ms)` -- never
`advance_ms(wall_delta)` -- so virtual time IS event time. "The only
wall-clock call in the loop is asyncio.sleep, which affects nothing the
scorer reads" (Day-2 Plan §G).

`ulid` is seeded deterministically from `request.seed` (see
services/scorer/scoring.py's docstring) so attempt_uid minting, not just
decisions, is reproducible under A13's speed=0-vs-60 comparison.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Optional

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from services.scorer.deps import ScorerState
from services.scorer.scoring import score_attempt


@dataclass(frozen=True)
class ReplayRequest:
    tier: str
    seed: int = 42
    speed: int = 0
    epoch_ms: Optional[int] = None
    hours: int = 3


@dataclass
class ReplayStatus:
    state: str = "idle"  # idle | running | stopped | finished
    tier: Optional[str] = None
    seed: Optional[int] = None
    speed: Optional[int] = None
    sent: int = 0
    total: int = 0
    episode_id: Optional[str] = None
    virtual_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "state": self.state, "tier": self.tier, "seed": self.seed, "speed": self.speed,
            "sent": self.sent, "total": self.total, "episode_id": self.episode_id,
            "virtual_time_ms": self.virtual_time_ms,
        }


class ReplayDriver:
    def __init__(self, state: ScorerState, merchant_id: str) -> None:
        self._state = state
        self._merchant_id = merchant_id
        self._clock = VirtualClock(epoch_ms=0)
        self._status = ReplayStatus(state="idle")
        self._stop_requested = False

    @property
    def clock(self) -> VirtualClock:
        return self._clock

    @property
    def status(self) -> ReplayStatus:
        return self._status

    def mark_starting(self, request: ReplayRequest) -> None:
        """
        Synchronous, no `await` in between the caller's 409-check and this
        call (routes_replay.py) -- asyncio.create_task() does not begin
        executing run() until the next event-loop iteration, so without
        this, two rapid POST /v1/replay/start calls could both observe
        state != "running" and both launch a driver.
        """
        self._status = ReplayStatus(state="running", tier=request.tier, seed=request.seed, speed=request.speed)

    def stop(self) -> None:
        self._stop_requested = True

    def reset(self) -> None:
        """Decision 36: Reset is required, not convenient -- VirtualClock cannot move
        backwards and windows accumulate, so without it the demo runs once per process."""
        self._state.window_store.clear()
        if self._state.threat is not None:
            self._state.threat.clear()
        self._status = ReplayStatus(state="idle")
        self._stop_requested = False

    async def run(self, request: ReplayRequest, stream=None) -> ReplayStatus:
        self._stop_requested = False
        epoch_ms = request.epoch_ms if request.epoch_ms is not None else self._state.clock.now_ms()
        self._clock = VirtualClock(epoch_ms=epoch_ms)
        ulid = UlidGenerator(clock=self._clock, rng=random.Random(f"ulid:{request.seed}"))

        if stream is None:
            from packages.simulator.generate import build_stream  # local: keep off the storefront's import graph

            result = build_stream(seed=request.seed, tier=request.tier, hours=request.hours)
            events = result.events
            episode_id = result.episodes[0].episode_id if result.episodes else None
        else:
            events = list(stream)
            episode_id = None

        total = len(events)
        self._status = ReplayStatus(
            state="running", tier=request.tier, seed=request.seed, speed=request.speed,
            sent=0, total=total, episode_id=episode_id, virtual_time_ms=epoch_ms,
        )

        prev_t_ms = 0
        for index, ev in enumerate(events):
            if self._stop_requested:
                self._status = ReplayStatus(
                    state="stopped", tier=request.tier, seed=request.seed, speed=request.speed,
                    sent=index, total=total, episode_id=episode_id, virtual_time_ms=self._clock.now_ms(),
                )
                return self._status

            self._clock.set_ms(epoch_ms + ev.t_ms)
            body = ScoreRequest(**ev.to_score_request())
            await score_attempt(
                self._state, merchant_id=self._merchant_id, ip=ev.ip, body=body,
                clock=self._clock, ulid=ulid,
            )

            if request.speed:
                delta_ms = ev.t_ms - prev_t_ms
                if delta_ms > 0:
                    await asyncio.sleep(delta_ms / 1000 / request.speed)
            prev_t_ms = ev.t_ms

            self._status = ReplayStatus(
                state="running", tier=request.tier, seed=request.seed, speed=request.speed,
                sent=index + 1, total=total, episode_id=episode_id, virtual_time_ms=self._clock.now_ms(),
            )

        self._status = ReplayStatus(
            state="finished", tier=request.tier, seed=request.seed, speed=request.speed,
            sent=total, total=total, episode_id=episode_id, virtual_time_ms=self._clock.now_ms(),
        )
        return self._status
