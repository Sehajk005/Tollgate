"""
python -m scripts.replay --tier easy --seed 42 --speed 0 --out FILE
    [--hours 3] [--epoch-ms 0] [--db data/corpus/replay.db] [--keep-db]

Source: Day-2 Plan §G -- "scripts/replay.py is a CLI over the same driver
for --speed 0 (Schema §9 step 5, the Day-5 training substrate)". Also used
manually by the Day-2 exit gate (§M item 5) to demonstrate M6: speed=0 and
speed=60 runs produce byte-identical published-event output.

Day-5 Plan §8: `--db PATH` persists the SQLite DB (and drains the spool, so
`attempt_score.feature_snapshot` rows land) instead of discarding it in a
TemporaryDirectory -- Impl Plan's literal "scripts/replay --speed 0 ->
feature_snapshot corpus". `--keep-db` (without `--db`) persists to
data/corpus/replay-<tier>.db. For the FULL multi-run training corpus use
`python -m scripts.train_l1 --rebuild-corpus` (eval/corpus.replay_corpus).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import tempfile
from pathlib import Path

from packages.storage.db import connect, initialize_schema
from services.scorer.deps import DEMO_MERCHANT_ID, ScorerState
from services.scorer.replay import ReplayRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def _ensure_demo_merchant(db_path: Path) -> None:
    """Minimal merchant + policy_config v1 so the drainer's auth_attempt FK
    passes. (scripts/seed_merchant.py mints a real API key we do not need here.)"""
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'Replay demo', 'INR', 'Asia/Kolkata', 'replay', 'replay', 0)",
            (DEMO_MERCHANT_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO policy_config (merchant_id, version, thresholds, hysteresis_gap, "
            "cooldown_seconds, cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block, "
            "auto_ceiling, k_max_entities, control_fraction, rules_config, created_at) "
            "VALUES (?, 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0, 'challenge', 10, 0.05, '{}', 0)",
            (DEMO_MERCHANT_ID,),
        )
        conn.commit()
    finally:
        conn.close()


async def _run_and_collect(state: ScorerState, request: ReplayRequest) -> list:
    events = []

    async def _listen():
        async for event in state.event_bus.subscribe():
            events.append(event)

    listener = asyncio.create_task(_listen())
    await asyncio.sleep(0)

    driver = state.replay_driver
    await driver.run(request)

    await asyncio.sleep(0)  # let the listener drain whatever is already queued
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        pass
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=["easy", "medium", "hard"], required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--speed", type=int, default=0)
    parser.add_argument("--hours", type=int, default=3)
    parser.add_argument("--epoch-ms", dest="epoch_ms", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None, help="JSONL of published SSE events")
    parser.add_argument(
        "--db", type=Path, default=None,
        help="persist the SQLite corpus here and drain the spool (feature_snapshot rows land)",
    )
    parser.add_argument(
        "--keep-db", dest="keep_db", action="store_true",
        help="without --db, persist to data/corpus/replay-<tier>.db instead of a temp dir",
    )
    args = parser.parse_args()

    persist_db = args.db
    if persist_db is None and args.keep_db:
        persist_db = REPO_ROOT / "data" / "corpus" / f"replay-{args.tier}.db"

    tmp_ctx = tempfile.TemporaryDirectory() if persist_db is None else contextlib.nullcontext()
    with tmp_ctx as tmp:
        if persist_db is not None:
            persist_db.parent.mkdir(parents=True, exist_ok=True)
            db_path = persist_db
            spool_dir = persist_db.parent / f"spool-{args.tier}"
            if not db_path.exists():
                initialize_schema(db_path, SCHEMA_PATH)
            _ensure_demo_merchant(db_path)
        else:
            db_path = Path(tmp) / "tollgate.db"
            spool_dir = Path(tmp) / "spool"
            initialize_schema(db_path, SCHEMA_PATH)

        # A non-existent model_dir keeps the persisted corpus rules-only and
        # deterministic regardless of whether models/ is populated -- the
        # feature_snapshot itself is model-independent either way.
        state = ScorerState.build_default(
            db_path=db_path, spool_dir=spool_dir, model_dir=db_path.parent / "__no_models__",
        )

        request = ReplayRequest(
            tier=args.tier, seed=args.seed, speed=args.speed, epoch_ms=args.epoch_ms, hours=args.hours,
        )
        events = asyncio.run(_run_and_collect(state, request))
        state.spool.close()

        n_rows = 0
        if persist_db is not None:
            n_rows = state.drainer.drain_from_start()

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for event in events:
                fh.write(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        print(f"wrote {len(events)} events -> {args.out}")

    if persist_db is not None:
        print(f"drained {n_rows} attempt rows -> {persist_db}")
    elif args.out is None:
        print(f"replayed {len(events)} events (no --out / --db given)")


if __name__ == "__main__":
    main()
