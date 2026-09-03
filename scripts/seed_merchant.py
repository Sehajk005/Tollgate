"""
python -m scripts.seed_merchant

Source: Backend Schema v2 section 9 -- bootstrap step 2 (merchant + baseline
+ config v1). Day 1 scope: creates the merchant row, a fresh API key
(printed once, never stored raw), and policy_config version 1 seeded from
config/rules.yaml.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import yaml

from packages.clock.clock import SystemClock
from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key

# Day 9 Plan Phase 2: the Compose bootstrap points this at the demo DB on a
# Linux-native volume (TOLLGATE_DB_PATH). Unset -> "tollgate.db", as before.
DB_PATH = Path(os.environ.get("TOLLGATE_DB_PATH", "tollgate.db"))
SCHEMA_PATH = Path("schema.sql")
RULES_CONFIG_PATH = Path("config/rules.yaml")
MERCHANT_ID = "merchant_demo"


def main() -> None:
    if not DB_PATH.exists():
        initialize_schema(DB_PATH, SCHEMA_PATH)

    clock = SystemClock()
    now_ms = clock.now_ms()

    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    # Day-7 Plan §4 Step 5 -- the outcome HMAC secret was previously generated
    # and thrown away. POST /v1/outcome now BINDS TOLLGATE_OUTCOME_SECRET to
    # this merchant by comparing hash_api_key(secret) against the stored hash,
    # so the raw secret must be printed once (like the API key) and set in the
    # scorer's environment as TOLLGATE_OUTCOME_SECRET.
    raw_outcome_secret = secrets.token_urlsafe(32)
    outcome_secret_hash = hash_api_key(raw_outcome_secret)

    rules_config = yaml.safe_load(RULES_CONFIG_PATH.read_text(encoding="utf-8"))

    conn = connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO merchant (
                merchant_id, display_name, currency, timezone,
                api_key_hash, outcome_hmac_key_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MERCHANT_ID, "Kesar & Co. (demo)", "INR", "Asia/Kolkata",
                key_hash, outcome_secret_hash, now_ms,
            ),
        )
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM policy_config WHERE merchant_id = ?",
            (MERCHANT_ID,),
        ).fetchone()
        next_version = row["v"] + 1
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MERCHANT_ID, next_version, json.dumps({}), 0.08, 300,
                5.0, 5.0, 10, 1800, False,
                "challenge", 10, 0.05, json.dumps(rules_config), now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Merchant seeded: {MERCHANT_ID}")
    print(f"API key (store this; it is not recoverable): {raw_key}")
    print(
        "Outcome HMAC secret (store this; it is not recoverable) -- set it as "
        f"TOLLGATE_OUTCOME_SECRET for POST /v1/outcome: {raw_outcome_secret}"
    )
    print(f"policy_config version: {next_version}")


if __name__ == "__main__":
    main()
