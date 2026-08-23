"""
Source: Implementation Plan v2.1 Day 1 acceptance test 9 -- writing
policy_config twice creates two version rows, never an update.
"""

from __future__ import annotations

from packages.storage.db import connect
from packages.storage.repository import append_policy_config


def test_writing_policy_config_twice_creates_two_version_rows(tmp_workspace):
    db_path, _ = tmp_workspace
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES ('m1', 'Test', 'INR', 'Asia/Kolkata', 'hash-a', 'hash-b', 0)
            """
        )
        conn.commit()

        v1 = append_policy_config(
            conn, "m1", thresholds={"a": 1}, rules_config={"r": 1}, created_at=0,
        )
        v2 = append_policy_config(
            conn, "m1", thresholds={"a": 2}, rules_config={"r": 2}, created_at=1,
        )

        assert v1 == 1
        assert v2 == 2

        rows = conn.execute(
            "SELECT version, thresholds FROM policy_config WHERE merchant_id = ? ORDER BY version",
            ("m1",),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["version"] == 1
        assert rows[1]["version"] == 2
        # The first row must be untouched by the second write -- never an update.
        assert '"a": 1' in rows[0]["thresholds"]
        assert '"a": 2' in rows[1]["thresholds"]
    finally:
        conn.close()
