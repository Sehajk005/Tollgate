"""
Source: Implementation Plan v2.1 Day 1 acceptance test 10 -- spool-always
durability. "Every attempt that received a 200 response is present in
SQLite exactly once after restart" (decisions.md, decision 8); boundary is
process death, not power loss (decision 9).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "_run_scorer_for_test.py"
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_merchant(db_path: Path) -> str:
    raw_key = "test-key-durability"
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES ('m_dur', 'Durability Test', 'INR', 'Asia/Kolkata', ?, ?, 0)
            """,
            (hash_api_key(raw_key), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES ('m_dur', 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
                      'challenge', 10, 0.05, '{}', 0)
            """
        )
        conn.commit()
    finally:
        conn.close()
    return raw_key


def _wait_for_health(port: int, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError("scorer did not become healthy in time")


def _spawn(db_path: Path, spool_dir: Path, port: int) -> subprocess.Popen:
    full_env = dict(os.environ)
    full_env["TOLLGATE_TEST_DB"] = str(db_path)
    full_env["TOLLGATE_TEST_SPOOL"] = str(spool_dir)
    full_env["TOLLGATE_TEST_PORT"] = str(port)
    return subprocess.Popen(
        [sys.executable, str(RUNNER)],
        env=full_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.mark.slow
def test_acknowledged_attempts_survive_hard_kill_exactly_once(tmp_path):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    raw_key = _seed_merchant(db_path)
    port = _free_port()

    proc = _spawn(db_path, spool_dir, port)
    try:
        _wait_for_health(port)

        acknowledged = []
        for i in range(15):
            resp = httpx.post(
                f"http://127.0.0.1:{port}/v1/score",
                headers={"X-Tollgate-Key": raw_key},
                json={
                    "event_id": f"evt-{i}", "card_hash": f"card-{i}", "bin": "411111",
                    "amount_minor": 100, "currency": "INR",
                },
                timeout=2.0,
            )
            assert resp.status_code == 200
            acknowledged.append(resp.json()["attempt_uid"])

        # No graceful shutdown -- a hard kill mid-drain, not a clean stop.
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    # Restart: a fresh process drains the surviving spool from byte 0 before
    # accepting traffic (Backend Schema v2.1 section 1).
    port2 = _free_port()
    proc2 = _spawn(db_path, spool_dir, port2)
    try:
        _wait_for_health(port2)
        time.sleep(0.3)  # let the background drainer's first pass settle
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT attempt_uid, COUNT(*) as n FROM auth_attempt GROUP BY attempt_uid"
        ).fetchall()
        by_uid = {row["attempt_uid"]: row["n"] for row in rows}

        score_rows = conn.execute(
            "SELECT attempt_uid, COUNT(*) as n FROM attempt_score GROUP BY attempt_uid"
        ).fetchall()
        score_by_uid = {row["attempt_uid"]: row["n"] for row in score_rows}
    finally:
        conn.close()

    for uid in acknowledged:
        assert by_uid.get(uid) == 1, f"{uid}: expected exactly 1 auth_attempt row, got {by_uid.get(uid)}"
        assert score_by_uid.get(uid) == 1, f"{uid}: expected exactly 1 attempt_score row, got {score_by_uid.get(uid)}"
