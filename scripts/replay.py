"""
python -m scripts.replay --tier easy --seed 42 --speed 0 --out FILE
    [--hours 3] [--epoch-ms 0]

Source: Day-2 Plan §G -- "scripts/replay.py is a CLI over the same driver
for --speed 0 (Schema §9 step 5, the Day-5 training substrate)". Also used
manually by the Day-2 exit gate (§M item 5) to demonstrate M6: speed=0 and
speed=60 runs produce byte-identical published-event output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from packages.storage.db import initialize_schema
from services.scorer.deps import DEMO_MERCHANT_ID, ScorerState
from services.scorer.replay import ReplayRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


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
    parser.add_argument("--tier", choices=["easy", "hard"], required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--speed", type=int, default=0)
    parser.add_argument("--hours", type=int, default=3)
    parser.add_argument("--epoch-ms", dest="epoch_ms", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tollgate.db"
        spool_dir = Path(tmp) / "spool"
        initialize_schema(db_path, SCHEMA_PATH)
        state = ScorerState.build_default(db_path=db_path, spool_dir=spool_dir)

        request = ReplayRequest(
            tier=args.tier, seed=args.seed, speed=args.speed, epoch_ms=args.epoch_ms, hours=args.hours,
        )
        events = asyncio.run(_run_and_collect(state, request))
        state.spool.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")

    print(f"wrote {len(events)} events -> {args.out}")


if __name__ == "__main__":
    main()
