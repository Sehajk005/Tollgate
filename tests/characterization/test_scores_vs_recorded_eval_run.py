"""
Source: Day-5 Plan §7 (Characterization) / Impl Plan §5:466 -- "Day 5 scores
vs recorded eval_run", the Day-5 rung of the bisection ladder. Recomputes the
l1-lgbm-v1 per-tier metrics on `temporal_test` and compares them to a
committed snapshot. A drift here is a PROMPT to look (regenerate the
snapshot, or find the regression), never a gate -- `characterization` marker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.corpus import build_runs, load_feature_corpus
from eval.cost import load_cost_model
from eval.dataset import build_dataset, compute_entity_overlap, temporal_split
from eval.metrics import ap_at_prevalence, average_precision, recall_at_fpr, roc_auc
from packages.detect.calibrate import Calibrator, serving_prior
from packages.detect.model import Layer1Model
from packages.storage.db import connect

pytestmark = pytest.mark.characterization

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "day5_eval_run_snapshot.json"
SEED = 42
ABS_TOL = 0.02


def _fresh_metrics(day5_corpus, day5_model):
    model = Layer1Model.load(Path(day5_model))
    calib = Calibrator.load(Path(day5_model) / "platt-v1.json")
    cm = load_cost_model()
    pi_s = serving_prior("in_control", cm)
    runs = build_runs(SEED)
    conn = connect(day5_corpus)
    try:
        features = load_feature_corpus(conn)
    finally:
        conn.close()
    samples = compute_entity_overlap(build_dataset([(r.stream_tier, r.output) for r in runs]))
    _, te = temporal_split(samples, train_fraction=0.7)

    def score(s):
        fr = features[(s.run_index, s.event_id)]
        return calib.apply(model.margin(fr.x), pi_s)

    rows = [(s, score(s)) for s in te.samples if (s.run_index, s.event_id) in features]
    scores = [sc for _, sc in rows]
    labels = [s.is_attack for s, _ in rows]
    out = {
        "overall": {
            "n": len(rows), "n_positive": sum(labels),
            "prevalence": sum(labels) / len(rows),
            "ap_raw": average_precision(scores, labels),
            "ap_at_eval_prevalence": ap_at_prevalence(scores, labels, cm.eval_prevalence),
            "roc_auc": roc_auc(scores, labels),
        },
        "per_tier": {},
    }
    for tier in ("easy", "medium", "hard"):
        idx = [i for i, (s, _) in enumerate(rows) if s.stream_tier == tier]
        if not idx:
            out["per_tier"][tier] = None
            continue
        ts = [scores[i] for i in idx]
        tl = [labels[i] for i in idx]
        r = recall_at_fpr(ts, tl, cm.target_fpr)
        out["per_tier"][tier] = {
            "n": len(idx), "prevalence": sum(tl) / len(idx),
            "ap_raw": average_precision(ts, tl),
            "recall_at_target_fpr": None if r is None else r.value,
        }
    return out


def _close(a, b, tol=ABS_TOL):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


class TestScoresVsRecordedEvalRun:
    def test_per_tier_metrics_match_the_committed_snapshot(self, day5_corpus, day5_model):
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        fresh = _fresh_metrics(day5_corpus, day5_model)

        drift = []
        for k in ("prevalence", "ap_raw", "ap_at_eval_prevalence", "roc_auc"):
            if not _close(fresh["overall"][k], snap["overall"][k]):
                drift.append(f"overall.{k}: fresh={fresh['overall'][k]} snapshot={snap['overall'][k]}")
        assert fresh["overall"]["n"] == snap["overall"]["n"], (
            "temporal_test size changed -- corpus/splits drifted"
        )

        for tier in ("easy", "medium", "hard"):
            f, s = fresh["per_tier"][tier], snap["per_tier"][tier]
            assert (f is None) == (s is None), f"{tier}: presence changed"
            if f is None:
                continue
            assert f["n"] == s["n"], f"{tier}: n changed {f['n']} vs {s['n']}"
            for k in ("prevalence", "ap_raw", "recall_at_target_fpr"):
                if not _close(f[k], s[k]):
                    drift.append(f"{tier}.{k}: fresh={f[k]} snapshot={s[k]}")

        assert not drift, (
            "Day-5 per-tier metrics drifted from the committed snapshot (regenerate "
            "tests/fixtures/day5_eval_run_snapshot.json or investigate):\n  " + "\n  ".join(drift)
        )
