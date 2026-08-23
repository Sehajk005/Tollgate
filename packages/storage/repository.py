"""
Source: Implementation Plan v2.1 Day 1 -- repository functions:
insert_attempt / insert_score / append_policy_config.

Every insert uses INSERT OR IGNORE keyed on a primary key that is the same
value across a restart (attempt_uid, a server-minted ULID) so the drainer's
replay-from-byte-0 recovery path (packages/storage/drainer.py) is always
idempotent, never duplicating a row already committed before a kill
(Backend Schema v2.1 §1, decisions 7-8).
"""

from __future__ import annotations

import json
import sqlite3

from packages.contracts.records import AttemptRecord, ScoreRecord


def insert_attempt(conn: sqlite3.Connection, record: AttemptRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO auth_attempt (
            attempt_uid, merchant_id, event_id, payload_digest, ingest_time,
            client_ts, session_id, card_hash, bin, last4, exp_month, exp_year,
            amount_minor, currency, ip, asn, ua_class, ipua_key, client_evidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.attempt_uid, record.merchant_id, record.event_id, record.payload_digest,
            record.ingest_time, record.client_ts, record.session_id, record.card_hash,
            record.bin, record.last4, record.exp_month, record.exp_year,
            record.amount_minor, record.currency, record.ip, record.asn,
            record.ua_class, record.ipua_key, record.client_evidence,
        ),
    )


def insert_score(conn: sqlite3.Connection, record: ScoreRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO attempt_score (
            attempt_uid, score_raw, score_calibrated, prior_used, regime, decision,
            tier_ladder, control_arm, shed, model_version, calibrator_version,
            policy_version, rules_fired, feature_snapshot, top_contributors,
            incident_id, latency_ms, scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.attempt_uid, record.score_raw, record.score_calibrated,
            record.prior_used, record.regime, record.decision, record.tier_ladder,
            record.control_arm, record.shed, record.model_version,
            record.calibrator_version, record.policy_version,
            json.dumps(record.rules_fired), json.dumps(record.feature_snapshot),
            record.top_contributors, record.incident_id, record.latency_ms,
            record.scored_at,
        ),
    )


def append_policy_config(
    conn: sqlite3.Connection,
    merchant_id: str,
    thresholds: dict,
    rules_config: dict,
    *,
    created_at: int,
    hysteresis_gap: float = 0.08,
    cooldown_seconds: int = 300,
    cusum_rho: float = 5.0,
    cusum_h: float = 5.0,
    cusum_bucket_s: int = 10,
    drift_window_s: int = 1800,
    allow_auto_block: bool = False,
    auto_ceiling: str = "challenge",
    k_max_entities: int = 10,
    control_fraction: float = 0.05,
) -> int:
    """
    Source: Implementation Plan v2.1 Day 1 acceptance test 9 -- writing
    policy_config twice creates two version rows, never an update. This
    function only ever INSERTs a new version; there is no UPDATE path.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS max_version FROM policy_config WHERE merchant_id = ?",
        (merchant_id,),
    ).fetchone()
    next_version = row["max_version"] + 1
    conn.execute(
        """
        INSERT INTO policy_config (
            merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
            cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
            auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            merchant_id, next_version, json.dumps(thresholds), hysteresis_gap,
            cooldown_seconds, cusum_rho, cusum_h, cusum_bucket_s, drift_window_s,
            allow_auto_block, auto_ceiling, k_max_entities, control_fraction,
            json.dumps(rules_config), created_at,
        ),
    )
    conn.commit()
    return next_version


def get_latest_policy_version(conn: sqlite3.Connection, merchant_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM policy_config WHERE merchant_id = ?",
        (merchant_id,),
    ).fetchone()
    return row["v"]
