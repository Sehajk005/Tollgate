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


def insert_narrator_call(conn: sqlite3.Connection, row: dict) -> None:
    """Source: Day-8 Plan Step 9 -- ONE row per narration ATTEMPT (every
    dispatch, successful or failed). `call_id` is the PK, so `INSERT OR IGNORE`
    keeps the drainer's byte-0 re-drain idempotent. `narrator_call.incident_id`
    is NOT NULL (schema.sql:232), which is why the reading is per-narration-
    attempt, not per-scored-attempt -- recorded in Decisions.md."""
    conn.execute(
        """
        INSERT OR IGNORE INTO narrator_call (
            call_id, incident_id, backend, requested_at, status, latency_ms, fallback_used
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["call_id"], row["incident_id"], row["backend"], row["requested_at"],
            row["status"], row.get("latency_ms"), int(bool(row.get("fallback_used"))),
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


# ---------------------------------------------------------------------------
# Day-8 Plan Step 6 -- D3 incident read model + confirm / resolve writers.
#
# The read model recomputes NOTHING: every field already exists in SQLite. The
# two writes are direct (not spooled): the spool exists to protect the SCORING
# path's durability, and a synchronous operator action must be visible on the
# next read, not 50 ms later. Timestamps are integer epoch ms (the repo
# convention -- `auth_attempt.ingest_time`, `eval_run.created_at`).
# ---------------------------------------------------------------------------

# entity_type -> the auth_attempt column its entity_key matches, for the
# newest-client-evidence lookup (Day-6 Plan §3.5 entity scoping).
_ENTITY_MATCH_COL = {"ip": "ip", "ipua": "ipua_key", "bin": "bin", "card": "card_hash"}


def _truncate_key(entity_type: str, entity_key: str) -> str:
    """UIUX v2 §6.8 -- pseudonyms PLUS a truncated real key; never a PAN, never
    a full card hash. An `ip` / `bin` key is short and shown as-is; a `card`
    (or any long) key is truncated to 8 chars + ellipsis."""
    if entity_type in ("ip", "bin") and len(entity_key) <= 18:
        return entity_key
    return entity_key[:8] + "…" if len(entity_key) > 8 else entity_key


def read_open_incidents(
    conn: sqlite3.Connection, merchant_id: str, state: str = "live"
) -> list:
    """Newest-first incidents for the merchant -- drives the nav's Incidents
    item (which routes straight to D3 for the newest).

    `state`: "live" (default, non-CLOSED) / "closed" / "all". DEF-D9-006: the
    HTTP `?state=` filter used to be dropped; it is honoured here now. The
    caller validates the value (route Literal), so an unknown value falls
    through to the "live" predicate rather than raising.
    """
    where = {
        "live": "AND state != 'CLOSED'",
        "closed": "AND state = 'CLOSED'",
        "all": "",
    }.get(state, "AND state != 'CLOSED'")
    rows = conn.execute(
        f"""
        SELECT incident_id, state, detector, opened_at, peak_tier
        FROM incident
        WHERE merchant_id = ? {where}
        ORDER BY opened_at DESC
        """,
        (merchant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def read_incident_detail(
    conn: sqlite3.Connection, incident_id: str, *, merchant_id: Optional[str] = None
) -> Optional[dict]:
    """The full D3 read model for one incident. Returns None when the incident
    does not exist (or does not belong to `merchant_id`, when given)."""
    inc = conn.execute(
        "SELECT * FROM incident WHERE incident_id = ?", (incident_id,)
    ).fetchone()
    if inc is None:
        return None
    if merchant_id is not None and inc["merchant_id"] != merchant_id:
        return None
    inc = dict(inc)

    entity_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT entity_type, entity_key, pseudonym, attempt_count, first_seen, last_seen "
            "FROM incident_entity WHERE incident_id = ?",
            (incident_id,),
        ).fetchall()
    ]
    entities = [
        {
            "pseudonym": r["pseudonym"],
            "entity_type": r["entity_type"],
            "entity_key_truncated": _truncate_key(r["entity_type"], r["entity_key"]),
            "attempt_count": r["attempt_count"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
        }
        for r in entity_rows
    ]

    transitions = [
        dict(r)
        for r in conn.execute(
            "SELECT from_tier, to_tier, trigger, signal_value, at "
            "FROM tier_transition WHERE incident_id = ? ORDER BY at ASC, transition_id ASC",
            (incident_id,),
        ).fetchall()
    ]

    actions = [
        dict(r)
        for r in conn.execute(
            "SELECT action_id, entity_type, entity_key, tier, requires_confirmation, "
            "confirmed_by, applied_at, expires_at, released_at, applied_by "
            "FROM enforcement_action WHERE incident_id = ? ORDER BY tier",
            (incident_id,),
        ).fetchall()
    ]
    for a in actions:
        a["entity_key_truncated"] = _truncate_key(a["entity_type"], a.pop("entity_key"))

    contrib_row = conn.execute(
        "SELECT top_contributors FROM attempt_score "
        "WHERE incident_id = ? AND top_contributors IS NOT NULL "
        "ORDER BY scored_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    try:
        top_contributors = json.loads(contrib_row["top_contributors"]) if contrib_row else []
    except (TypeError, ValueError):
        top_contributors = []

    # proposed vs in-force (Day-6 Plan §3.6 / App Flow §5 D3). `peak_tier` is
    # the proposed peak (may exceed the auto-ceiling); the in-force tier is the
    # most recent decision actually applied to an attempt on this incident.
    inforce_row = conn.execute(
        "SELECT decision FROM attempt_score WHERE incident_id = ? "
        "ORDER BY scored_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    in_force_tier = inforce_row["decision"] if inforce_row else "challenge"

    # newest client-asserted evidence from an attempt on this incident's entity
    client_evidence = None
    for r in entity_rows:
        col = _ENTITY_MATCH_COL.get(r["entity_type"])
        if col is None:
            continue
        ev = conn.execute(
            f"SELECT client_evidence, ingest_time FROM auth_attempt "  # noqa: S608 -- col from a fixed allowlist
            f"WHERE {col} = ? ORDER BY ingest_time DESC LIMIT 1",
            (r["entity_key"],),
        ).fetchone()
        if ev is not None and ev["client_evidence"]:
            try:
                blob = json.loads(ev["client_evidence"])
            except (TypeError, ValueError):
                blob = {}
            ua = str(blob.get("user_agent", ""))[:60]  # inert text, 60-char cap (§6.9)
            client_evidence = {"user_agent": ua, "observed_at": ev["ingest_time"]}
            break

    return {
        "incident": {
            "incident_id": inc["incident_id"],
            "state": inc["state"],
            "detector": inc["detector"],
            "opened_at": inc["opened_at"],
            "escalated_at": inc["escalated_at"],
            "cooling_at": inc["cooling_at"],
            "closed_at": inc["closed_at"],
            "peak_tier": inc["peak_tier"],
            "proposed_tier": inc["peak_tier"],
            "in_force_tier": in_force_tier,
            "attempts_total": inc["attempts_total"],
            "attempts_before_alert": inc["attempts_before_alert"],
            "cards_exposed_before_alert": inc["cards_exposed_before_alert"],
            "time_to_detect_s": inc["time_to_detect_s"],
            "narrative": inc["narrative"],
            "resolution": inc["resolution"],
            "resolved_by": inc["resolved_by"],
            "pinned_policy_version": inc["pinned_policy_version"],
        },
        "entities": entities,
        "timeline": transitions,
        "enforcement": actions,
        "contributions": top_contributors,
        "client_evidence": client_evidence,
    }


def confirm_enforcement_action(
    conn: sqlite3.Connection, action_id: str, confirmed_by: str, applied_at: int
) -> int:
    """UPDATE (not INSERT OR IGNORE -- `insert_enforcement_action` structurally
    cannot express a confirmation). Flips `requires_confirmation -> 0` and
    records who/when. Returns the number of rows changed (0 if unknown)."""
    cur = conn.execute(
        "UPDATE enforcement_action "
        "SET requires_confirmation = 0, confirmed_by = ?, applied_at = ? "
        "WHERE action_id = ?",
        (confirmed_by, applied_at, action_id),
    )
    conn.commit()
    return cur.rowcount


def release_enforcement_for_incident(
    conn: sqlite3.Connection, incident_id: str, released_at: int
) -> int:
    """Mark every still-active enforcement row for the incident released. This
    is App Flow J4 -- "enforcement released immediately"."""
    cur = conn.execute(
        "UPDATE enforcement_action SET released_at = ? "
        "WHERE incident_id = ? AND released_at IS NULL",
        (released_at, incident_id),
    )
    conn.commit()
    return cur.rowcount


def resolve_incident(
    conn: sqlite3.Connection,
    incident_id: str,
    resolution: str,
    resolved_by: str,
    closed_at: int,
) -> int:
    """Close the incident with an operator resolution (App Flow J4). CLOSED is
    terminal in the state machine; this is the operator-driven path to it."""
    cur = conn.execute(
        "UPDATE incident "
        "SET resolution = ?, resolved_by = ?, closed_at = ?, state = 'CLOSED' "
        "WHERE incident_id = ?",
        (resolution, resolved_by, closed_at, incident_id),
    )
    conn.commit()
    return cur.rowcount


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
