"""
Shared builders for the Day-6 integration acceptance tests (NOT a test
module -- the leading underscore keeps pytest from collecting it). Assembles
a ScorerState with Layer 2 + policy loaded from a seeded tmp DB, and drives
score_attempt through the injected-stream replay seam.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import List, Optional

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.detect.rules import DayOneRules
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.bus import InProcessEventBus
from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import Drainer
from packages.storage.spool import Spool
from services.scorer.deps import ScorerState
from services.scorer.scoring import score_attempt

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

TIER_LADDER = {
    "throttle": 0.06474820143884892,
    "challenge": 0.2571428571428571,
    "step_up": 0.5094339622641509,
    "block": 0.8737864077669902,
}


def make_db(tmp_path: Path) -> Path:
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    db = Path(tmp_path) / "day6.db"
    initialize_schema(db, SCHEMA_PATH)
    return db


def seed_merchant(db_path: Path, merchant_id: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'day6', 'INR', 'Asia/Kolkata', 'k', 'k', 0)",
            (merchant_id,),
        )
        conn.commit()
    finally:
        conn.close()


def seed_policy(
    db_path: Path,
    merchant_id: str,
    *,
    version: int = 1,
    thresholds: Optional[dict] = None,
    cusum_h: float = 3.0,
    cooldown_seconds: int = 300,
    k_max_entities: int = 10,
    control_fraction: float = 0.0,
    auto_ceiling: str = "challenge",
    hysteresis_gap: float = 0.08,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, ?, ?, ?, ?, 5.0, ?, 10, 1800, 0, ?, ?, ?, '{}', 0)
            """,
            (
                merchant_id, version, json.dumps(thresholds or TIER_LADDER), hysteresis_gap,
                cooldown_seconds, cusum_h, auto_ceiling, k_max_entities, control_fraction,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_baseline(
    db_path: Path,
    merchant_id: str,
    *,
    hourly_rate: float = 60.0,
    flagged_rate_mean: float = 1.0,
    q30m: Optional[list] = None,
    q5m: Optional[list] = None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO store_baseline (
                merchant_id, hourly_volume_profile, decline_rate_mean, decline_rate_std,
                amount_p05_minor, amount_p50_minor, amount_p95_minor, bin_entropy_mean,
                bin_entropy_std, foreign_bin_share_mean, foreign_bin_share_std,
                cards_per_ip_quantiles, flagged_rate_mean, sample_count, is_stable, updated_at
            ) VALUES (?, ?, 0, 0, 100, 500, 2000, 0, 0, 0, 0, ?, ?, 100, 0, 0)
            """,
            (
                merchant_id,
                json.dumps([hourly_rate] * 24),
                json.dumps({
                    "5m": q5m or [1, 1, 1, 1, 1, 2, 2, 3, 4, 5, 10],
                    "30m": q30m or [1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 12],
                }),
                flagged_rate_mean,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def build_state(db_path: Path, spool_dir: Path, merchant_id: str) -> ScorerState:
    window_store = InMemoryWindowStore()
    spool = Spool(spool_dir)
    drainer = Drainer(db_path=db_path, spool_path=spool.path)
    policy, baseline, layer2, incidents, engine, ttl_ms = ScorerState._load_layer2(db_path, merchant_id)
    assert policy is not None, "Layer 2 did not load -- seed policy_config (thresholds) + store_baseline first"
    return ScorerState(
        clock=VirtualClock(epoch_ms=0),
        ulid=UlidGenerator(clock=VirtualClock(epoch_ms=0), rng=random.Random("day6")),
        window_store=window_store,
        rules=DayOneRules(window_store),
        spool=spool,
        drainer=drainer,
        event_bus=InProcessEventBus(),
        db_path=db_path,
        policy=policy, baseline=baseline, layer2=layer2, incidents=incidents,
        policy_engine=engine, enforcement_ttl_ms=ttl_ms,
        policy_versions={policy.version: policy},
    )


def score_stream(state: ScorerState, merchant_id: str, events: List[dict]) -> List[dict]:
    """events: [{t_ms, ip, card_hash, bin, amount_minor?, event_id?, session_id?}].
    Returns the SSE event dict per attempt."""
    clock = VirtualClock(epoch_ms=0)
    ulid = UlidGenerator(clock=clock, rng=random.Random("day6-stream"))
    out: List[dict] = []

    async def _run():
        for i, ev in enumerate(events):
            clock.set_ms(ev["t_ms"])
            body = ScoreRequest(
                event_id=ev.get("event_id", f"e-{i:07d}"),
                card_hash=ev["card_hash"],
                bin=ev["bin"],
                amount_minor=ev.get("amount_minor", 1999),
                currency="INR",
                session_id=ev.get("session_id"),
            )
            _resp, event = await score_attempt(
                state, merchant_id=merchant_id, ip=ev["ip"], body=body, clock=clock, ulid=ulid,
            )
            out.append(event)

    asyncio.run(_run())
    return out


def drain(state: ScorerState) -> None:
    state.spool.close()
    state.drainer.drain_from_start()
