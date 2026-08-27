-- Tollgate schema.sql
-- Source: 04-BACKEND-SCHEMA-v2.md. Shipped complete on Day 1 (decision K4 in
-- the Day 1 plan): there is no Alembic, so growing this table-by-table across
-- ten days would mean hand-rebuilding the DB daily. Tables not yet populated
-- by Day 1 code (incident*, episode_truth, eval_run, ...) still exist so the
-- FK-enforcement and policy-versioning acceptance tests exercise real
-- constraints from day one.
--
-- PRAGMA foreign_keys is NOT set here -- it is a per-connection setting, not a
-- database-file setting, and is applied by packages/storage/db.py on every
-- connection (including read-only ones).

-- ============================================================
-- 1. Configuration
-- ============================================================

CREATE TABLE IF NOT EXISTS merchant (
    merchant_id      TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    currency         TEXT NOT NULL DEFAULT 'INR',
    timezone         TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    api_key_hash     TEXT NOT NULL,
    outcome_hmac_key_hash TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS store_baseline (
    merchant_id           TEXT PRIMARY KEY REFERENCES merchant(merchant_id),
    hourly_volume_profile TEXT NOT NULL,
    decline_rate_mean     REAL NOT NULL,
    decline_rate_std      REAL NOT NULL,
    amount_p05_minor      INTEGER NOT NULL,
    amount_p50_minor      INTEGER NOT NULL,
    amount_p95_minor      INTEGER NOT NULL,
    bin_entropy_mean      REAL NOT NULL,
    bin_entropy_std       REAL NOT NULL,
    foreign_bin_share_mean REAL NOT NULL,
    foreign_bin_share_std  REAL NOT NULL,
    cards_per_ip_quantiles TEXT NOT NULL,
    flagged_rate_mean     REAL NOT NULL,
    sample_count          INTEGER NOT NULL DEFAULT 0,
    is_stable             BOOLEAN NOT NULL DEFAULT 0,
    updated_at            TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_config (
    merchant_id      TEXT NOT NULL REFERENCES merchant(merchant_id),
    version          INTEGER NOT NULL,
    thresholds       TEXT NOT NULL,
    hysteresis_gap   REAL NOT NULL DEFAULT 0.08,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    cusum_rho        REAL NOT NULL DEFAULT 5.0,
    cusum_h          REAL NOT NULL,
    cusum_bucket_s   INTEGER NOT NULL DEFAULT 10,
    drift_window_s   INTEGER NOT NULL DEFAULT 1800,
    allow_auto_block BOOLEAN NOT NULL DEFAULT 0,
    auto_ceiling     TEXT NOT NULL DEFAULT 'challenge',
    k_max_entities   INTEGER NOT NULL DEFAULT 10,
    control_fraction REAL NOT NULL DEFAULT 0.05,
    rules_config     TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (merchant_id, version)
);

CREATE TABLE IF NOT EXISTS cost_model_config (
    merchant_id            TEXT NOT NULL REFERENCES merchant(merchant_id),
    version                INTEGER NOT NULL,
    auth_fee_minor         INTEGER NOT NULL,
    downstream_exposure_minor INTEGER NOT NULL,
    aov_minor              INTEGER NOT NULL,
    margin_pct             REAL NOT NULL,
    abandonment_by_tier    TEXT NOT NULL,
    prior_steady_state     REAL NOT NULL DEFAULT 0.001,
    prior_under_attack     REAL NOT NULL DEFAULT 0.9,
    source_notes           TEXT NOT NULL,
    created_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (merchant_id, version)
);

-- ============================================================
-- 2. Event stream
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_attempt (
    attempt_uid         TEXT PRIMARY KEY,
    merchant_id         TEXT NOT NULL REFERENCES merchant(merchant_id),
    event_id            TEXT,
    payload_digest      TEXT NOT NULL,
    ingest_time         TIMESTAMP NOT NULL,
    client_ts           TIMESTAMP,
    session_id          TEXT,

    card_hash           TEXT NOT NULL,
    bin                 TEXT NOT NULL,
    last4               TEXT,
    exp_month           INTEGER,
    exp_year            INTEGER,

    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,

    ip                  TEXT,
    asn                 INTEGER,
    ua_class            TEXT,
    ipua_key            TEXT,

    client_evidence     TEXT
);

CREATE TABLE IF NOT EXISTS attempt_score (
    attempt_uid       TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    score_raw         REAL NOT NULL,
    score_calibrated  REAL NOT NULL,
    prior_used        REAL NOT NULL,
    regime            TEXT NOT NULL,
    decision          TEXT NOT NULL,
    tier_ladder       TEXT NOT NULL,
    control_arm       BOOLEAN NOT NULL DEFAULT 0,
    shed              BOOLEAN NOT NULL DEFAULT 0,
    model_version     TEXT NOT NULL,
    calibrator_version TEXT NOT NULL,
    policy_version    INTEGER NOT NULL,
    rules_fired       TEXT,
    feature_snapshot  TEXT NOT NULL,
    top_contributors  TEXT,
    incident_id       TEXT REFERENCES incident(incident_id),
    latency_ms        INTEGER NOT NULL,
    scored_at         TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_outcome (
    attempt_uid       TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    gateway_status    TEXT NOT NULL,
    decline_code      TEXT,
    gateway_latency_ms INTEGER,
    auth_fee_minor    INTEGER,
    reached_gateway   BOOLEAN NOT NULL,
    sig_verified      BOOLEAN NOT NULL,
    ingest_time       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS outcome_nonce (
    nonce       TEXT PRIMARY KEY,
    seen_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS bin_metadata (
    bin        TEXT PRIMARY KEY,
    issuer     TEXT,
    country    TEXT,
    is_foreign BOOLEAN NOT NULL,
    brand      TEXT,
    card_type  TEXT
);

-- ============================================================
-- 3. Incidents
-- ============================================================

CREATE TABLE IF NOT EXISTS incident (
    incident_id           TEXT PRIMARY KEY,
    merchant_id           TEXT NOT NULL REFERENCES merchant(merchant_id),
    state                 TEXT NOT NULL,
    detector              TEXT NOT NULL,
    opened_at             TIMESTAMP NOT NULL,
    escalated_at          TIMESTAMP,
    cooling_at            TIMESTAMP,
    closed_at             TIMESTAMP,

    peak_tier             TEXT NOT NULL,
    attempts_total        INTEGER NOT NULL DEFAULT 0,
    attempts_before_alert INTEGER,
    cards_exposed_before_alert INTEGER,
    time_to_detect_s      REAL,
    cusum_stat_at_alert   REAL,
    decline_mix           TEXT,

    narrative             TEXT,
    narrative_source      TEXT,
    recommended_tier      TEXT,

    resolution            TEXT,
    resolved_by           TEXT,
    pinned_policy_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS incident_entity (
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    entity_type   TEXT NOT NULL,
    entity_key    TEXT NOT NULL,
    pseudonym     TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    first_seen    TIMESTAMP NOT NULL,
    last_seen     TIMESTAMP NOT NULL,
    PRIMARY KEY (incident_id, entity_type, entity_key)
);

CREATE TABLE IF NOT EXISTS tier_transition (
    transition_id TEXT PRIMARY KEY,
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    from_tier     TEXT,
    to_tier       TEXT NOT NULL,
    trigger       TEXT NOT NULL,
    signal_value  REAL,
    at            TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS enforcement_action (
    action_id     TEXT PRIMARY KEY,
    incident_id   TEXT REFERENCES incident(incident_id),
    merchant_id   TEXT NOT NULL REFERENCES merchant(merchant_id),
    entity_type   TEXT NOT NULL,
    entity_key    TEXT NOT NULL,
    tier          TEXT NOT NULL,
    requires_confirmation BOOLEAN NOT NULL DEFAULT 0,
    confirmed_by  TEXT,
    applied_at    TIMESTAMP,
    expires_at    TIMESTAMP NOT NULL,
    released_at   TIMESTAMP,
    applied_by    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS narrator_call (
    call_id       TEXT PRIMARY KEY,
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    backend       TEXT NOT NULL,
    requested_at  TIMESTAMP NOT NULL,
    status        TEXT NOT NULL,
    latency_ms    INTEGER,
    fallback_used BOOLEAN NOT NULL DEFAULT 0
);

-- ============================================================
-- 4. Ground truth and evaluation
-- ============================================================

CREATE TABLE IF NOT EXISTS episode_truth (
    episode_id     TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    tier           TEXT,
    -- Source: Day-4 Plan (rev. 2) Step 3 -- schema-canonical negative-
    -- control scenario names (Backend Schema v2 §3.2's spelling; resolves
    -- the six-vs-seven scenario vocabulary fork, F17). NULL for attack-tier
    -- episodes (kind='attack').
    scenario       TEXT CHECK (scenario IS NULL OR scenario IN (
                       'flash_sale', 'corporate_nat', 'cgnat', 'retry_storm',
                       'subscription_batch', 'nri_traffic', 'shared_ip_legit'
                   )),
    started_at     TIMESTAMP NOT NULL,
    ended_at       TIMESTAMP NOT NULL,
    attempt_count  INTEGER NOT NULL,
    distinct_cards INTEGER NOT NULL,
    generator_seed INTEGER NOT NULL,
    evasion_params TEXT
);

CREATE TABLE IF NOT EXISTS attempt_label (
    attempt_uid TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    is_attack   BOOLEAN NOT NULL,
    episode_id  TEXT REFERENCES episode_truth(episode_id),
    entity_overlap BOOLEAN NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'simulator'
);

CREATE TABLE IF NOT EXISTS eval_run (
    run_id         TEXT PRIMARY KEY,
    created_at     TIMESTAMP NOT NULL,
    model_version  TEXT NOT NULL,
    calibrator_version TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    split_name     TEXT NOT NULL,
    prior_assumed  REAL NOT NULL,
    eval_prevalence REAL NOT NULL,
    config_hash    TEXT NOT NULL,
    fixture_sha256 TEXT NOT NULL,
    stream_seed    INTEGER NOT NULL,
    metrics        TEXT NOT NULL,
    artifacts_path TEXT NOT NULL
);

-- ============================================================
-- 5. Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS ix_attempt_merchant_ing  ON auth_attempt(merchant_id, ingest_time DESC);
CREATE INDEX IF NOT EXISTS ix_attempt_ip_ing        ON auth_attempt(ip, ingest_time DESC);
CREATE INDEX IF NOT EXISTS ix_attempt_bin_ing       ON auth_attempt(bin, ingest_time DESC);
CREATE INDEX IF NOT EXISTS ix_attempt_card_ing      ON auth_attempt(card_hash, ingest_time DESC);
CREATE INDEX IF NOT EXISTS ix_attempt_event_id      ON auth_attempt(merchant_id, event_id);
CREATE INDEX IF NOT EXISTS ix_score_incident        ON attempt_score(incident_id);
CREATE INDEX IF NOT EXISTS ix_score_control_arm     ON attempt_score(control_arm, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_incident_state        ON incident(merchant_id, state, opened_at DESC);
CREATE INDEX IF NOT EXISTS ix_entity_lookup         ON incident_entity(entity_type, entity_key);
CREATE INDEX IF NOT EXISTS ix_enforce_active        ON enforcement_action(entity_type, entity_key, released_at);
CREATE INDEX IF NOT EXISTS ix_label_episode         ON attempt_label(episode_id);
