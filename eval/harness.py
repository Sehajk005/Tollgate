"""
Source: Day-4 Plan (rev. 2) Step 7 -- eval/harness.py. `evaluate(split,
scorer, cost_model, provenance) -> Report`: recall@FPR (with
resolvability + CI), AP at raw pi and at pi_eval, ROC-AUC, per-tier
breakdown, clean-subset breakdown, cost over operating points at pi0 and
pi1.

**Multi-seed cut to 1** (Day-4 Plan §9 cut ladder item 2, explicitly
authorized: "Multi-seed 5 -> 1 (-20m), with the limitation stated in the
report and in README. Weakens tests 3 and 20 to characterization."):
tests 3 and 20 already independently exercise their scorers/tiers across 5
seeds by calling the scoring functions directly (test_harness_sanity.py,
test_attack_tiers.py), so that guarantee is not lost -- only the CLI
harness's OWN report generation runs a single seed by default. `--seeds N`
is accepted; when >1, `run_all()` is called once per seed and
`eval/report.py`'s block 1 (per-tier recall@FPR / AP, the headline
metrics) reports min/median/max across the N runs. Other blocks (2, 4, 6)
render only the first run's data even when `--seeds N>1` is passed --
extending them to aggregate is not implemented. Default is `--seeds 1`,
stated as a limitation in the report.

Report.__post_init__ validates provenance itself (not merely relying on
the caller having done so first) -- a Report cannot exist with
unvalidated provenance.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from eval.cost import CostModel, load_cost_model, roc_convex_hull
from eval.dataset import (
    Sample,
    Split,
    attack_shape_holdout,
    build_dataset,
    clean_view,
    compute_entity_overlap,
    exclude_negative_controls,
    negative_control_splits,
    temporal_split,
)
from eval.metrics import (
    RecallAtFpr,
    average_precision,
    ap_at_prevalence,
    cost_over_operating_points,
    recall_at_fpr,
    roc_auc,
    roc_points,
)
from eval.provenance import RunProvenance, config_hash
from eval.scorers import AlwaysPositiveScorer, InvertedScorer, PerfectScorer, RandomScorer, Scorer

# Source: Day-5 Plan Step 2 -- run construction moved to eval.corpus.build_runs
# (delegated from build_full_dataset); this module no longer builds streams
# directly.

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "outputs"

# Source: Day-4 Plan Step 7 note -- Day 4 has no live merchant DB
# dependency (eval/load.py, the DB loader, is explicitly the lowest-
# priority/first-cut item, Day-4 Plan §9). This placeholder version is the
# one seeded by scripts/seed_merchant.py; eval/load.py (Day 5) is
# responsible for real DB-backed policy_version discovery.
DEFAULT_POLICY_VERSION = 1
DEFAULT_POLICY_VERSIONS_AVAILABLE = (1,)

COST_TIER = "challenge"  # the auto-ceiling tier (TRD Decision table) -- report block 2/4's default
BLOCK_HOURS = 3
N_BLOCKS_PER_TIER = 4  # spreads multiple attack episodes across a longer timeline (see test_splits.py)


def _build_sanity_scorers(seed: int) -> Dict[str, Tuple[str, Scorer]]:
    return {
        "perfect": ("none:perfect", PerfectScorer()),
        "random": ("none:random", RandomScorer(seed=seed)),
        "inverted": ("none:inverted", InvertedScorer()),
        "always_positive": ("none:always_positive", AlwaysPositiveScorer()),
    }


@dataclass(frozen=True)
class TierMetrics:
    n: int
    prevalence: Optional[float]
    recall_at_target_fpr: Optional[RecallAtFpr]
    ap_raw: Optional[float]
    ap_at_eval_prevalence: Optional[float]


@dataclass(frozen=True)
class Report:
    provenance: RunProvenance
    policy_versions_available: Tuple[int, ...]
    split_name: str
    n: int
    n_positive: int
    prevalence: float
    recall_at_target_fpr: Optional[RecallAtFpr]
    ap_raw: Optional[float]
    ap_at_eval_prevalence: Optional[float]
    roc_auc_value: Optional[float]
    cost_points_pi0: List[Tuple[float, float, float]]
    cost_points_pi1: List[Tuple[float, float, float]]
    min_cost_pi0: Tuple[Optional[Tuple[float, float]], Optional[float]]
    min_cost_pi1: Tuple[Optional[Tuple[float, float]], Optional[float]]
    tier_breakdown: Dict[str, Optional[TierMetrics]]
    clean_breakdown: Optional[TierMetrics]

    def __post_init__(self) -> None:
        self.provenance.validate(policy_versions_available=self.policy_versions_available)


def _tier_metrics(samples: Sequence[Sample], scorer: Scorer, cost_model: CostModel) -> Optional[TierMetrics]:
    if not samples:
        return None
    scores = [scorer(s) for s in samples]
    labels = [s.is_attack for s in samples]
    n_pos = sum(1 for lbl in labels if lbl)
    return TierMetrics(
        n=len(samples),
        prevalence=(n_pos / len(samples)) if samples else None,
        recall_at_target_fpr=recall_at_fpr(scores, labels, cost_model.target_fpr),
        ap_raw=average_precision(scores, labels),
        ap_at_eval_prevalence=ap_at_prevalence(scores, labels, cost_model.eval_prevalence),
    )


def evaluate(
    split: Split, scorer: Scorer, cost_model: CostModel, provenance: RunProvenance,
    *, policy_versions_available: Sequence[int] = DEFAULT_POLICY_VERSIONS_AVAILABLE, cost_tier: str = COST_TIER,
) -> Report:
    samples = split.samples
    scores = [scorer(s) for s in samples]
    labels = [s.is_attack for s in samples]
    n = len(samples)
    n_positive = sum(1 for lbl in labels if lbl)
    prevalence = n_positive / n if n else 0.0

    recall = recall_at_fpr(scores, labels, cost_model.target_fpr)
    ap_raw = average_precision(scores, labels)
    ap_eval = ap_at_prevalence(scores, labels, cost_model.eval_prevalence)
    auc = roc_auc(scores, labels)

    points = [(p[0], p[1]) for p in roc_points(scores, labels)]
    cost_points_pi0 = cost_over_operating_points(points, cost_model, cost_model.prior_steady_state, cost_tier)
    cost_points_pi1 = cost_over_operating_points(points, cost_model, cost_model.prior_under_attack, cost_tier)
    hull = roc_convex_hull(points) if points else []
    min_cost_pi0 = cost_model.min_cost_operating_point(hull, cost_model.prior_steady_state, cost_tier)
    min_cost_pi1 = cost_model.min_cost_operating_point(hull, cost_model.prior_under_attack, cost_tier)

    # Source: Day-7 Plan §6 -- `evasive` joins the per-tier breakdown. On a
    # split with no evasive samples (temporal_test / holdout_test) the entry is
    # None; it is populated only on the dedicated `tier_e` split.
    tier_breakdown = {
        tier: _tier_metrics([s for s in samples if s.stream_tier == tier], scorer, cost_model)
        for tier in ("easy", "medium", "hard", "evasive")
    }

    clean = clean_view(split)
    clean_breakdown = _tier_metrics(clean.samples, scorer, cost_model)

    return Report(
        provenance=provenance, policy_versions_available=tuple(policy_versions_available),
        split_name=split.name, n=n, n_positive=n_positive, prevalence=prevalence,
        recall_at_target_fpr=recall, ap_raw=ap_raw, ap_at_eval_prevalence=ap_eval,
        roc_auc_value=auc, cost_points_pi0=cost_points_pi0, cost_points_pi1=cost_points_pi1,
        min_cost_pi0=min_cost_pi0, min_cost_pi1=min_cost_pi1,
        tier_breakdown=tier_breakdown, clean_breakdown=clean_breakdown,
    )


def build_full_dataset(
    seed: int, *, hours: int = BLOCK_HOURS, n_blocks_per_tier: int = N_BLOCKS_PER_TIER,
) -> List[Sample]:
    """
    Unions multiple sequentially-epoched blocks per attack tier (so a
    temporal split can put attack representation on both sides -- a
    single build_stream() run has exactly one attack episode) plus one run
    per negative-control scenario, all at seed-derived sub-seeds.

    Source: Day-5 Plan Step 2 -- delegates to `eval.corpus.build_runs`, which
    IS the loop this function used to inline. One construction, so the Day-5
    feature corpus and this dataset cannot drift. Sample ordering and content
    are byte-identical to Day 4.
    """
    from eval.corpus import build_runs

    runs = build_runs(seed, hours=hours, n_blocks_per_tier=n_blocks_per_tier)
    samples = build_dataset([(run.stream_tier, run.output) for run in runs])
    return compute_entity_overlap(samples)


def build_tier_e_dataset(
    seed: int, *, hours: int = BLOCK_HOURS, n_blocks_per_tier: int = N_BLOCKS_PER_TIER,
) -> List[Sample]:
    """
    Source: Day-7 Plan §6 -- `build_full_dataset` is UNCHANGED. This is the
    dedicated Tier-E dataset: ONE `build_dataset` call over
    `build_runs(seed) + build_tier_e_runs(seed)` so `run_index` stays aligned
    with the corpus merchants, entity-overlap computed against the full set,
    then filtered to the evasive stream. Returns `[]` when the Tier-E search
    was cut and `config/attack_tiers.yaml`'s `evasive` block is still pending.
    """
    from eval.corpus import build_runs, build_tier_e_runs
    from packages.simulator.profile import load_attack_tiers

    if load_attack_tiers().get("evasive", {}).get("pending"):
        return []

    runs = build_runs(seed, hours=hours, n_blocks_per_tier=n_blocks_per_tier)
    runs = runs + build_tier_e_runs(seed, hours=hours)
    samples = compute_entity_overlap(
        build_dataset([(run.stream_tier, run.output) for run in runs])
    )
    return [s for s in samples if s.stream_tier == "evasive"]


def _make_provenance(model_version: str) -> RunProvenance:
    return RunProvenance(
        model_version=model_version, config_hash=config_hash(),
        policy_version=DEFAULT_POLICY_VERSION, eval_prevalence=load_cost_model().eval_prevalence,
    )


# ---------------------------------------------------------------------------
# Source: Day-5 Plan Step 11 (Block 5) -- calibration evidence at both regimes.
# math-only local copies of sigmoid / prior_correct so eval/harness.py stays
# numpy-free (the Calibrator/Layer1Model objects are passed in already built).
# ---------------------------------------------------------------------------

_EPS = 1e-6


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    q = min(max(p, _EPS), 1.0 - _EPS)
    return math.log(q / (1.0 - q))


def _prior_correct(p_train: float, pi_t: float, pi_s: float) -> float:
    return _sigmoid(_logit(p_train) + _logit(pi_s) - _logit(pi_t))


def _calibration_block(
    samples: Sequence[Sample], feature_corpus, model, calibrator, cost_model, *, n_bins: int,
) -> Optional[dict]:
    from eval.metrics import brier, ece, prevalence_weights, reliability_bins

    pairs = [
        (feature_corpus[(s.run_index, s.event_id)], s.is_attack)
        for s in samples
        if (s.run_index, s.event_id) in feature_corpus
    ]
    if not pairs:
        return None
    margins = [model.margin(fr.x) for fr, _ in pairs]
    labels = [bool(lbl) for _, lbl in pairs]
    a, b, pi_t = calibrator.a, calibrator.b, calibrator.pi_t
    raw = [_sigmoid(m) for m in margins]
    platt = [_sigmoid(a * m + b) for m in margins]
    pi0 = cost_model.prior_steady_state
    pi1 = cost_model.prior_under_attack
    platt_pc0 = [_prior_correct(p, pi_t, pi0) for p in platt]
    platt_pc1 = [_prior_correct(p, pi_t, pi1) for p in platt]
    w0 = prevalence_weights(labels, pi0)
    w1 = prevalence_weights(labels, pi1)

    def _eff_n(w: Sequence[float]) -> float:
        s1 = sum(w)
        s2 = sum(x * x for x in w)
        return (s1 * s1 / s2) if s2 > 0 else 0.0

    def _regime(w, platt_pc) -> dict:
        return {
            "brier_raw": brier(raw, labels, weights=w),
            "brier_platt": brier(platt, labels, weights=w),
            "brier_platt_prior": brier(platt_pc, labels, weights=w),
            "ece_platt": ece(platt, labels, n_bins=n_bins, weights=w),
            "ece_platt_prior": ece(platt_pc, labels, n_bins=n_bins, weights=w),
            "effective_n": _eff_n(w),
        }

    def _reliab(platt_pc, w) -> list:
        return [
            {"lo": rb.lo, "hi": rb.hi, "weight": rb.weight,
             "mean_predicted": rb.mean_predicted, "observed_rate": rb.observed_rate}
            for rb in reliability_bins(platt_pc, labels, n_bins=n_bins, weights=w)
        ]

    return {
        "n": len(labels),
        "pi_t": pi_t,
        "n_bins": n_bins,
        "raw_prevalence": sum(1 for lbl in labels if lbl) / len(labels),
        "pi0": _regime(w0, platt_pc0),
        "pi1": _regime(w1, platt_pc1),
        "reliability_pi0": _reliab(platt_pc0, w0),
        "reliability_pi1": _reliab(platt_pc1, w1),
    }


def _audit_summary(audit_block: dict) -> dict:
    feats = audit_block.get("features", {})
    return {
        "max_univariate_auc": audit_block.get("max_univariate_auc"),
        "n_features": len(feats),
        "n_constant": sum(1 for v in feats.values() if v.get("constant")),
        "n_flagged": sum(1 for v in feats.values() if v.get("flagged")),
        "excluded": sorted(n for n, v in feats.items() if v.get("excluded")),
    }


@dataclass(frozen=True)
class BaselineSummary:
    b1_operating_point: object  # eval.metrics.OperatingPoint
    b2_operating_point: object
    sanity_recall_at_b1_fpr: Dict[str, Optional[float]]
    sanity_recall_at_b2_fpr: Dict[str, Optional[float]]


@dataclass(frozen=True)
class HarnessRun:
    eval_reports: Dict[str, List[Report]]  # split.name -> one Report per scorer (sanity + Day-5 model/B0)
    temporal_train_n: int
    holdout_train_n: int
    negative_scenario_names: Tuple[str, ...]
    negative_splits: Dict[str, Split]  # scenario -> its Split (raw samples, for episode-FP grouping)
    baseline_summary: BaselineSummary
    seed: int
    # Source: Day-5 Plan Steps 10/11 -- populated only when `run_all` is given a
    # feature corpus + model. calibration_block feeds report Block 5 and the
    # eval_run metrics JSON; audit_block feeds Block 3.
    calibration_block: Optional[dict] = None
    audit_block: Optional[dict] = None
    model_version: Optional[str] = None
    b0_present: bool = False


def _baseline_summary(split: Split, seed: int) -> BaselineSummary:
    from eval.baselines import B2BinConcentrationScorer, b1_decline_velocity
    from eval.metrics import operating_point, recall_at_matched_fpr
    from packages.features.memory_store import InMemoryWindowStore

    samples = split.samples
    labels = [s.is_attack for s in samples]

    b2_store = InMemoryWindowStore()
    b2_scorer = B2BinConcentrationScorer(b2_store)
    b2_scores = [b2_scorer(s) for s in samples]
    b1_scores = b1_decline_velocity(samples)

    b1_point = operating_point(b1_scores, labels, theta=0.5)
    b2_point = operating_point(b2_scores, labels, theta=0.5)

    sanity_scorers = _build_sanity_scorers(seed)
    sanity_recall_b1: Dict[str, Optional[float]] = {}
    sanity_recall_b2: Dict[str, Optional[float]] = {}
    for key, (_model_version, scorer) in sanity_scorers.items():
        scores = [scorer(s) for s in samples]
        sanity_recall_b1[key] = recall_at_matched_fpr(scores, labels, b1_point.fpr) if b1_point else None
        sanity_recall_b2[key] = recall_at_matched_fpr(scores, labels, b2_point.fpr) if b2_point else None

    return BaselineSummary(
        b1_operating_point=b1_point, b2_operating_point=b2_point,
        sanity_recall_at_b1_fpr=sanity_recall_b1, sanity_recall_at_b2_fpr=sanity_recall_b2,
    )


MODEL_MODEL_VERSION = "l1-lgbm-v1"
B0_MODEL_VERSION = "rules-only-v0"


def run_all(
    seed: int = 42,
    *,
    feature_corpus: Optional[dict] = None,
    model=None,
    calibrator=None,
    audit_block: Optional[dict] = None,
    policy_versions_available: Sequence[int] = DEFAULT_POLICY_VERSIONS_AVAILABLE,
) -> HarnessRun:
    """
    One report per (eval split, scorer) pair. `--split all`'s entry point.

    Day-5 Plan Step 10: when `feature_corpus` + `model` + `calibrator` are
    supplied, the Layer-1 model (`l1-lgbm-v1`) and the live rules layer B0
    (`rules-only-v0`) are evaluated alongside the four B3 sanity scorers on
    `temporal_test` and `holdout_test`. `evaluate()` is not redesigned.
    """
    cost_model = load_cost_model()
    samples = build_full_dataset(seed)

    temporal_train, temporal_test = temporal_split(samples, train_fraction=0.7)
    temporal_train = exclude_negative_controls(temporal_train)
    holdout_train, holdout_test = attack_shape_holdout(samples)
    holdout_train = exclude_negative_controls(holdout_train)
    negative_splits = negative_control_splits(samples)

    sanity = _build_sanity_scorers(seed)
    model_scorers: Dict[str, Tuple[str, object]] = {}
    calibration_block: Optional[dict] = None
    have_model = feature_corpus is not None and model is not None and calibrator is not None
    if have_model:
        from eval.scorers import B0RulesScorer, Layer1Scorer

        pi_s = cost_model.prior_steady_state  # serving_prior("in_control", cost_model)
        model_scorers = {
            "l1_lgbm": (MODEL_MODEL_VERSION, Layer1Scorer(model, calibrator, feature_corpus, pi_s=pi_s)),
            "b0_rules": (B0_MODEL_VERSION, B0RulesScorer(feature_corpus)),
        }
        calibration_block = _calibration_block(
            temporal_test.samples, feature_corpus, model, calibrator, cost_model,
            n_bins=calibrator.ece_bins,
        )

    eval_reports: Dict[str, List[Report]] = {}

    for split in (temporal_test, holdout_test):
        reports: List[Report] = []
        for _key, (model_version, scorer) in {**sanity, **model_scorers}.items():
            provenance = _make_provenance(model_version)
            reports.append(evaluate(
                split, scorer, cost_model, provenance,
                policy_versions_available=policy_versions_available,
            ))
        eval_reports[split.name] = reports

    for split in negative_splits.values():
        reports = []
        for _key, (model_version, scorer) in sanity.items():
            provenance = _make_provenance(model_version)
            reports.append(evaluate(
                split, scorer, cost_model, provenance,
                policy_versions_available=policy_versions_available,
            ))
        eval_reports[split.name] = reports

    # Source: Day-7 Plan §6 -- the dedicated Tier-E split, evaluated with the
    # SAME scorers (sanity + model/B0). Skipped entirely when the search was
    # cut (build_tier_e_dataset returns []).
    tier_e_samples = build_tier_e_dataset(seed)
    if tier_e_samples:
        te_split = Split(name="tier_e", samples=tuple(tier_e_samples))
        te_reports: List[Report] = []
        for _key, (model_version, scorer) in {**sanity, **model_scorers}.items():
            provenance = _make_provenance(model_version)
            te_reports.append(evaluate(
                te_split, scorer, cost_model, provenance,
                policy_versions_available=policy_versions_available,
            ))
        eval_reports["tier_e"] = te_reports

    return HarnessRun(
        eval_reports=eval_reports, temporal_train_n=temporal_train.n, holdout_train_n=holdout_train.n,
        negative_scenario_names=tuple(negative_splits.keys()), negative_splits=negative_splits,
        baseline_summary=_baseline_summary(temporal_test, seed), seed=seed,
        calibration_block=calibration_block, audit_block=audit_block,
        model_version=MODEL_MODEL_VERSION if have_model else None, b0_present=have_model,
    )


def _load_model_bundle(model_dir: Path):
    """(feature_corpus, model, calibrator, audit_block) -- model_dir side only.
    Local imports so eval/harness.py stays free of packages.detect / numpy /
    lightgbm on the Day-4 path."""
    import json as _json

    from packages.detect.calibrate import Calibrator
    from packages.detect.model import Layer1Model

    model = Layer1Model.load(model_dir)
    calibrator = Calibrator.load(Path(model_dir) / "platt-v1.json")
    audit_path = Path(model_dir) / "audit.json"
    audit_block = _json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
    return model, calibrator, audit_block


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["all"], default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--corpus-db", dest="corpus_db", type=Path, default=None)
    parser.add_argument("--model-dir", dest="model_dir", type=Path, default=None)
    parser.add_argument("--write-eval-run", dest="write_eval_run", action="store_true")
    args = parser.parse_args()

    from eval.report import render  # local import -- report.py imports harness.py's Report type

    feature_corpus = model = calibrator = audit_block = None
    policy_versions: Sequence[int] = DEFAULT_POLICY_VERSIONS_AVAILABLE
    if args.model_dir is not None:
        if args.corpus_db is None:
            raise SystemExit("--model-dir requires --corpus-db (the replay feature corpus)")
        from eval.corpus import load_feature_corpus
        from packages.storage.db import connect

        conn = connect(args.corpus_db)
        try:
            feature_corpus = load_feature_corpus(conn)
            rows = conn.execute("SELECT DISTINCT version FROM policy_config").fetchall()
            discovered = tuple(sorted({int(r[0]) for r in rows}))
        finally:
            conn.close()
        if discovered:
            policy_versions = discovered
        model, calibrator, audit_block = _load_model_bundle(args.model_dir)

    runs = [
        run_all(
            seed=args.seed + i, feature_corpus=feature_corpus, model=model,
            calibrator=calibrator, audit_block=audit_block,
            policy_versions_available=policy_versions,
        )
        for i in range(max(1, args.seeds))
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "report.md"
    render(runs, out_path=out_path, seeds_used=max(1, args.seeds), base_seed=args.seed)
    print(f"wrote {out_path}")

    if args.write_eval_run:
        if args.corpus_db is None:
            raise SystemExit("--write-eval-run requires --corpus-db")
        from eval.load import write_eval_run
        from packages.storage.db import connect

        cost_model = load_cost_model()
        run = runs[0]
        # Source: Day-7 Plan §6 -- the `evasive` per-tier entry on EVERY
        # eval_run row is sourced from the dedicated `tier_e` split's matching
        # model report, never from the temporal_test/holdout report (which has
        # no evasive samples). Absent when the search was cut.
        tier_e_reports = {
            r.provenance.model_version: r for r in run.eval_reports.get("tier_e", [])
        }
        conn = connect(args.corpus_db)
        written: List[Tuple[str, str, str]] = []
        try:
            for split_name, reports in run.eval_reports.items():
                is_temporal = split_name == "temporal_test"
                is_holdout = split_name.startswith("attack_shape_holdout") and split_name.endswith("test")
                if not (is_temporal or is_holdout):
                    continue
                for report in reports:
                    mv = report.provenance.model_version
                    if mv == B0_MODEL_VERSION and not is_temporal:
                        continue  # B0 row only for temporal_test
                    if mv not in (MODEL_MODEL_VERSION, B0_MODEL_VERSION):
                        continue
                    cal_ver = "platt-v1" if mv == MODEL_MODEL_VERSION else "identity"
                    extra: dict = {}
                    if mv == MODEL_MODEL_VERSION and is_temporal:
                        if run.calibration_block is not None:
                            extra["calibration"] = run.calibration_block
                        if run.audit_block is not None:
                            extra["audit_summary"] = _audit_summary(run.audit_block)
                    te_report = tier_e_reports.get(mv)
                    tier_e_tm = (
                        te_report.tier_breakdown.get("evasive") if te_report is not None else None
                    )
                    rid = write_eval_run(
                        conn, report=report, seed=args.seed, model_version=mv,
                        calibrator_version=cal_ver,
                        prior_assumed=cost_model.prior_steady_state,
                        artifacts_path=str(args.model_dir or args.out),
                        extra_metrics=extra or None,
                        tier_e_metrics=tier_e_tm,
                    )
                    written.append((mv, report.split_name, rid))
        finally:
            conn.close()
        for mv, sn, rid in written:
            print(f"eval_run[{rid[:12]}] {mv} on {sn}")


if __name__ == "__main__":
    main()
