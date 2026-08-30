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

import hashlib
import json
import sqlite3
import time
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


# ---------------------------------------------------------------------------
# Source: Day-5 Plan Step 10 -- the first real per-tier `eval_run` rows.
# `eval_run` has existed in schema.sql since Day 1 with zero rows; this is
# its writer. No schema migration: `build_hash` and the calibration/audit
# blocks live inside the `metrics` JSON because `eval_run` has no such column.
# ---------------------------------------------------------------------------

REPO_ROOT_FROM_LOAD = None  # set lazily to avoid an import at module load


def _recall_json(recall) -> Optional[dict]:
    if recall is None:
        return None
    return {
        "value": recall.value, "n_neg": recall.n_neg, "resolvable": recall.resolvable,
        "ci_low": recall.ci_low, "ci_high": recall.ci_high,
    }


def _tier_metrics_json(tm) -> Optional[dict]:
    if tm is None:
        return None
    return {
        "n": tm.n,
        "prevalence": tm.prevalence,
        "recall_at_target_fpr": _recall_json(tm.recall_at_target_fpr),
        "ap_raw": tm.ap_raw,
        "ap_at_eval_prevalence": tm.ap_at_eval_prevalence,
    }


def _fixture_sha256() -> str:
    from eval.provenance import FIXTURE_SHA_PATH, _sha_file_first_token

    return _sha_file_first_token(FIXTURE_SHA_PATH)


def write_eval_run(
    conn: sqlite3.Connection,
    *,
    report,
    seed: int,
    model_version: str,
    calibrator_version: str,
    prior_assumed: float,
    artifacts_path,
    extra_metrics: Optional[dict] = None,
    tier_e_metrics=None,
) -> str:
    """
    Write one `eval_run` row for `report` (an eval.harness.Report). Idempotent:
    `run_id` is a deterministic digest of (config_hash, build_hash,
    model_version, split_name, seed), so re-running the same command updates
    the same row rather than inserting a duplicate -- Eval Protocol §9's
    "regenerates every number from --seed in one command".
    """
    from eval.provenance import build_hash

    prov = report.provenance
    bh = build_hash()
    run_id = hashlib.sha256(
        "\x00".join([prov.config_hash, bh, model_version, report.split_name, str(seed)]).encode("utf-8")
    ).hexdigest()

    metrics = {
        "build_hash": bh,
        "model_version": model_version,
        "calibrator_version": calibrator_version,
        "overall": {
            "n": report.n,
            "n_positive": report.n_positive,
            "prevalence": report.prevalence,
            "recall_at_target_fpr": _recall_json(report.recall_at_target_fpr),
            "ap_raw": report.ap_raw,
            "ap_at_eval_prevalence": report.ap_at_eval_prevalence,
            "roc_auc": report.roc_auc_value,
        },
        "per_tier": {
            tier: _tier_metrics_json(report.tier_breakdown.get(tier))
            for tier in ("easy", "medium", "hard")
        },
        "clean": _tier_metrics_json(report.clean_breakdown),
    }
    # Source: Day-7 Plan §6 -- `evasive` is added ONLY when Tier E is available
    # (from the dedicated tier_e split, passed in, or already on this report's
    # breakdown). A cut Tier E leaves the 3-tier per_tier shape untouched, so
    # test_eval_run_row.py's unedited form still passes.
    _evasive_tm = tier_e_metrics if tier_e_metrics is not None else report.tier_breakdown.get("evasive")
    if _evasive_tm is not None:
        metrics["per_tier"]["evasive"] = _tier_metrics_json(_evasive_tm)
    if extra_metrics:
        metrics.update(extra_metrics)

    conn.execute(
        """
        INSERT INTO eval_run (
            run_id, created_at, model_version, calibrator_version, policy_version,
            split_name, prior_assumed, eval_prevalence, config_hash, fixture_sha256,
            stream_seed, metrics, artifacts_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            model_version = excluded.model_version,
            calibrator_version = excluded.calibrator_version,
            policy_version = excluded.policy_version,
            split_name = excluded.split_name,
            prior_assumed = excluded.prior_assumed,
            eval_prevalence = excluded.eval_prevalence,
            config_hash = excluded.config_hash,
            fixture_sha256 = excluded.fixture_sha256,
            stream_seed = excluded.stream_seed,
            metrics = excluded.metrics,
            artifacts_path = excluded.artifacts_path
        """,
        (
            run_id, int(time.time() * 1000), model_version, calibrator_version, prov.policy_version,
            report.split_name, float(prior_assumed), float(prov.eval_prevalence), prov.config_hash,
            _fixture_sha256(), int(seed), json.dumps(metrics, sort_keys=True), str(artifacts_path),
        ),
    )
    conn.commit()
    return run_id
