"""
Source: Day-5 Plan §7 test 9 -- AC 9 / Eval Protocol §9. The first real
per-tier `eval_run` rows. After `python -m eval.harness ... --write-eval-run`:
an `l1-lgbm-v1` row exists for `temporal_test` with every provenance field
non-null and meaningful, a per-tier metrics breakdown (easy/medium/hard, each
with its own prevalence), and idempotent re-runs (same `run_id`, no dup row).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import eval.harness as harness
from packages.storage.db import connect

SEED = 42


def _copy_corpus(src: Path, dst_dir: Path) -> Path:
    dst = dst_dir / "corpus.db"
    shutil.copyfile(src, dst)
    for suffix in ("-wal", "-shm"):
        s = Path(str(src) + suffix)
        if s.exists():
            shutil.copyfile(s, Path(str(dst) + suffix))
    # Start from a clean eval_run table -- the shared repo corpus may already
    # carry rows from a prior `python -m eval.harness --write-eval-run` run.
    conn = connect(dst)
    try:
        conn.execute("DELETE FROM eval_run")
        conn.commit()
    finally:
        conn.close()
    return dst


def _run_harness(corpus_db: Path, model_dir: Path, out_dir: Path, monkeypatch):
    import eval.provenance as provenance

    # Pin the git HEAD/dirty probe: this test exercises write_eval_run's
    # ON CONFLICT(run_id) idempotency, not build_hash's git integration
    # (test_config_hash.py covers that). Otherwise a concurrent suite that
    # transiently touches the working tree between the two runs would flip
    # `dirty` and produce a second run_id.
    monkeypatch.setattr(provenance, "_git_head_and_dirty", lambda repo_root: ("day5-test-head", False))
    argv = [
        "eval.harness", "--split", "all", "--seed", str(SEED),
        "--corpus-db", str(corpus_db), "--model-dir", str(model_dir),
        "--out", str(out_dir), "--write-eval-run",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    harness.main()


class TestEvalRunRow:
    def test_l1_lgbm_v1_row_on_temporal_test_is_complete_and_idempotent(
        self, day5_corpus, day5_model, tmp_path, monkeypatch
    ):
        corpus_db = _copy_corpus(Path(day5_corpus), tmp_path)
        _run_harness(corpus_db, Path(day5_model), tmp_path / "out1", monkeypatch)

        conn = connect(corpus_db)
        try:
            rows = conn.execute(
                "SELECT * FROM eval_run WHERE model_version = 'l1-lgbm-v1' AND split_name = 'temporal_test'"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1, f"expected exactly one l1-lgbm-v1/temporal_test eval_run row, got {len(rows)}"
        row = dict(rows[0])

        assert row["calibrator_version"] == "platt-v1"
        assert isinstance(row["policy_version"], int) and row["policy_version"] >= 1
        assert row["prior_assumed"] == 0.001, row["prior_assumed"]
        assert row["eval_prevalence"] == 0.01, row["eval_prevalence"]
        assert isinstance(row["config_hash"], str) and len(row["config_hash"]) == 64
        assert isinstance(row["fixture_sha256"], str) and len(row["fixture_sha256"]) == 64
        assert row["stream_seed"] == SEED
        assert row["artifacts_path"]

        metrics = json.loads(row["metrics"])
        assert set(metrics["per_tier"].keys()) == {"easy", "medium", "hard"}
        prevs = {}
        for tier, tm in metrics["per_tier"].items():
            assert tm is not None, f"per-tier metrics missing for {tier}"
            assert tm["n"] > 0 and 0.0 < tm["prevalence"] < 1.0, f"{tier}: n/prevalence not meaningful ({tm})"
            prevs[tier] = tm["prevalence"]
        assert len({round(p, 6) for p in prevs.values()}) > 1, (
            "per-tier prevalences are all identical -- the breakdown is not really per-tier"
        )
        assert "build_hash" in metrics and len(metrics["build_hash"]) == 64
        assert "calibration" in metrics and "audit_summary" in metrics

        first_run_id = row["run_id"]

        _run_harness(corpus_db, Path(day5_model), tmp_path / "out2", monkeypatch)
        conn = connect(corpus_db)
        try:
            rows2 = conn.execute(
                "SELECT run_id FROM eval_run WHERE model_version = 'l1-lgbm-v1' AND split_name = 'temporal_test'"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM eval_run").fetchone()[0]
        finally:
            conn.close()
        assert [r["run_id"] for r in rows2] == [first_run_id], "re-run changed or duplicated the run_id"
        assert total <= 4, f"re-run inserted duplicate eval_run rows (total={total})"
