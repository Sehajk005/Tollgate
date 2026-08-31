"""
Source: Implementation Plan v2.1 Day 1 -- repository functions:
insert_attempt / insert_score / append_policy_config.

Every insert uses INSERT OR IGNORE keyed on a primary key that is the same
value across a restart (attempt_uid, a server-minted ULID) so the drainer's
replay-from-byte-0 recovery path (packages/storage/drainer.py) is always
idempotent, never duplicating a row already committed before a kill
(Backend Schema v2.1 §1, decisions 7-8).

Day-6 Plan §3.4 -- the incident / entity / transition / enforcement writers
and the policy_config / store_baseline readers. The incident row is an
UPSERT (its state changes over the incident's life); transitions and
enforcement rows carry deterministic ids, so INSERT OR IGNORE keeps the
drainer's byte-0 re-drain idempotent -- the incident's final state is
re-derived by replaying its (ordered) transitions.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.detect.baseline import StoreBaseline
from packages.detect.policy import PolicySnapshot


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


def insert_outcome_nonce(conn: sqlite3.Connection, nonce: str, seen_at: int) -> None:
    """
    Source: Day-7 Plan §4 Step 5 -- `outcome_nonce.nonce` is a PRIMARY KEY, so
    a plain INSERT (NOT `OR IGNORE`) raises `sqlite3.IntegrityError` on a
    replay; the route turns that into 409. This is the replay guard.
    """
    conn.execute(
        "INSERT INTO outcome_nonce (nonce, seen_at) VALUES (?, ?)", (nonce, seen_at)
    )


def insert_auth_outcome(conn: sqlite3.Connection, row: dict) -> None:
    """
    Source: Day-7 Plan §4 Step 5 -- one row per scored attempt (attempt_uid
    PK). `INSERT OR IGNORE` keeps a second legitimately-signed report of the
    same outcome from crashing the route; the nonce guard above is what stops
    a replay. `sig_verified` is always 1 here -- the route only reaches this
    point after `hmac.compare_digest` succeeds.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO auth_outcome (
            attempt_uid, gateway_status, decline_code, gateway_latency_ms,
            auth_fee_minor, reached_gateway, sig_verified, ingest_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["attempt_uid"], row["gateway_status"], row.get("decline_code"),
            row.get("gateway_latency_ms"), row.get("auth_fee_minor"),
            int(bool(row["reached_gateway"])), int(bool(row.get("sig_verified", True))),
            row["ingest_time"],
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


# ---------------------------------------------------------------------------
# Day-6 Plan §3.4 -- incident / entity / transition / enforcement writers
# ---------------------------------------------------------------------------

_INCIDENT_COLS = (
    "incident_id", "merchant_id", "state", "detector", "opened_at", "escalated_at",
    "cooling_at", "closed_at", "peak_tier", "attempts_total", "attempts_before_alert",
    "cards_exposed_before_alert", "time_to_detect_s", "cusum_stat_at_alert", "decline_mix",
    "narrative", "narrative_source", "recommended_tier", "resolution", "resolved_by",
    "pinned_policy_version",
)


def upsert_incident(conn: sqlite3.Connection, row: dict) -> None:
    """State changes over an incident's life, so this is ON CONFLICT DO
    UPDATE, not INSERT OR IGNORE. The drainer's byte-0 re-drain replays every
    spool line in order, so the last write wins -- which is the final state."""
    placeholders = ", ".join("?" for _ in _INCIDENT_COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _INCIDENT_COLS if c != "incident_id")
    conn.execute(
        f"INSERT INTO incident ({', '.join(_INCIDENT_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(incident_id) DO UPDATE SET {updates}",
        tuple(row.get(c) for c in _INCIDENT_COLS),
    )


_ENTITY_COLS = (
    "incident_id", "entity_type", "entity_key", "pseudonym", "attempt_count",
    "first_seen", "last_seen",
)


def upsert_incident_entity(conn: sqlite3.Connection, row: dict) -> None:
    placeholders = ", ".join("?" for _ in _ENTITY_COLS)
    updates = ", ".join(
        f"{c}=excluded.{c}" for c in _ENTITY_COLS
        if c not in ("incident_id", "entity_type", "entity_key")
    )
    conn.execute(
        f"INSERT INTO incident_entity ({', '.join(_ENTITY_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(incident_id, entity_type, entity_key) DO UPDATE SET {updates}",
        tuple(row.get(c) for c in _ENTITY_COLS),
    )


def insert_tier_transition(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO tier_transition (
            transition_id, incident_id, from_tier, to_tier, trigger, signal_value, at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["transition_id"], row["incident_id"], row.get("from_tier"), row["to_tier"],
            row["trigger"], row.get("signal_value"), row["at"],
        ),
    )


def insert_enforcement_action(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO enforcement_action (
            action_id, incident_id, merchant_id, entity_type, entity_key, tier,
            requires_confirmation, confirmed_by, applied_at, expires_at, released_at, applied_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["action_id"], row.get("incident_id"), row["merchant_id"], row["entity_type"],
            row["entity_key"], row["tier"], int(bool(row.get("requires_confirmation"))),
            row.get("confirmed_by"), row.get("applied_at"), row["expires_at"],
            row.get("released_at"), row.get("applied_by", "auto"),
        ),
    )


def read_active_enforcement_count(conn: sqlite3.Connection, merchant_id: str) -> int:
    """Distinct (entity_type, entity_key) with an unreleased enforcement_action
    -- the K_max blast-radius count (Threat Model §4/P2). Not on the hot path:
    the serving path uses the in-process IncidentRegistry count; this reader
    is for tests and reporting."""
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT entity_type || ':' || entity_key) AS c
        FROM enforcement_action
        WHERE merchant_id = ? AND released_at IS NULL
        """,
        (merchant_id,),
    ).fetchone()
    return row["c"]


# ---------------------------------------------------------------------------
# Day-6 Plan §3.4 -- policy_config / store_baseline readers
# ---------------------------------------------------------------------------


def load_policy_config(
    conn: sqlite3.Connection, merchant_id: str, version: Optional[int] = None
) -> Optional[PolicySnapshot]:
    """Read one policy_config version (the latest when `version` is None) as
    a frozen PolicySnapshot. Returns None when the merchant has no row."""
    if version is None:
        row = conn.execute(
            "SELECT * FROM policy_config WHERE merchant_id = ? ORDER BY version DESC LIMIT 1",
            (merchant_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM policy_config WHERE merchant_id = ? AND version = ?",
            (merchant_id, version),
        ).fetchone()
    if row is None:
        return None
    return PolicySnapshot(
        version=int(row["version"]),
        thresholds=json.loads(row["thresholds"] or "{}"),
        hysteresis_gap=float(row["hysteresis_gap"]),
        cooldown_seconds=int(row["cooldown_seconds"]),
        cusum_rho=float(row["cusum_rho"]),
        cusum_h=float(row["cusum_h"]),
        cusum_bucket_s=int(row["cusum_bucket_s"]),
        drift_window_s=int(row["drift_window_s"]),
        allow_auto_block=bool(row["allow_auto_block"]),
        auto_ceiling=str(row["auto_ceiling"]),
        k_max_entities=int(row["k_max_entities"]),
        control_fraction=float(row["control_fraction"]),
        rules_config=json.loads(row["rules_config"] or "{}"),
    )


def load_store_baseline(conn: sqlite3.Connection, merchant_id: str) -> Optional[StoreBaseline]:
    row = conn.execute(
        "SELECT * FROM store_baseline WHERE merchant_id = ?", (merchant_id,)
    ).fetchone()
    if row is None:
        return None
    return StoreBaseline(
        merchant_id=merchant_id,
        hourly_volume_profile=tuple(json.loads(row["hourly_volume_profile"] or "[]")),
        flagged_rate_mean=float(row["flagged_rate_mean"]),
        cards_per_ip_quantiles=json.loads(row["cards_per_ip_quantiles"] or "{}"),
        is_stable=bool(row["is_stable"]),
        sample_count=int(row["sample_count"]),
    )
