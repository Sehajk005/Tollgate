"""
Source: Day-4 Plan (rev. 2) Step 10 -- eval/load.py, first cut (see §9).
`load_truth(conn, merchant_id, runs)` -- **idempotent** (F14):
`episode_truth.episode_id` is a PRIMARY KEY and Eval Protocol §9 requires
regenerating every number from `--seed` in one command, i.e. re-running.
Uses `INSERT ... ON CONFLICT(episode_id) DO UPDATE`; same for
`attempt_label` on `attempt_uid`.

`attempt_label.attempt_uid` FKs `auth_attempt` (Decision 32), populated
only by a replay -- writes `episode_truth` unconditionally and
`attempt_label` only for events with an existing `auth_attempt` row
(matched by `merchant_id` + `event_id`, the same pair `ix_attempt_event_id`
indexes), counting skips.

Timestamps follow the existing convention (`services/scorer/scoring.py`:
`ingest_time=ingest_ms`) -- raw integer milliseconds stored directly into
the TIMESTAMP columns, not converted to an ISO string.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from packages.simulator.stream import SimulatorOutput


@dataclass(frozen=True)
class LoadResult:
    episodes_written: int
    labels_written: int
    labels_skipped_no_attempt: int


def load_truth(
    conn: sqlite3.Connection, merchant_id: str, runs: Sequence[Tuple[Optional[str], SimulatorOutput]],
) -> LoadResult:
    episodes_written = 0
    labels_written = 0
    labels_skipped = 0

    for _stream_tier, output in runs:
        for episode in output.episodes:
            conn.execute(
                """
                INSERT INTO episode_truth
                    (episode_id, kind, tier, scenario, started_at, ended_at,
                     attempt_count, distinct_cards, generator_seed, evasion_params)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    kind = excluded.kind, tier = excluded.tier, scenario = excluded.scenario,
                    started_at = excluded.started_at, ended_at = excluded.ended_at,
                    attempt_count = excluded.attempt_count, distinct_cards = excluded.distinct_cards,
                    generator_seed = excluded.generator_seed, evasion_params = excluded.evasion_params
                """,
                (
                    episode.episode_id, episode.kind, episode.tier, episode.scenario,
                    episode.started_at, episode.ended_at, episode.attempt_count,
                    episode.distinct_cards, episode.generator_seed,
                    json.dumps(episode.evasion_params) if episode.evasion_params is not None else None,
                ),
            )
            episodes_written += 1

        for label in output.labels:
            row = conn.execute(
                "SELECT attempt_uid FROM auth_attempt WHERE merchant_id = ? AND event_id = ?",
                (merchant_id, label.event_id),
            ).fetchone()
            if row is None:
                labels_skipped += 1
                continue
            attempt_uid = row["attempt_uid"] if isinstance(row, sqlite3.Row) else row[0]
            conn.execute(
                """
                INSERT INTO attempt_label (attempt_uid, is_attack, episode_id, entity_overlap, source)
                VALUES (?, ?, ?, 0, 'simulator')
                ON CONFLICT(attempt_uid) DO UPDATE SET
                    is_attack = excluded.is_attack, episode_id = excluded.episode_id,
                    entity_overlap = excluded.entity_overlap, source = excluded.source
                """,
                (attempt_uid, label.is_attack, label.episode_id),
            )
            labels_written += 1

    conn.commit()
    return LoadResult(
        episodes_written=episodes_written, labels_written=labels_written, labels_skipped_no_attempt=labels_skipped,
    )
