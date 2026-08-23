"""
Source: Implementation Plan v2.1 Day 1 acceptance test 8 -- FK enforcement
actually works, not merely declared.
"""

from __future__ import annotations

import sqlite3

import pytest

from packages.storage.db import connect


def test_foreign_key_violation_is_actually_rejected(tmp_workspace):
    db_path, _ = tmp_workspace
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO attempt_score (
                    attempt_uid, score_raw, score_calibrated, prior_used, regime,
                    decision, tier_ladder, control_arm, shed, model_version,
                    calibrator_version, policy_version, rules_fired,
                    feature_snapshot, top_contributors, incident_id,
                    latency_ms, scored_at
                ) VALUES (
                    'nonexistent-attempt-uid', 0.1, 0.1, 0.001, 'in_control',
                    'allow', 'domestic', 0, 0, 'rules-only-v0',
                    'identity', 1, '[]', '{}', NULL, NULL, 5, 0
                )
                """
            )
            conn.commit()
    finally:
        conn.close()


def test_foreign_keys_pragma_is_actually_on_per_connection(tmp_workspace):
    db_path, _ = tmp_workspace
    conn = connect(db_path)
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_foreign_keys_pragma_is_on_for_readonly_connections_too(tmp_workspace):
    db_path, _ = tmp_workspace
    # A read-only connection must be openable at all (the DB must exist).
    conn = connect(db_path)
    conn.close()
    ro_conn = connect(db_path, read_only=True)
    try:
        row = ro_conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
    finally:
        ro_conn.close()
