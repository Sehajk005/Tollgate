"""
Source: Implementation Plan v2.1 Day 1 -- DI wiring. ScorerState ties clock,
window store, rules, spool, drainer, and event bus together and is stashed
on app.state so route handlers can depend on it via FastAPI's Depends().
"""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger("tollgate.scorer")

if TYPE_CHECKING:
    import asyncio

    from packages.detect.calibrate import Calibrator
    from packages.detect.model import Layer1Model
    from services.scorer.replay import ReplayDriver

DEFAULT_MODEL_DIR = Path("models")

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
    # Day-5 Plan Step 9 -- the Layer-1 model + calibrator. Both default to None
    # (like replay_driver/threat), so every direct ScorerState(...) construction
    # in tests and eval/corpus.py is unaffected and, with no models/ artifact
    # present, the serving path is byte-identical to Day 4 -- which is also the
    # authorized Day-5 rules-only fallback. score yes, decide no: the model
    # informs score_raw/score_calibrated only; apply_auto_ceiling is unchanged.
    model: Optional["Layer1Model"] = None
    calibrator: Optional["Calibrator"] = None

    def db_read_conn(self):
        return connect(self.db_path)

    def payload_digest(self, body: ScoreRequest) -> str:
        return compute_payload_digest(body)

    @staticmethod
    def rule_score(evaluation: RulesEvaluation) -> float:
        return evaluation.rule_score()

    @staticmethod
    def _build_window_store() -> WindowStore:
        """
        Source: Day-3 Plan Step 7 -- RedisWindowStore is selected when
        TOLLGATE_REDIS_URL is set AND reachable; any other case (unset,
        unreachable) falls back to InMemoryWindowStore, which is also the
        pre-committed Day-3 20:00 fallback (Impl Plan Day 3 exit trigger).
        One place, logged at startup so which backend is live is never a
        silent question.
        """
        redis_url = os.environ.get("TOLLGATE_REDIS_URL")
        if not redis_url:
            logger.info("TOLLGATE_REDIS_URL not set; using InMemoryWindowStore")
            return InMemoryWindowStore()

        try:
            import redis as redis_lib

            from packages.features.redis_store import RedisWindowStore

            client = redis_lib.Redis.from_url(redis_url)
            client.ping()
            logger.info("Connected to Redis at %s; using RedisWindowStore", redis_url)
            return RedisWindowStore(client)
        except Exception:  # noqa: BLE001 -- any connection/import failure falls back
            logger.exception(
                "TOLLGATE_REDIS_URL=%s set but unreachable; falling back to "
                "InMemoryWindowStore (single-process limitation applies)",
                redis_url,
            )
            return InMemoryWindowStore()

    @staticmethod
    def _load_model(model_dir: Path):
        """
        Source: Day-5 Plan Step 9 -- guarded, exactly like `_build_window_store`.
        Returns (Layer1Model, Calibrator) only when `model_dir` holds a
        loadable l1-lgbm booster+artifact pair AND a platt-v1.json; any other
        case (absent, unreadable, no lightgbm) returns (None, None) and the
        serving path stays rules-only -- the authorized Day-5 fallback.
        """
        try:
            from packages.detect.model import Layer1Model, artifact_exists
        except Exception:  # noqa: BLE001 -- lightgbm not installed / import failure
            logger.info("packages.detect.model unavailable; scoring rules-only")
            return None, None

        if not artifact_exists(model_dir):
            logger.info("no model artifact under %s; scoring rules-only (Day-5 fallback)", model_dir)
            return None, None

        try:
            from packages.detect.calibrate import Calibrator

            model = Layer1Model.load(model_dir)
            calibrator = Calibrator.load(Path(model_dir) / "platt-v1.json")
            logger.info(
                "loaded Layer-1 model %s + calibrator %s from %s",
                model.model_version, calibrator.calibrator_version, model_dir,
            )
            return model, calibrator
        except Exception:  # noqa: BLE001 -- any load failure falls back to rules-only
            logger.exception(
                "model artifact present under %s but failed to load; falling back to rules-only",
                model_dir,
            )
            return None, None

    @staticmethod
    def build_default(
        db_path: Path = Path("tollgate.db"),
        spool_dir: Path = Path("spool"),
        model_dir: Path = DEFAULT_MODEL_DIR,
    ) -> "ScorerState":
        clock = SystemClock()
        ulid = UlidGenerator(clock=clock, rng=random.Random())
        window_store = ScorerState._build_window_store()
        rules = DayOneRules(window_store)
        spool = Spool(spool_dir)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        event_bus = InProcessEventBus()
        model, calibrator = ScorerState._load_model(model_dir)
        state = ScorerState(
            clock=clock, ulid=ulid, window_store=window_store, rules=rules,
            spool=spool, drainer=drainer, event_bus=event_bus, db_path=db_path,
            threat=ThreatRollup(), model=model, calibrator=calibrator,
        )
        # Local import: breaks the deps.py <-> replay.py import cycle
        # (replay.py imports ScorerState for its own type hints). By the
        # time build_default() actually runs, both modules are fully loaded.
        from services.scorer.replay import ReplayDriver

        state.replay_driver = ReplayDriver(state, merchant_id=DEMO_MERCHANT_ID)
        return state


def get_scorer_state(request: Request) -> ScorerState:
    return request.app.state.scorer
