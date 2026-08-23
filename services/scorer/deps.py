"""
Source: Implementation Plan v2.1 Day 1 -- DI wiring. ScorerState ties clock,
window store, rules, spool, drainer, and event bus together and is stashed
on app.state so route handlers can depend on it via FastAPI's Depends().
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from packages.clock.clock import Clock, SystemClock
from packages.clock.ids import UlidGenerator
from packages.contracts.records import compute_payload_digest
from packages.contracts.wire import ScoreRequest
from packages.detect.rules import DayOneRules, RulesEvaluation
from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import WindowStore
from packages.storage.bus import EventBus, InProcessEventBus
from packages.storage.db import connect
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool

DEFAULT_PRIOR_STEADY_STATE = 0.001


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
        return ScorerState(
            clock=clock, ulid=ulid, window_store=window_store, rules=rules,
            spool=spool, drainer=drainer, event_bus=event_bus, db_path=db_path,
        )


def get_scorer_state(request: Request) -> ScorerState:
    return request.app.state.scorer
