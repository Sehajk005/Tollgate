"""
Source: Day-2 Plan §I acceptance test A16 -- the whole Day-2 claim, end to
end, against a real scorer subprocess (same harness pattern as
tests/acceptance/test_sse.py and test_durability.py, per Decision 22).
`/v1/replay/*` does not exist yet (Day-2 Step 7-9); this fails with a
connection/404 error until then, which is an honest failure of a real
expectation, not an assertion on a fabricated constant.
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_merchant(db_path: Path) -> str:
    raw_key = "test-key-day2-e2e"
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES ('m_e2e', 'Day2 E2E Test', 'INR', 'Asia/Kolkata', ?, ?, 0)
            """,
            (hash_api_key(raw_key), hash_api_key("outcome-secret")),
        )
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES ('m_e2e', 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
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
def test_launch_easy_replay_drives_rules_decisions_and_threat_band_end_to_end(tmp_path):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    initialize_schema(db_path, SCHEMA_PATH)
    raw_key = _seed_merchant(db_path)
    port = _free_port()

    proc = _spawn(db_path, spool_dir, port)
    try:
        _wait_for_health(port)

        received = []
        stop_listening = threading.Event()

        def _listen():
            try:
                with httpx.stream("GET", f"http://127.0.0.1:{port}/v1/stream", timeout=30.0) as resp:
                    for line in resp.iter_lines():
                        if stop_listening.is_set():
                            return
                        if not line or not line.startswith("data: "):
                            continue
                        received.append(json.loads(line[len("data: "):]))
            except httpx.HTTPError:
                # The scorer subprocess is force-killed in the outer test's
                # `finally` block, which tears down this connection out from
                # under an in-flight read -- expected on shutdown, not a bug.
                return

        listener = threading.Thread(target=_listen, daemon=True)
        listener.start()
        time.sleep(0.3)  # let the subscriber register before the replay starts

        # Source: Day-2 Plan §G -- POST /v1/replay/start, API-key authed like
        # /v1/score, speed=0 for a fast deterministic test run (no wall pacing).
        start_resp = httpx.post(
            f"http://127.0.0.1:{port}/v1/replay/start",
            headers={"X-Tollgate-Key": raw_key},
            json={"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0},
            timeout=5.0,
        )
        assert start_resp.status_code == 202, f"unexpected status: {start_resp.status_code} {start_resp.text}"

        # Poll GET /v1/replay/status until the replay finishes.
        deadline = time.time() + 30.0
        final_status = None
        while time.time() < deadline:
            status_resp = httpx.get(f"http://127.0.0.1:{port}/v1/replay/status", timeout=2.0)
            assert status_resp.status_code == 200
            body = status_resp.json()
            if body.get("state") == "finished":
                final_status = body
                break
            time.sleep(0.2)
        assert final_status is not None, "replay did not reach 'finished' state within 30s"

        time.sleep(0.5)  # let the last few SSE events and the drainer settle
        stop_listening.set()

        assert received, "no events were received on /v1/stream during replay"

        # Source: Day-2 Plan §M exit gate -- "R1/R2/R3 fire on real feature
        # counts... rules_fired non-empty, asserted".
        all_rules_fired = set()
        for event in received:
            all_rules_fired.update(event.get("rules_fired") or [])
        expected_rule_names = {"attempts_per_ip_60s", "distinct_cards_per_ip_5m", "distinct_cards_per_bin_5m"}
        assert all_rules_fired & expected_rule_names, (
            f"none of R1/R2/R3 fired during the easy-tier replay; saw rules: {all_rules_fired}"
        )

        decisions_seen = {event.get("decision") for event in received}
        assert "challenge" in decisions_seen, f"expected at least one 'challenge' decision, saw: {decisions_seen}"

        # Source: Day-2 Plan §M exit gate -- "the threat band moves CALM ->
        # ELEVATED -> UNDER ATTACK, driven by threat_state on the SSE event".
        threat_states_in_order = [event.get("threat_state") for event in received if event.get("threat_state")]
        assert "calm" in threat_states_in_order, f"threat_state never observed as calm: {threat_states_in_order[:10]}"
        assert "under_attack" in threat_states_in_order, (
            f"threat_state never reached under_attack: {threat_states_in_order}"
        )
        first_calm = threat_states_in_order.index("calm")
        first_under_attack = threat_states_in_order.index("under_attack")
        assert first_calm < first_under_attack, "threat_state reached under_attack before ever being calm"
    finally:
        proc.kill()
        proc.wait(timeout=10)

    # Source: Day-2 Plan §M exit gate -- "after drain the SQLite attempt_score
    # rows carry the same decisions". The drainer is a daemon thread inside
    # the now-killed process; re-run drain_from_start in this process against
    # the same db/spool to make the post-drain assertion deterministic
    # rather than racing the killed subprocess's own drainer.
    from packages.storage.drainer import Drainer  # noqa: PLC0415

    Drainer(db_path=db_path, spool_path=spool_dir / "attempts-active.jsonl").drain_from_start()

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT decision, COUNT(*) AS n FROM attempt_score GROUP BY decision"
        ).fetchall()
    finally:
        conn.close()
    decisions_in_db = {row["decision"] for row in rows}
    assert "challenge" in decisions_in_db, (
        f"expected a 'challenge' row in attempt_score after drain, saw: {decisions_in_db}"
    )
