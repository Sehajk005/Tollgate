"""
Source: Implementation Plan v2.1 Day 1 -- DI wiring. ScorerState ties clock,
window store, rules, spool, drainer, and event bus together and is stashed
on app.state so route handlers can depend on it via FastAPI's Depends().
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import Request

from packages.clock.clock import Clock, SystemClock
from packages.clock.ids import UlidGenerator
from packages.contracts.records import compute_payload_digest
from packages.contracts.wire import ScoreRequest
from packages.detect.rules import DayOneRules, RulesEvaluation
from packages.detect.threat_state import ThreatRollup
from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import WindowStore
from packages.storage.bus import EventBus, InProcessEventBus
from packages.storage.db import connect
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool

if TYPE_CHECKING:
    import asyncio

    from services.scorer.replay import ReplayDriver

DEFAULT_PRIOR_STEADY_STATE = 0.001
# Source: Day-2 Plan §G / scripts/seed_merchant.py -- Day 2 is single-merchant
# demo scope; the replay driver always scores against the one seeded demo
# merchant (matches scripts/seed_merchant.py's MERCHANT_ID).
DEMO_MERCHANT_ID = "merchant_demo"


@dataclass
class ScorerState:
    clock: Clock
    ulid: UlidGenerator
    window_store: WindowStore
    rules: DayOneRules
    spool: Spool
    drainer: Drainer
    event_bus: EventBus
    db_path: Path
    policy_version: int = 1
    prior_steady_state: float = DEFAULT_PRIOR_STEADY_STATE
    # Day-2 Plan §L Step 7 -- "replay task handle". Both default to None so
    # Day-1 callers that construct ScorerState directly (tests/conftest.py,
    # scripts/_run_scorer_for_test.py) are unaffected; build_default() below
    # is the only Day-2 code path that populates replay_driver.
    replay_driver: Optional["ReplayDriver"] = None
    replay_task: Optional["asyncio.Task"] = None
    # Day-2 Plan §L Step 8 -- rollup on ScorerState. Optional/defaults to
    # None for the same reason replay_driver does: Day-1 callers that
    # construct ScorerState directly never see it, and services/scorer/
    # scoring.py treats absence as "no threat_state on this event".
    threat: Optional[ThreatRollup] = None

    def db_read_conn(self):
        return connect(self.db_path)

    def payload_digest(self, body: ScoreRequest) -> str:
        return compute_payload_digest(body)

    @staticmethod
    def rule_score(evaluation: RulesEvaluation) -> float:
        return evaluation.rule_score()

    @staticmethod
    def build_default(
        db_path: Path = Path("tollgate.db"),
        spool_dir: Path = Path("spool"),
    ) -> "ScorerState":
        clock = SystemClock()
        ulid = UlidGenerator(clock=clock, rng=random.Random())
        window_store = InMemoryWindowStore()
        rules = DayOneRules(window_store)
        spool = Spool(spool_dir)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        event_bus = InProcessEventBus()
        state = ScorerState(
            clock=clock, ulid=ulid, window_store=window_store, rules=rules,
            spool=spool, drainer=drainer, event_bus=event_bus, db_path=db_path,
            threat=ThreatRollup(),
        )
        # Local import: breaks the deps.py <-> replay.py import cycle
        # (replay.py imports ScorerState for its own type hints). By the
        # time build_default() actually runs, both modules are fully loaded.
        from services.scorer.replay import ReplayDriver

        state.replay_driver = ReplayDriver(state, merchant_id=DEMO_MERCHANT_ID)
        return state


def get_scorer_state(request: Request) -> ScorerState:
    return request.app.state.scorer
