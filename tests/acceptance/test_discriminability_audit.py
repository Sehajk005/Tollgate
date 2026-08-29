"""
Source: Day-5 Plan §7 test 4 -- AC 3 / Eval Protocol §4/V2. The discriminability
audit runs over the REAL easy+medium training-set columns; every feature not
already in `config/features.yaml:audit.excluded` must sit at or below the flag
threshold, and every excluded feature must carry a recorded reason and its
measured AUC. Non-vacuous: it recomputes `univariate_auc` from the corpus, not
just reads `models/audit.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from eval.corpus import build_runs, load_feature_corpus
from eval.dataset import (
    build_dataset,
    compute_entity_overlap,
    exclude_negative_controls,
    temporal_split,
)
from packages.features.compute import FEATURE_NAMES
from packages.storage.db import connect
from scripts.train_l1 import _matrix, run_audit

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURES_YAML = REPO_ROOT / "config" / "features.yaml"
SEED = 42


def _features_config() -> dict:
    raw = yaml.safe_load(FEATURES_YAML.read_text(encoding="utf-8"))
    excluded = {e["name"]: e for e in (raw["audit"].get("excluded") or [])}
    return {
        "max_univariate_auc": float(raw["audit"]["max_univariate_auc"]["value"]),
        "excluded": excluded,
    }


def _recomputed_audit(day5_corpus: Path):
    runs = build_runs(SEED)
    conn = connect(day5_corpus)
    try:
        features = load_feature_corpus(conn)
    finally:
        conn.close()
    samples = compute_entity_overlap(build_dataset([(r.stream_tier, r.output) for r in runs]))
    temporal_train, _ = temporal_split(samples, train_fraction=0.7)
    train = exclude_negative_controls(temporal_train)
    train_samples = [s for s in train.samples if s.stream_tier in ("easy", "medium")]
    x, y = _matrix(train_samples, features, ())
    cfg = _features_config()
    excluded = {
        k: {"reason": v.get("reason", ""), "measured_auc": v.get("measured_auc")}
        for k, v in cfg["excluded"].items()
    }
    return run_audit(x, y, {"max_univariate_auc": cfg["max_univariate_auc"], "excluded": excluded})


class TestDiscriminabilityAudit:
    def test_all_24_features_appear_in_the_audit(self, day5_model):
        audit = json.loads((Path(day5_model) / "audit.json").read_text(encoding="utf-8"))
        assert set(audit["features"].keys()) == set(FEATURE_NAMES)
        assert len(audit["features"]) == 24

    def test_no_unlisted_feature_exceeds_the_threshold(self, day5_corpus):
        cfg = _features_config()
        audit, newly_flagged = _recomputed_audit(day5_corpus)
        assert not newly_flagged, (
            "a feature over the univariate-AUC threshold is NOT in "
            f"config/features.yaml:audit.excluded: {newly_flagged} -- remedy (a) not applied"
        )
        for name, row in audit["features"].items():
            if name in cfg["excluded"] or row["constant"]:
                continue
            assert row["univariate_auc"] is None or row["univariate_auc"] <= cfg["max_univariate_auc"], (
                f"{name}: univariate_auc {row['univariate_auc']} > {cfg['max_univariate_auc']} "
                "and not excluded"
            )

    def test_every_excluded_feature_has_a_reason_and_a_measured_auc(self, day5_corpus):
        cfg = _features_config()
        assert cfg["excluded"], "audit.excluded is empty -- test would be vacuous on this corpus"
        audit, _ = _recomputed_audit(day5_corpus)
        for name, entry in cfg["excluded"].items():
            assert name in FEATURE_NAMES, f"excluded feature {name!r} is not a real feature name"
            assert entry.get("reason", "").strip(), f"{name}: no reason recorded"
            assert isinstance(entry.get("measured_auc"), (int, float)), f"{name}: no measured_auc"
            fresh = audit["features"][name]["univariate_auc"]
            assert fresh is not None and abs(fresh - float(entry["measured_auc"])) < 0.05, (
                f"{name}: recorded measured_auc {entry['measured_auc']} vs recomputed {fresh}"
            )
            assert fresh > cfg["max_univariate_auc"], (
                f"{name} is excluded but its recomputed AUC {fresh} is not over threshold"
            )
