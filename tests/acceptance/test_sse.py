"""
Source: Implementation Plan v2.1 Day 1 acceptance test 14 -- a scored event
reaches the SSE stream.

Implementation note: this runs against a real subprocess (the same harness
used by test_durability.py) rather than the in-process TestClient. FastAPI's
TestClient drives the ASGI app through a single shared anyio portal thread,
and a long-lived streaming call there does not reliably interleave with a
second concurrent call on the same TestClient instance -- a real process on
a real socket has no such constraint and is what an SSE consumer actually
looks like in production anyway.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "_run_scorer_for_test.py"
SCHEMA_PATH = REPO_ROOT / "schema.sql"

VALID_BODY = {
    "event_id": "evt-sse-1", "card_hash": "card-sse-1", "bin": "411111",
    "amount_minor": 100, "currency": "INR",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_merchant(db_path: Path) -> str:
    raw_key = "test-key-sse"
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES ('m_sse', 'SSE Test', 'INR', 'Asia/Kolkata', ?, ?, 0)
            """,
            (hash_api_key(raw_key), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES ('m_sse', 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
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
def test_scored_event_reaches_sse_stream(tmp_path):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    raw_key = _seed_merchant(db_path)
    port = _free_port()

    proc = _spawn(db_path, spool_dir, port)
    try:
        _wait_for_health(port)

        received = []

        def _listen():
            with httpx.stream("GET", f"http://127.0.0.1:{port}/v1/stream", timeout=10.0) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        received.append(json.loads(line[len("data: "):]))
                        return

        listener = threading.Thread(target=_listen, daemon=True)
        listener.start()
        time.sleep(0.3)  # let the subscriber register before we publish

        resp = httpx.post(
            f"http://127.0.0.1:{port}/v1/score",
            headers={"X-Tollgate-Key": raw_key},
            json=VALID_BODY,
            timeout=2.0,
        )
        assert resp.status_code == 200
        attempt_uid = resp.json()["attempt_uid"]

        listener.join(timeout=5)
        assert received, "no SSE event was received"
        assert received[0]["attempt_uid"] == attempt_uid
    finally:
        proc.kill()
        proc.wait(timeout=10)
