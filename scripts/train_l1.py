"""
python -m scripts.train_l1 --seed 42 --db data/corpus/tollgate.db --out models/ [--rebuild-corpus]

Source: Day-5 Plan Step 7 / Backend Schema §9 step 6 (which names this path
verbatim). This is the ONE place labels and features meet -- it lives in
scripts/, never in packages/detect/, which is exactly what
tests/acceptance/test_detect_label_isolation.py asserts.

Pipeline:
  1. build_runs(seed); replay_corpus(...) if --rebuild-corpus or the DB is absent.
  2. samples = compute_entity_overlap(build_dataset(runs)); features = load_feature_corpus(conn).
  3. temporal_split(samples, 0.7) -> train side = easy+medium, negative controls
     excluded; 3-way temporal slice fit 70% / earlystop 15% / calib 15%, each
     with the existing 30-minute embargo.
  4. discriminability audit on the TRAIN set (univariate AUC over all 24);
     write models/audit.json; exit non-zero if any feature not already in
     config/features.yaml:audit.excluded exceeds max_univariate_auc.
  5. fit LightGBM: objective="binary", num_boost_round=200, max_depth=6,
     scale_pos_weight = n_neg/n_pos on `fit`, num_threads=1, deterministic=True,
     seed=42; early stopping on `earlystop` via a custom eval fn calling
     eval.metrics.recall_at_fpr(scores, labels, cost_model.target_fpr).
  6. calibrate on `calib`: fit_platt(margins, labels); pi_t = prevalence(calib).
  7. write models/l1-lgbm-v1.txt, models/l1-lgbm-v1.json, models/platt-v1.json,
     models/audit.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import yaml

from eval.audit import univariate_auc
from eval.corpus import build_runs, load_feature_corpus, replay_corpus
from eval.cost import load_cost_model
from eval.dataset import (
    MAX_FEATURE_HORIZON_MS,
    Sample,
    Split,
    build_dataset,
    compute_entity_overlap,
    exclude_negative_controls,
    temporal_split,
)
from eval.metrics import recall_at_fpr
from eval.provenance import build_hash, config_hash
from packages.detect.calibrate import Calibrator, fit_isotonic, fit_platt
from packages.detect.model import FEATURE_ORDER, Layer1Model, ModelArtifact
from packages.features.compute import FEATURE_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_YAML = REPO_ROOT / "config" / "features.yaml"
MODEL_VERSION = "l1-lgbm-v1"
CALIBRATOR_VERSION = "platt-v1"


# ---------------------------------------------------------------------------
# config/features.yaml
# ---------------------------------------------------------------------------


def _leaf(node):
    return node["value"] if isinstance(node, dict) and "value" in node else node


def load_features_config() -> dict:
    raw = yaml.safe_load(FEATURES_YAML.read_text(encoding="utf-8"))
    excluded_raw = raw["audit"].get("excluded") or []
    excluded: Dict[str, dict] = {}
    for entry in excluded_raw:
        excluded[entry["name"]] = {
            "reason": entry.get("reason", ""),
            "measured_auc": entry.get("measured_auc"),
        }
    return {
        "feature_set_version": int(_leaf(raw["feature_set_version"])),
        "max_univariate_auc": float(_leaf(raw["audit"]["max_univariate_auc"])),
        "excluded": excluded,
        "num_boost_round": int(_leaf(raw["model"]["num_boost_round"])),
        "max_depth": int(_leaf(raw["model"]["max_depth"])),
        "seed": int(_leaf(raw["model"]["seed"])),
        "num_threads": int(_leaf(raw["model"]["num_threads"])),
        "isotonic_enabled": bool(_leaf(raw["calibration"]["isotonic_enabled"])),
        "ece_bins": int(_leaf(raw["calibration"]["ece_bins"])),
    }


# ---------------------------------------------------------------------------
# slicing + matrix
# ---------------------------------------------------------------------------


def three_way_temporal_slice(samples: Sequence[Sample]) -> Tuple[Split, Split, Split]:
    """
    fit 70% / earlystop 15% / calib 15%, temporal, each with the existing
    30-minute (MAX_FEATURE_HORIZON_MS) embargo -- Eval Protocol §7 'no shuffled
    split'. A separate `calib` slice keeps the calibrator off the
    early-stopping set.

    NOTE (stated in the report): the tier blocks are epoched 3h-contiguous
    (eval/corpus.build_runs), so the time-tail `calib` slice is dominated by
    the last-epoched tier (medium) and `earlystop` by the one before (easy).
    The calibrator is therefore fit largely on medium-tier margins; Block 5
    reports its behaviour on the full `temporal_test` (all tiers) so this is
    visible, not hidden.
    """
    fit_split, rest = temporal_split(
        list(samples), train_fraction=0.70, embargo_ms=MAX_FEATURE_HORIZON_MS
    )
    earlystop_split, calib_split = temporal_split(
        list(rest.samples), train_fraction=0.50, embargo_ms=MAX_FEATURE_HORIZON_MS
    )
    return (
        Split(name="fit", samples=fit_split.samples),
        Split(name="earlystop", samples=earlystop_split.samples),
        Split(name="calib", samples=calib_split.samples),
    )


def _matrix(
    samples: Sequence[Sample], features: Dict[Tuple[int, str], object], excluded: Sequence[str],
) -> Tuple[np.ndarray, np.ndarray]:
    excluded_set = set(excluded)
    rows: List[List[float]] = []
    labels: List[int] = []
    for s in samples:
        row = features[(s.run_index, s.event_id)]  # KeyError = loud failure, by design
        rows.append([
            0.0 if FEATURE_NAMES[j] in excluded_set else float(row.x[j])
            for j in range(len(FEATURE_NAMES))
        ])
        labels.append(1 if s.is_attack else 0)
    return np.asarray(rows, dtype=np.float64), np.asarray(labels, dtype=np.int32)


def _prevalence(samples: Sequence[Sample]) -> float:
    n = len(samples)
    return (sum(1 for s in samples if s.is_attack) / n) if n else 0.0


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def run_audit(x_train: np.ndarray, y_train: np.ndarray, cfg: dict) -> Tuple[dict, List[str]]:
    """univariate AUC per feature on the training set. Returns (audit_dict,
    newly_flagged) where newly_flagged are features over threshold that are
    NOT already in config/features.yaml:audit.excluded."""
    labels = [bool(v) for v in y_train.tolist()]
    threshold = cfg["max_univariate_auc"]
    excluded = cfg["excluded"]
    features_block: Dict[str, dict] = {}
    newly_flagged: List[str] = []
    for j, name in enumerate(FEATURE_NAMES):
        col = x_train[:, j]
        constant = bool(np.all(col == col[0])) if col.size else True
        auc = univariate_auc(col.tolist(), labels)
        is_excluded = name in excluded
        over = (auc is not None) and (auc > threshold) and not constant
        if over and not is_excluded:
            newly_flagged.append(name)
        features_block[name] = {
            "univariate_auc": auc,
            "constant": constant,
            "excluded": is_excluded,
            "flagged": bool(over),
            "reason": (
                excluded[name]["reason"] if is_excluded
                else ("constant 0.0 -- un-fed slot, Decision 43" if constant else None)
            ),
        }
    audit = {
        "max_univariate_auc": threshold,
        "statistic": "univariate_auc (Mann-Whitney) on the training set -- Eval Protocol §4/V2",
        "training_set": {
            "n": int(x_train.shape[0]),
            "n_positive": int(y_train.sum()),
            "prevalence": float(y_train.mean()) if y_train.size else 0.0,
        },
        "features": features_block,
    }
    return audit, newly_flagged


# ---------------------------------------------------------------------------
# training
# ---------------------------------------------------------------------------


def _recall_at_fpr_feval(target_fpr: float):
    def _feval(preds, dataset):
        labels = [bool(v) for v in dataset.get_label().tolist()]
        result = recall_at_fpr(list(preds), labels, target_fpr)
        value = result.value if (result is not None and result.value is not None) else 0.0
        return "recall_at_fpr", float(value), True  # is_higher_better

    return _feval


def train_lgbm(
    fit_xy: Tuple[np.ndarray, np.ndarray],
    earlystop_xy: Tuple[np.ndarray, np.ndarray],
    cfg: dict,
    target_fpr: float,
) -> Tuple[object, dict, int]:
    import lightgbm as lgb

    x_fit, y_fit = fit_xy
    x_es, y_es = earlystop_xy
    n_pos = int(y_fit.sum())
    n_neg = int(y_fit.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        raise SystemExit("train_l1: `fit` slice is single-class -- cannot train")
    scale_pos_weight = n_neg / n_pos

    params = {
        "objective": "binary",
        "max_depth": cfg["max_depth"],
        "scale_pos_weight": scale_pos_weight,
        "num_threads": cfg["num_threads"],
        "deterministic": True,
        "force_row_wise": True,
        "seed": cfg["seed"],
        "verbosity": -1,
        "metric": "None",
    }
    train_ds = lgb.Dataset(x_fit, label=y_fit, feature_name=list(FEATURE_ORDER))
    valid_ds = lgb.Dataset(x_es, label=y_es, reference=train_ds)
    num_boost_round = cfg["num_boost_round"]
    recorded = dict(params)
    recorded["num_boost_round"] = num_boost_round  # a train() arg, recorded for test_model_config

    # Pass 1: TRD §6.9's spec -- early stopping on validation recall@FPR=1e-3.
    evals_log: dict = {}
    probe = lgb.train(
        params, train_ds, num_boost_round=num_boost_round,
        valid_sets=[valid_ds], valid_names=["earlystop"],
        feval=_recall_at_fpr_feval(target_fpr),
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, first_metric_only=True, verbose=False),
            lgb.record_evaluation(evals_log),
        ],
    )
    trace = evals_log.get("earlystop", {}).get("recall_at_fpr", [])
    resolved = len({round(v, 9) for v in trace}) > 1

    if resolved:
        best_iter = int(probe.best_iteration)
        recorded["early_stopping"] = (
            f"stopped at iteration {best_iter} on validation recall@FPR=1e-3 "
            f"(trace over {len(trace)} rounds)"
        )
        return probe, recorded, best_iter

    # The validation recall@FPR=1e-3 was constant every round -- the embargoed
    # 15% earlystop slice has n_neg << 1/target_fpr, so early stopping cannot
    # discriminate boosting rounds (itself a downstream effect of the §11/R1
    # audit exclusions). Retrain without the callback so TRD §6.9's "~200 trees"
    # is honoured rather than collapsing to a stump. Stated in the report.
    booster = lgb.train(params, train_ds, num_boost_round=num_boost_round)
    best_iter = int(booster.current_iteration())
    recorded["early_stopping"] = (
        f"unresolved -- validation recall@FPR=1e-3 was constant (0.0) over all {len(trace)} "
        "rounds (n_neg < 1/target_fpr on the embargoed earlystop slice); kept all "
        f"{best_iter} trees"
    )
    return booster, recorded, best_iter


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "corpus" / "tollgate.db")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "models")
    parser.add_argument("--rebuild-corpus", action="store_true")
    args = parser.parse_args()

    cfg = load_features_config()
    cost_model = load_cost_model()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = build_runs(args.seed)

    spool_dir = args.db.parent / "spool"
    if args.rebuild_corpus or not args.db.exists():
        print(f"[train_l1] building corpus -> {args.db}")
        result = replay_corpus(runs, db_path=args.db, spool_dir=spool_dir, rebuild=True)
        print(f"[train_l1] corpus: {result.n_runs} runs, {result.n_attempts} attempts, "
              f"{result.n_labels_written} labels")
    else:
        print(f"[train_l1] reusing corpus at {args.db}")

    from packages.storage.db import connect

    conn = connect(args.db)
    try:
        features = load_feature_corpus(conn)
    finally:
        conn.close()
    print(f"[train_l1] feature corpus: {len(features)} rows")

    samples = compute_entity_overlap(build_dataset([(r.stream_tier, r.output) for r in runs]))

    temporal_train, temporal_test = temporal_split(samples, train_fraction=0.7)
    train_split = exclude_negative_controls(temporal_train)
    train_samples = [s for s in train_split.samples if s.stream_tier in ("easy", "medium")]
    fit_split, earlystop_split, calib_split = three_way_temporal_slice(train_samples)
    print(f"[train_l1] slices: train={len(train_samples)} "
          f"fit={fit_split.n} earlystop={earlystop_split.n} calib={calib_split.n} "
          f"| temporal_test={temporal_test.n}")

    x_train, y_train = _matrix(train_samples, features, ())  # audit reads RAW columns (no exclusion)
    audit, newly_flagged = run_audit(x_train, y_train, cfg)
    (out_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[train_l1] wrote {out_dir / 'audit.json'}")
    if newly_flagged:
        lines = "\n".join(
            f"  - {n}: univariate_auc={audit['features'][n]['univariate_auc']:.4f} > "
            f"{cfg['max_univariate_auc']}"
            for n in newly_flagged
        )
        print(
            "[train_l1] discriminability audit FAILED -- these features exceed "
            f"max_univariate_auc and are not in config/features.yaml:audit.excluded:\n{lines}\n"
            "Pre-committed remedy (a), Day-5 Plan §11/R1: add each to "
            "config/features.yaml:audit.excluded with its measured AUC and a reason, then re-run.",
            file=sys.stderr,
        )
        return 2

    excluded_features = tuple(sorted(cfg["excluded"].keys()))

    fit_xy = _matrix(fit_split.samples, features, excluded_features)
    earlystop_xy = _matrix(earlystop_split.samples, features, excluded_features)
    calib_xy = _matrix(calib_split.samples, features, excluded_features)

    booster, recorded_params, best_iter = train_lgbm(
        fit_xy, earlystop_xy, cfg, cost_model.target_fpr
    )
    print(f"[train_l1] trained: best_iteration={best_iter} "
          f"scale_pos_weight={recorded_params['scale_pos_weight']:.6f}")

    x_calib, y_calib = calib_xy
    calib_margins = booster.predict(
        x_calib, raw_score=True, num_iteration=best_iter, num_threads=cfg["num_threads"]
    )
    calib_labels = [bool(v) for v in y_calib.tolist()]
    a, b = fit_platt(list(calib_margins), calib_labels)
    pi_t = _prevalence(calib_split.samples)
    calibrator = Calibrator(
        calibrator_version=CALIBRATOR_VERSION, method="platt", a=a, b=b,
        pi_t=pi_t, n_fit=len(calib_labels), ece_bins=cfg["ece_bins"],
    )
    calibrator.save(out_dir / f"{CALIBRATOR_VERSION}.json")
    print(f"[train_l1] platt: a={a:.6f} b={b:.6f} pi_t={pi_t:.6f} n_fit={len(calib_labels)}")

    if cfg["isotonic_enabled"]:
        p_calib = 1.0 / (1.0 + np.exp(-np.asarray(calib_margins)))
        iso = fit_isotonic(list(p_calib), calib_labels)
        (out_dir / "isotonic-v1.json").write_text(
            json.dumps({"x": list(iso.x), "y": list(iso.y)}, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("[train_l1] isotonic comparison written (config: calibration.isotonic_enabled=true)")

    artifact = ModelArtifact(
        model_version=MODEL_VERSION,
        feature_names=tuple(FEATURE_ORDER),
        params=recorded_params,
        pi_t=pi_t,
        best_iteration=best_iter,
        n_train=int(fit_xy[1].size),
        n_train_pos=int(fit_xy[1].sum()),
        excluded_features=excluded_features,
        corpus={
            "seed": args.seed,
            "config_hash": config_hash(),
            "build_hash": build_hash(),
            "n_runs": len(runs),
            "feature_set_version": cfg["feature_set_version"],
        },
    )
    Layer1Model(booster, artifact).save(out_dir)
    print(f"[train_l1] wrote {out_dir / (MODEL_VERSION + '.txt')} + {MODEL_VERSION}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
