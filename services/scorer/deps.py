"""
Source: Implementation Plan v2.1 Day 1 -- DI wiring. ScorerState ties clock,
window store, rules, spool, drainer, and event bus together and is stashed
on app.state so route handlers can depend on it via FastAPI's Depends().
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml
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

    from packages.detect.baseline import StoreBaseline
    from packages.detect.calibrate import Calibrator
    from packages.detect.episode import IncidentRegistry
    from packages.detect.layer2 import Layer2Engine
    from packages.detect.model import Layer1Model
    from packages.detect.policy import PolicyEngine, PolicySnapshot
    from services.scorer.admission import AdmissionController, AvailabilityMonitor
    from services.scorer.replay import ReplayDriver

DEFAULT_MODEL_DIR = Path("models")
DEFAULT_POLICY_YAML = Path("config/policy.yaml")

DEFAULT_PRIOR_STEADY_STATE = 0.001
# Source: Day-7 Plan §4 Step 2 -- the in-process stored-decision cache is a
# bounded FIFO keyed by idem_digest. Decision 71's precedent: hot-path state
# lives in-process on ScorerState, never as a second Redis write, so TRD
# §6.3's one-round-trip invariant and the p99 < 5 ms budget both hold. The
# single-worker limitation is the one Decision 71 already accepts.
DECISION_CACHE_MAX = 10_000
# Source: Day-7 Plan §4 Step 4 -- Redis socket timeout / connect timeout so a
# dead backend raises promptly and the route wrapper fails open inside the
# budget. The acceptance test measures wall clock (§12 trap 7).
FAIL_OPEN_BUDGET_MS = 150
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
    # Day-6 Plan §3.10 -- Layer 2 + policy, loaded guarded exactly like
    # `model`/`calibrator`. When `policy` is None the whole Layer-2 block in
    # services/scorer/scoring.py is skipped and the path is byte-identical to
    # Day 5. tests/conftest.py::scorer_state and eval/corpus.py::_replay_one
    # both build bare states, so the Day-5 corpus/model/audit/eval_run rows
    # are provably unaffected.
    policy: Optional["PolicySnapshot"] = None
    baseline: Optional["StoreBaseline"] = None
    layer2: Optional["Layer2Engine"] = None
    incidents: Optional["IncidentRegistry"] = None
    policy_engine: Optional["PolicyEngine"] = None
    enforcement_ttl_ms: int = 900_000
    # Day-6 Plan §3.3 -- an incident resolves against its PINNED policy
    # version, never the live one. Cache of {version -> PolicySnapshot};
    # populated with the live version at load, a pinned version is loaded
    # once (then cached) on first miss. `default_factory=dict` so bare
    # ScorerState(...) constructions are unaffected.
    policy_versions: dict = field(default_factory=dict)
    # Source: Day-7 Plan §4 Step 2 -- {idem_digest: (attempt_uid,
    # decision_value)}, written after a decision resolves. On an idempotent
    # replay (SET NX found the key) the stored pair is returned and the spool
    # append is skipped -- no duplicate auth_attempt / attempt_score row, no
    # duplicate SSE event. Bounded FIFO (DECISION_CACHE_MAX); a cross-process
    # or evicted miss falls back to the pre-Day-7 behaviour.
    decision_cache: dict = field(default_factory=dict)
    # Source: Day-7 Plan §4 Step 3/4 -- merchant-scoped admission control and
    # fail-open availability monitoring, in-process (Decision 87). Guarded
    # exactly like `model` / `policy`: `build_default()` populates them, every
    # bare ScorerState(...) in tests / eval leaves them None and the route
    # skips the admission + fail-open rungs (byte-identical to Day 6).
    admission: Optional["AdmissionController"] = None
    availability: Optional["AvailabilityMonitor"] = None
    # Source: Day-7 Plan §4 Step 4 -- {api_key_hash: merchant_id}, populated on
    # each successful auth. A locked SQLite with a WARM cache still
    # authenticates (and can then fail-open, merchant-scoped); a COLD cache +
    # locked DB returns 503 -- auth never fails open (Decision 89).
    api_key_cache: dict = field(default_factory=dict)
    # Source: Day-8 Plan Step 9 -- out-of-band Gemini narrator dispatch.
    # `gemini_tasks` holds the scheduled asyncio tasks (so a caller / test can
    # await them); `gemini_transport` is an injected httpx transport for tests
    # (None -> the real network). Both default such that every bare
    # ScorerState(...) construction is unaffected.
    gemini_tasks: set = field(default_factory=set)
    gemini_transport: object = None

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

            # Source: Day-7 Plan §4 Step 4 -- a dead Redis socket must raise
            # PROMPTLY so the route wrapper can fail open within the budget.
            # score_path() is a blocking sync call, so asyncio.wait_for cannot
            # bound it -- the socket timeout IS the mechanism (§12 trap 7).
            timeout_s = FAIL_OPEN_BUDGET_MS / 1000.0
            client = redis_lib.Redis.from_url(
                redis_url, socket_timeout=timeout_s, socket_connect_timeout=timeout_s
            )
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
    def _load_policy_yaml_params(policy_yaml: Path = DEFAULT_POLICY_YAML) -> dict:
        """Parse config/policy.yaml's {value,unit,source} leaves into the flat
        dict the Layer-2 engines need. Only the tunables with no policy_config
        column live here (lambda_min, the ARL0 target, L2b's statistic
        params, enforcement_ttl_s)."""
        raw = yaml.safe_load(Path(policy_yaml).read_text(encoding="utf-8"))

        def v(node):
            return node["value"] if isinstance(node, dict) and "value" in node else node

        return {
            "lambda_min": float(v(raw["cusum"]["lambda_min"])),
            "drift_exceedance_quantile": float(v(raw["drift"]["exceedance_quantile"])),
            "drift_p1": float(v(raw["drift"]["p1"])),
            "drift_alpha": float(v(raw["drift"]["alpha"])),
            "drift_beta": float(v(raw["drift"]["beta"])),
            "drift_enabled": bool(v(raw["drift"]["enabled"])),
            "enforcement_ttl_s": int(v(raw["policy"]["enforcement_ttl_s"])),
        }

    @staticmethod
    def _load_layer2(db_path: Path, merchant_id: str, policy_yaml: Path = DEFAULT_POLICY_YAML):
        """
        Source: Day-6 Plan §3.10 -- guarded, exactly like `_load_model`.
        Returns (policy, baseline, layer2, incidents, policy_engine, ttl_ms)
        only when a policy_config row with a populated `thresholds` column AND
        a store_baseline row both exist; any other case returns all-None so
        the serving path stays Day-5-identical (the authorized fallback).
        """
        none = (None, None, None, None, None, 900_000)
        try:
            from packages.detect.baseline import StoreBaseline  # noqa: F401
            from packages.detect.cusum import CusumParams
            from packages.detect.drift import DriftParams
            from packages.detect.episode import IncidentRegistry
            from packages.detect.layer2 import Layer2Engine
            from packages.detect.policy import PolicyEngine
            from packages.storage.repository import load_policy_config, load_store_baseline

            conn = connect(db_path, read_only=True)
            try:
                snapshot = load_policy_config(conn, merchant_id)
                baseline = load_store_baseline(conn, merchant_id)
            finally:
                conn.close()

            if snapshot is None or not snapshot.thresholds or "throttle" not in snapshot.thresholds:
                logger.info("no policy_config with thresholds for %s; Layer 2 disabled (Day-5 path)", merchant_id)
                return none
            if baseline is None:
                logger.info("no store_baseline row for %s; Layer 2 disabled (Day-5 path)", merchant_id)
                return none

            yaml_params = ScorerState._load_policy_yaml_params(policy_yaml)
            cusum_params = CusumParams(
                rho=snapshot.cusum_rho, h=snapshot.cusum_h,
                bucket_s=snapshot.cusum_bucket_s, lambda_min=yaml_params["lambda_min"],
            )
            drift_params = DriftParams(
                exceedance_quantile=yaml_params["drift_exceedance_quantile"],
                p1=yaml_params["drift_p1"], alpha=yaml_params["drift_alpha"],
                beta=yaml_params["drift_beta"], enabled=yaml_params["drift_enabled"],
            )
            layer2 = Layer2Engine(
                baseline=baseline, cusum_params=cusum_params, drift_params=drift_params,
                tau_flag=snapshot.thresholds["throttle"],
            )
            logger.info(
                "loaded Layer 2 for %s: policy v%d, cusum_h=%.3f, tau_flag=%.5f, drift_enabled=%s",
                merchant_id, snapshot.version, snapshot.cusum_h, layer2.tau_flag, drift_params.enabled,
            )
            return (
                snapshot, baseline, layer2, IncidentRegistry(), PolicyEngine(),
                yaml_params["enforcement_ttl_s"] * 1000,
            )
        except Exception:  # noqa: BLE001 -- any load failure falls back to the Day-5 path
            logger.exception("Layer 2 load failed for %s; falling back to the Day-5 serving path", merchant_id)
            return none

    @staticmethod
    def build_default(
        db_path: "Path | None" = None,
        spool_dir: "Path | None" = None,
        model_dir: Path = DEFAULT_MODEL_DIR,
    ) -> "ScorerState":
        # Day 9 Plan Phase 2: the containerized deployment puts the MUTABLE demo
        # DB + spool on a Linux-native volume, because SQLite in WAL mode cannot
        # mmap its -shm file over a Docker Desktop Windows bind mount (a fresh
        # read/write connection then fails with "unable to open database file").
        # TOLLGATE_DB_PATH / TOLLGATE_SPOOL_DIR select that location; an explicit
        # argument (the durability / lock-contention test runner) still wins, and
        # with neither the defaults are byte-identical to before.
        if db_path is None:
            db_path = Path(os.environ.get("TOLLGATE_DB_PATH", "tollgate.db"))
        if spool_dir is None:
            spool_dir = Path(os.environ.get("TOLLGATE_SPOOL_DIR", "spool"))
        clock = SystemClock()
        ulid = UlidGenerator(clock=clock, rng=random.Random())
        window_store = ScorerState._build_window_store()
        rules = DayOneRules(window_store)
        spool = Spool(spool_dir)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        event_bus = InProcessEventBus()
        model, calibrator = ScorerState._load_model(model_dir)
        policy, baseline, layer2, incidents, policy_engine, ttl_ms = ScorerState._load_layer2(
            db_path, DEMO_MERCHANT_ID
        )
        # Source: Day-7 Plan §4 Step 3/4 -- admission control + fail-open
        # availability monitoring, from config/policy.yaml's `admission:` block.
        from services.scorer.admission import (
            AdmissionController,
            AvailabilityMonitor,
            load_admission_config,
        )

        admission_cfg = load_admission_config()
        admission = AdmissionController(admission_cfg)
        availability = AvailabilityMonitor(
            alert_threshold=admission_cfg.fail_open_alert_threshold
        )
        state = ScorerState(
            clock=clock, ulid=ulid, window_store=window_store, rules=rules,
            spool=spool, drainer=drainer, event_bus=event_bus, db_path=db_path,
            threat=ThreatRollup(), model=model, calibrator=calibrator,
            policy=policy, baseline=baseline, layer2=layer2, incidents=incidents,
            policy_engine=policy_engine, enforcement_ttl_ms=ttl_ms,
            policy_versions={policy.version: policy} if policy is not None else {},
            admission=admission, availability=availability,
        )
        # Local import: breaks the deps.py <-> replay.py import cycle
        # (replay.py imports ScorerState for its own type hints). By the
        # time build_default() actually runs, both modules are fully loaded.
        from services.scorer.replay import ReplayDriver

        state.replay_driver = ReplayDriver(state, merchant_id=DEMO_MERCHANT_ID)
        return state


def get_scorer_state(request: Request) -> ScorerState:
    return request.app.state.scorer
