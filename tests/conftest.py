"""
Shared fixtures for the acceptance and unit suites.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import packages.config.env as env_config

from packages.clock.clock import SystemClock
from packages.clock.ids import UlidGenerator
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.app import create_app
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


# ---------------------------------------------------------------------------
# Source: remediation plan FIX-000 (AUDIT-010) -- process-global test isolation.
#
# Two pieces of process-global state leak between tests and silently change
# what a later test measures:
#
#   * `os.environ` -- `create_app()`'s lifespan calls `load_env_file()`, which
#     loads the repo-root `.env` into THIS process. That is how the first
#     acceptance test to use the `client` fixture put TOLLGATE_REDIS_URL into
#     the pytest process, which `test_day2_e2e._spawn` then handed to its
#     subprocess via `dict(os.environ)`. One test decided another test's
#     storage backend. `monkeypatch` does not cover it: some tests (e.g.
#     `test_narrator_eval_disabled.py`) write `os.environ` directly.
#   * `packages.config.env._loaded` -- the once-only latch guarding that load.
#     Restoring the environment without restoring the latch would leave a
#     later `load_env_file()` a silent no-op.
#
# `env_snapshot()` is the mechanism; `env_isolation` is the autouse fixture
# that applies it to every test. Pinned by tests/acceptance/test_env_isolation.py.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def env_snapshot():
    """Restore `os.environ` and `packages.config.env._loaded` on exit.

    Restores by difference rather than `os.environ.clear()` + update, so
    variables whose value never changed are never re-`putenv`'d.
    """
    saved_environ = dict(os.environ)
    saved_loaded = env_config._loaded
    try:
        yield
    finally:
        for key in [k for k in os.environ if k not in saved_environ]:
            del os.environ[key]
        for key, value in saved_environ.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
        env_config._loaded = saved_loaded


@pytest.fixture(autouse=True)
def env_isolation():
    """Every test starts from, and leaves behind, the environment it was given."""
    with env_snapshot():
        yield


@pytest.fixture
def tmp_workspace(tmp_path: Path):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    return db_path, spool_dir


def seed_merchant(db_path: Path, merchant_id: str = "merchant_test") -> str:
    raw_key = secrets.token_urlsafe(16)
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES (?, 'Test Merchant', 'INR', 'Asia/Kolkata', ?, ?, 0)
            """,
            (merchant_id, hash_api_key(raw_key), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
                      'challenge', 10, 0.05, '{}', 0)
            """,
            (merchant_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return raw_key


@pytest.fixture
def scorer_state(tmp_workspace):
    db_path, spool_dir = tmp_workspace
    clock = SystemClock()
    ulid = UlidGenerator(clock=clock)
    window_store = InMemoryWindowStore()
    rules = DayOneRules(window_store)
    spool = Spool(spool_dir)
    drainer = Drainer(db_path=db_path, spool_path=spool.path)
    bus = InProcessEventBus()
    state = ScorerState(
        clock=clock, ulid=ulid, window_store=window_store, rules=rules,
        spool=spool, drainer=drainer, event_bus=bus, db_path=db_path,
    )
    yield state
    state.spool.close()


@pytest.fixture
def client(scorer_state, tmp_workspace):
    db_path, _ = tmp_workspace
    api_key = seed_merchant(db_path)
    app = create_app(state=scorer_state)
    with TestClient(app) as test_client:
        test_client.tollgate_api_key = api_key
        yield test_client


# ---------------------------------------------------------------------------
# Source: Day-5 Plan §7 / §9 -- shared build for the corpus/model-dependent
# acceptance + characterization tests (1, 4, 5, 6, 7, 8, 9, 10 and the
# bisection rung). Reuses the committed repo artifacts
# (`data/corpus/tollgate.db` + `models/`) when present and loadable; otherwise
# rebuilds them ONCE per session into a session tmp dir -- the booster `.txt`
# and the corpus `.db` are gitignored (Day-5 Plan §8), so a fresh clone
# rebuilds while a local run after `python -m scripts.train_l1` reuses.
# In tests/conftest.py (not tests/acceptance/) so tests/characterization/ can
# use it too.
# ---------------------------------------------------------------------------

_DAY5_SEED = 42
_REPO_CORPUS_DB = REPO_ROOT / "data" / "corpus" / "tollgate.db"
_REPO_MODEL_DIR = REPO_ROOT / "models"


def _day5_corpus_usable(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        from packages.storage.db import connect

        conn = connect(db_path)
        try:
            n = conn.execute("SELECT COUNT(*) FROM attempt_score").fetchone()[0]
            m = conn.execute("SELECT COUNT(*) FROM attempt_label").fetchone()[0]
        finally:
            conn.close()
        return n > 0 and m > 0
    except Exception:  # noqa: BLE001
        return False


def _day5_model_usable(model_dir: Path) -> bool:
    try:
        from packages.detect.model import artifact_exists

        return (
            artifact_exists(model_dir)
            and (model_dir / "platt-v1.json").exists()
            and (model_dir / "audit.json").exists()
        )
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def day5_seed() -> int:
    return _DAY5_SEED


@pytest.fixture(scope="session")
def day5_corpus(tmp_path_factory) -> Path:
    """Path to a replayed feature corpus DB (seed 42, the full build_runs layout)."""
    if _day5_corpus_usable(_REPO_CORPUS_DB):
        return _REPO_CORPUS_DB
    from eval.corpus import build_runs, replay_corpus

    work = tmp_path_factory.mktemp("day5_corpus")
    db_path = work / "tollgate.db"
    replay_corpus(build_runs(_DAY5_SEED), db_path=db_path, spool_dir=work / "spool", rebuild=True)
    return db_path


@pytest.fixture(scope="session")
def day5_model(day5_corpus, tmp_path_factory) -> Path:
    """Path to a models/ dir with l1-lgbm-v1.{txt,json}, platt-v1.json, audit.json."""
    if day5_corpus == _REPO_CORPUS_DB and _day5_model_usable(_REPO_MODEL_DIR):
        return _REPO_MODEL_DIR
    import subprocess
    import sys

    out = tmp_path_factory.mktemp("day5_models")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.train_l1", "--seed", str(_DAY5_SEED),
         "--db", str(day5_corpus), "--out", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, f"train_l1 failed:\n{result.stdout}\n{result.stderr}"
    return out
