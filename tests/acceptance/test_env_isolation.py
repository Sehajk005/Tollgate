"""
Source: remediation plan FIX-000 (AUDIT-010) -- the isolation the whole suite's
trustworthiness rests on.

AUDIT-010's mechanism was process-global leakage, in two places:

  1. `create_app()`'s lifespan calls `load_env_file()`, which loads the
     repo-root `.env` into the *pytest* process. Every later subprocess spawned
     with `dict(os.environ)` then inherited `TOLLGATE_REDIS_URL` and silently
     changed storage backend.
  2. `packages.config.env._loaded` latches that load, so restoring the
     environment without restoring the latch leaves the next `load_env_file()`
     a silent no-op.

These tests pin both halves of the fix: the `env_snapshot()` mechanism, and the
autouse `env_isolation` fixture that applies it to every test in the suite.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from fastapi.testclient import TestClient

import packages.config.env as env_config
from services.scorer.app import create_app
from tests.conftest import env_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = "TOLLGATE_ENV_ISOLATION_PROBE"


class TestEnvSnapshotMechanism:
    def test_environment_and_loaded_flag_are_restored_around_a_create_app_lifespan(
        self, scorer_state
    ):
        before_environ = dict(os.environ)
        before_loaded = env_config._loaded

        with env_snapshot():
            # Force the lifespan to take the real `.env`-loading path rather
            # than short-circuiting on the latch.
            env_config._loaded = False
            os.environ[PROBE] = "set-inside-the-snapshot"
            with TestClient(create_app(state=scorer_state)):
                pass
            assert env_config._loaded is True, (
                "the lifespan did not run load_env_file(); this test is not "
                "exercising the leak it exists to prevent"
            )

        assert dict(os.environ) == before_environ, (
            "os.environ was not restored after the snapshot exited"
        )
        assert PROBE not in os.environ
        assert env_config._loaded == before_loaded, (
            "packages.config.env._loaded was not restored; the next "
            "load_env_file() would be a silent no-op"
        )

    def test_snapshot_restores_a_mutated_pre_existing_variable(self):
        os.environ[PROBE] = "original"
        try:
            with env_snapshot():
                os.environ[PROBE] = "mutated"
            assert os.environ[PROBE] == "original"
        finally:
            os.environ.pop(PROBE, None)


class TestAutouseEnvIsolationFixture:
    """These two run in file order, which pytest guarantees within a class --
    including under the reversed-FILE-order gate in §15."""

    def test_a_dirties_process_global_state(self):
        os.environ[PROBE] = "leaked"
        env_config._loaded = not env_config._loaded

    def test_b_starts_from_a_clean_environment(self):
        assert PROBE not in os.environ, (
            "the autouse env_isolation fixture is not restoring os.environ -- "
            "one test can change what another test measures (AUDIT-010)"
        )


class TestSpawnedScorerIsHermetic:
    def test_the_spawn_env_never_carries_a_tollgate_variable_from_the_parent(self):
        from tests.acceptance._scorer_process import hermetic_env

        os.environ["TOLLGATE_REDIS_URL"] = "redis://parent-should-not-leak:6379"
        os.environ["GEMINI_API_KEY"] = "parent-secret"
        try:
            env = hermetic_env(Path("db"), Path("spool"), 1234)
        finally:
            os.environ.pop("TOLLGATE_REDIS_URL", None)
            os.environ.pop("GEMINI_API_KEY", None)

        assert "TOLLGATE_REDIS_URL" not in env, (
            "the parent's Redis URL reached the subprocess -- AUDIT-010's exact "
            "mechanism"
        )
        assert "GEMINI_API_KEY" not in env
        assert env["TOLLGATE_SKIP_DOTENV"] == "1", (
            "without this the subprocess loads .env itself and is no more "
            "hermetic than before"
        )
        leaked = [k for k in env if k.startswith("TOLLGATE_")]
        assert sorted(leaked) == [
            "TOLLGATE_SKIP_DOTENV",
            "TOLLGATE_TEST_DB",
            "TOLLGATE_TEST_PORT",
            "TOLLGATE_TEST_SPOOL",
        ], f"unexpected TOLLGATE_* variables in the child environment: {leaked}"

    def test_an_explicit_backend_choice_is_passed_through(self):
        from tests.acceptance._scorer_process import hermetic_env

        env = hermetic_env(
            Path("db"), Path("spool"), 1234, extra_env={"TOLLGATE_REDIS_URL": "redis://x/9"}
        )
        assert env["TOLLGATE_REDIS_URL"] == "redis://x/9"


class TestRunnerResolvesConfigBeforeBuildingState:
    def test_load_env_file_precedes_build_default_in_the_test_runner(self):
        """F-C: `build_default()` reads TOLLGATE_REDIS_URL, so configuration
        must be resolved BEFORE it, not inside create_app()'s lifespan.

        Asserted over the AST rather than the raw text, so a comment mentioning
        either call cannot satisfy or break it.
        """
        tree = ast.parse(
            (REPO_ROOT / "scripts" / "_run_scorer_for_test.py").read_text(encoding="utf-8")
        )
        main = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
            None,
        )
        assert main is not None, "the runner has no main()"

        load_line = build_line = None
        for node in ast.walk(main):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "load_env_file":
                load_line = node.lineno if load_line is None else min(load_line, node.lineno)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "build_default"
                and isinstance(func.value, ast.Name)
                and func.value.id == "ScorerState"
            ):
                build_line = node.lineno if build_line is None else min(build_line, node.lineno)

        assert load_line is not None, "the runner never calls load_env_file()"
        assert build_line is not None, "the runner never calls ScorerState.build_default()"
        assert load_line < build_line, (
            "the runner still builds state before loading configuration -- its "
            "storage backend is decided by whatever the parent happened to have"
        )
