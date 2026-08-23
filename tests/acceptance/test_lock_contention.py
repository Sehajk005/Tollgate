"""
Source: Implementation Plan v2.1 Day 1 acceptance test 11 -- read-only
evaluation/rebuild can coexist with writer activity without `database is
locked`, exercised concurrently, not just declared via WAL mode.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from packages.storage.db import connect, initialize_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def test_readonly_connection_coexists_with_concurrent_writer(tmp_path):
    db_path = tmp_path / "tollgate.db"
    initialize_schema(db_path, SCHEMA_PATH)

    write_conn = connect(db_path)
    write_conn.execute(
        """
        INSERT INTO merchant (
            merchant_id, display_name, currency, timezone,
            api_key_hash, outcome_hmac_key_hash, created_at
        ) VALUES ('m1', 'Test', 'INR', 'Asia/Kolkata', 'h1', 'h2', 0)
        """
    )
    write_conn.commit()
    write_conn.close()

    errors = []
    stop = threading.Event()

    def writer_loop():
        n = 0
        conn = connect(db_path)
        try:
            while not stop.is_set():
                conn.execute(
                    """
                    INSERT INTO policy_config (
                        merchant_id, version, thresholds, hysteresis_gap,
                        cooldown_seconds, cusum_rho, cusum_h, cusum_bucket_s,
                        drift_window_s, allow_auto_block, auto_ceiling,
                        k_max_entities, control_fraction, rules_config, created_at
                    ) VALUES ('m1', ?, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
                              'challenge', 10, 0.05, '{}', ?)
                    """,
                    (n + 1, n),
                )
                conn.commit()
                n += 1
                time.sleep(0.005)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            conn.close()

    def reader_loop():
        try:
            for _ in range(50):
                conn = connect(db_path, read_only=True)
                try:
                    conn.execute("SELECT COUNT(*) FROM policy_config").fetchone()
                finally:
                    conn.close()
                time.sleep(0.005)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    writer_thread = threading.Thread(target=writer_loop)
    writer_thread.start()
    reader_loop()
    stop.set()
    writer_thread.join(timeout=5)

    locked_errors = [
        e for e in errors
        if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower()
    ]
    assert not locked_errors, f"database is locked occurred: {locked_errors}"
    assert not errors, f"unexpected errors during concurrent access: {errors}"
