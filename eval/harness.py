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
from packages.simulator.generate import build_negative_stream, build_stream
from packages.simulator.negative import SCENARIOS

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

    tier_breakdown = {
        tier: _tier_metrics([s for s in samples if s.stream_tier == tier], scorer, cost_model)
        for tier in ("easy", "medium", "hard")
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
    """
    runs = []
    block_i = 0
    for _ in range(n_blocks_per_tier):
        for tier in ("easy", "medium", "hard"):
            epoch_ms = block_i * hours * 3_600_000
            runs.append((tier, build_stream(seed=seed + block_i, tier=tier, hours=hours, epoch_ms=epoch_ms)))
            block_i += 1
    for scenario in SCENARIOS:
        runs.append((None, build_negative_stream(seed=seed, scenario=scenario, hours=hours)))
    samples = build_dataset(runs)
    return compute_entity_overlap(samples)


def _make_provenance(model_version: str) -> RunProvenance:
    return RunProvenance(
        model_version=model_version, config_hash=config_hash(),
        policy_version=DEFAULT_POLICY_VERSION, eval_prevalence=load_cost_model().eval_prevalence,
    )


@dataclass(frozen=True)
class BaselineSummary:
    b1_operating_point: object  # eval.metrics.OperatingPoint
    b2_operating_point: object
    sanity_recall_at_b1_fpr: Dict[str, Optional[float]]
    sanity_recall_at_b2_fpr: Dict[str, Optional[float]]


@dataclass(frozen=True)
class HarnessRun:
    eval_reports: Dict[str, List[Report]]  # split.name -> one Report per sanity scorer
    temporal_train_n: int
    holdout_train_n: int
    negative_scenario_names: Tuple[str, ...]
    negative_splits: Dict[str, Split]  # scenario -> its Split (raw samples, for episode-FP grouping)
    baseline_summary: BaselineSummary
    seed: int


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


def run_all(seed: int = 42) -> HarnessRun:
    """One report per (eval split, sanity scorer) pair. `--split all`'s entry point."""
    cost_model = load_cost_model()
    samples = build_full_dataset(seed)

    temporal_train, temporal_test = temporal_split(samples, train_fraction=0.7)
    temporal_train = exclude_negative_controls(temporal_train)
    holdout_train, holdout_test = attack_shape_holdout(samples)
    holdout_train = exclude_negative_controls(holdout_train)
    negative_splits = negative_control_splits(samples)

    scorers = _build_sanity_scorers(seed)
    eval_reports: Dict[str, List[Report]] = {}

    eval_splits: List[Split] = [temporal_test, holdout_test] + list(negative_splits.values())
    for split in eval_splits:
        reports = []
        for _key, (model_version, scorer) in scorers.items():
            provenance = _make_provenance(model_version)
            reports.append(evaluate(split, scorer, cost_model, provenance))
        eval_reports[split.name] = reports

    return HarnessRun(
        eval_reports=eval_reports, temporal_train_n=temporal_train.n, holdout_train_n=holdout_train.n,
        negative_scenario_names=tuple(negative_splits.keys()), negative_splits=negative_splits,
        baseline_summary=_baseline_summary(temporal_test, seed), seed=seed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["all"], default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    from eval.report import render  # local import -- report.py imports harness.py's Report type

    runs = [run_all(seed=args.seed + i) for i in range(max(1, args.seeds))]

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "report.md"
    render(runs, out_path=out_path, seeds_used=max(1, args.seeds), base_seed=args.seed)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
