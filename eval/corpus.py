"""
Source: Day-5 Plan Step 2 -- seams S1 (run construction with identity), S2
(a PERSISTENT corpus replay covering negative controls), S4 (a
feature_snapshot reader).

Day 4 built runs inline in `harness.build_full_dataset` and threw away which
run each sample came from; `scripts/replay.py` replayed into a
`TemporaryDirectory` and never drained. Day 5 needs the exact logged
`attempt_score.feature_snapshot` vectors as a training corpus, joined back to
`attempt_label.is_attack`. This module:

  * `build_runs(seed)`          -- the ONE construction (12 sequentially-epoched
                                   tier blocks + 7 negative-control scenarios),
                                   now carrying run identity. `build_full_dataset`
                                   delegates here, so the corpus and the dataset
                                   cannot drift.
  * `replay_corpus(runs, ...)`  -- per run: a fresh ScorerState (fresh
                                   InMemoryWindowStore) + a per-run merchant_id,
                                   driven through the EXISTING injected-stream
                                   parameter of ReplayDriver.run(), then
                                   Drainer.drain_from_start() + load_truth().
  * `load_feature_corpus(conn)` -- reads the persisted vectors back, projected
                                   by FEATURE_NAMES and coerced to float.

One merchant per run (`m-eval-{run_index:02d}`) simultaneously fixes the
colliding-`event_id` join ambiguity (stream.py restarts at "e-0000000" per
run), the overlapping negative-control timelines (they carry no epoch_ms), and
gives each run the window isolation the simulator assumed when it generated
each stream independently. Window keys are already merchant-scoped
(keys.py::window_key -> tg:{merchant_id}:...), so nothing in keys.py,
compute.py or the driver changes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from packages.features.compute import FEATURE_NAMES
from packages.simulator.generate import build_negative_stream, build_stream
from packages.simulator.negative import SCENARIOS
from packages.simulator.stream import SimulatorOutput

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

MS_PER_HOUR = 3_600_000
# Source: eval/harness.py -- BLOCK_HOURS / N_BLOCKS_PER_TIER. build_runs()
# replicates build_full_dataset:173-193 exactly so Sample ordering and content
# are unchanged from Day 4.
DEFAULT_HOURS = 3
DEFAULT_N_BLOCKS_PER_TIER = 4
_TIERS: Tuple[str, ...] = ("easy", "medium", "hard")


@dataclass(frozen=True)
class CorpusRun:
    """One simulator run plus the identity that lets its samples be joined
    back to the persisted feature corpus."""

    run_index: int
    merchant_id: str          # f"m-eval-{run_index:02d}"
    stream_tier: Optional[str]  # "easy"|"medium"|"hard" for tier blocks, None for scenarios
    scenario: Optional[str]     # negative-control scenario name, None for tier blocks
    output: SimulatorOutput
    epoch_ms: int              # the epoch already baked into output.events' t_ms


@dataclass(frozen=True)
class FeatureRow:
    attempt_uid: str
    ingest_time: int
    x: Tuple[float, ...]       # len == 24, ordered by FEATURE_NAMES
    rule_score_raw: float      # attempt_score.score_raw at decision time -- this IS B0


@dataclass(frozen=True)
class CorpusReplayResult:
    db_path: Path
    n_runs: int
    n_attempts: int
    n_labels_written: int
    n_episodes_written: int
    merchant_ids: Tuple[str, ...]


def _merchant_id(run_index: int) -> str:
    return f"m-eval-{run_index:02d}"


def run_index_of(merchant_id: str) -> int:
    """Inverse of `_merchant_id` -- f"m-eval-05" -> 5."""
    return int(merchant_id.rsplit("-", 1)[-1])


def build_runs(
    seed: int, *, hours: int = DEFAULT_HOURS, n_blocks_per_tier: int = DEFAULT_N_BLOCKS_PER_TIER,
) -> List[CorpusRun]:
    """
    The loop currently inlined in `harness.build_full_dataset` (12
    sequentially-epoched tier blocks + one run per negative-control scenario),
    now returning run identity. `epoch_ms` is passed to `build_stream` exactly
    as Day 4 did, so `output.events` carry the shift and Sample ordering /
    content are byte-identical -- which is what keeps test_splits.py and
    run_all()'s train counts unchanged.
    """
    runs: List[CorpusRun] = []
    run_index = 0
    block_i = 0
    for _ in range(n_blocks_per_tier):
        for tier in _TIERS:
            epoch_ms = block_i * hours * MS_PER_HOUR
            output = build_stream(seed=seed + block_i, tier=tier, hours=hours, epoch_ms=epoch_ms)
            runs.append(CorpusRun(
                run_index=run_index, merchant_id=_merchant_id(run_index),
                stream_tier=tier, scenario=None, output=output, epoch_ms=epoch_ms,
            ))
            run_index += 1
            block_i += 1
    for scenario in SCENARIOS:
        output = build_negative_stream(seed=seed, scenario=scenario, hours=hours)
        runs.append(CorpusRun(
            run_index=run_index, merchant_id=_merchant_id(run_index),
            stream_tier=None, scenario=scenario, output=output, epoch_ms=0,
        ))
        run_index += 1
    return runs


def _connect(db_path: Path) -> sqlite3.Connection:
    from packages.storage.db import connect  # local: keep packages.storage off the module import graph

    return connect(db_path)


def _seed_eval_merchant(conn: sqlite3.Connection, merchant_id: str) -> None:
    """
    A small local helper: tests/conftest.py::seed_merchant cannot be imported
    (test_oracle_isolation.py forbids production code importing tests/), and
    scripts/seed_merchant.py mints a real API key we do not need. The replay
    path never authenticates, so placeholder key hashes are fine. policy_config
    version 1 mirrors tests/conftest.py's minimal insert.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO merchant (
            merchant_id, display_name, currency, timezone,
            api_key_hash, outcome_hmac_key_hash, created_at
        ) VALUES (?, 'Eval corpus merchant', 'INR', 'Asia/Kolkata', 'eval-corpus', 'eval-corpus', 0)
        """,
        (merchant_id,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO policy_config (
            merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
            cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
            auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
        ) VALUES (?, 1, '{}', 0.08, 300, 5.0, 5.0, 10, 1800, 0,
                  'challenge', 10, 0.05, '{}', 0)
        """,
        (merchant_id,),
    )
    conn.commit()


def _replay_one(run: CorpusRun, *, db_path: Path, spool_dir: Path) -> int:
    """Replay one run through the identical scoring core, drain it, load its
    truth. Returns the number of attempts scored."""
    import asyncio
    import random

    from packages.clock.clock import SystemClock
    from packages.clock.ids import UlidGenerator
    from packages.detect.rules import DayOneRules
    from packages.features.memory_store import InMemoryWindowStore
    from packages.storage.bus import InProcessEventBus
    from packages.storage.drainer import Drainer
    from packages.storage.spool import Spool
    from services.scorer.deps import ScorerState
    from services.scorer.replay import ReplayDriver, ReplayRequest

    from eval.load import load_truth

    run_spool_dir = spool_dir / f"run-{run.run_index:02d}"

    # Redis must be off: the corpus is bit-reproducible and Day-5's time-travel
    # test recomputes against the same backend (Day-5 Plan Step 2).
    window_store = InMemoryWindowStore()
    clock = SystemClock()  # unused for timing -- the driver installs its own VirtualClock
    ulid = UlidGenerator(clock=clock, rng=random.Random(f"corpus:ulid:{run.run_index}"))
    spool = Spool(run_spool_dir)
    drainer = Drainer(db_path=db_path, spool_path=spool.path)
    state = ScorerState(
        clock=clock, ulid=ulid, window_store=window_store, rules=DayOneRules(window_store),
        spool=spool, drainer=drainer, event_bus=InProcessEventBus(), db_path=db_path,
    )
    assert isinstance(state.window_store, InMemoryWindowStore), (
        "replay_corpus requires InMemoryWindowStore (unset TOLLGATE_REDIS_URL) for a "
        "bit-reproducible corpus"
    )

    conn = _connect(db_path)
    try:
        _seed_eval_merchant(conn, run.merchant_id)
    finally:
        conn.close()

    driver = ReplayDriver(state, merchant_id=run.merchant_id)
    # epoch_ms=0: the events already carry their block epoch (build_runs passes
    # it to build_stream), so ingest_time == event.t_ms == Sample.t_ms. seed is
    # per-run so attempt_uid ULIDs never collide across runs.
    request = ReplayRequest(
        tier=run.stream_tier or "n/a", seed=10_000 + run.run_index, speed=0, epoch_ms=0,
    )
    asyncio.run(driver.run(request, stream=list(run.output.events)))

    spool.close()
    n_attempts = drainer.drain_from_start()

    conn = _connect(db_path)
    try:
        load_truth(conn, run.merchant_id, [(run.stream_tier, run.output)])
    finally:
        conn.close()
    return n_attempts


def replay_corpus(
    runs: List[CorpusRun], *, db_path: Path, spool_dir: Path, rebuild: bool = True,
) -> CorpusReplayResult:
    """
    Replay every run in `runs` (tier blocks AND negative controls) into a
    PERSISTENT SQLite DB, in run order, each on its own merchant + fresh
    window store. When `rebuild` is True the DB and spool dir are wiped first
    so the corpus is deterministic; when False an existing DB is reused as-is.
    """
    from packages.storage.db import initialize_schema

    db_path = Path(db_path)
    spool_dir = Path(spool_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if rebuild:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        if spool_dir.exists():
            import shutil

            shutil.rmtree(spool_dir)

    if not db_path.exists():
        initialize_schema(db_path, SCHEMA_PATH)

    spool_dir.mkdir(parents=True, exist_ok=True)

    total_attempts = 0
    for run in runs:
        total_attempts += _replay_one(run, db_path=db_path, spool_dir=spool_dir)

    conn = _connect(db_path)
    try:
        n_labels = conn.execute("SELECT COUNT(*) AS c FROM attempt_label").fetchone()["c"]
        n_episodes = conn.execute("SELECT COUNT(*) AS c FROM episode_truth").fetchone()["c"]
    finally:
        conn.close()

    return CorpusReplayResult(
        db_path=db_path, n_runs=len(runs), n_attempts=total_attempts,
        n_labels_written=n_labels, n_episodes_written=n_episodes,
        merchant_ids=tuple(r.merchant_id for r in runs),
    )


_CORPUS_QUERY = """
SELECT a.merchant_id AS merchant_id, a.event_id AS event_id, a.attempt_uid AS attempt_uid,
       a.ingest_time AS ingest_time, s.feature_snapshot AS feature_snapshot, s.score_raw AS score_raw
FROM auth_attempt a JOIN attempt_score s ON a.attempt_uid = s.attempt_uid
"""


def load_feature_corpus(conn: sqlite3.Connection) -> Dict[Tuple[int, str], FeatureRow]:
    """
    Read every persisted `attempt_score.feature_snapshot` back, projected by
    FEATURE_NAMES (the stored dict has 27 keys -- the 24 plus
    `distinct_cards_per_ip_5m`, `trusted`, `baseline_coverage`, and
    `degraded_reason` when set -- Day-5 Plan fact #2) and coerced to float.
    Keyed by (run_index, event_id); event_id is only unique within a run.
    Raises on a missing key -- a shape drift must fail loudly, not silently
    substitute a zero.
    """
    corpus: Dict[Tuple[int, str], FeatureRow] = {}
    for row in conn.execute(_CORPUS_QUERY):
        run_index = run_index_of(row["merchant_id"])
        snapshot = json.loads(row["feature_snapshot"])
        x = tuple(float(snapshot[name]) for name in FEATURE_NAMES)  # KeyError on drift -- intended
        corpus[(run_index, row["event_id"])] = FeatureRow(
            attempt_uid=row["attempt_uid"],
            ingest_time=int(row["ingest_time"]),
            x=x,
            rule_score_raw=float(row["score_raw"]),
        )
    return corpus
