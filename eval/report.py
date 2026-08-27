"""
Source: Day-4 Plan (rev. 2) Step 8 -- eval/report.py. `render(reports) ->
eval/outputs/report.md`, ordered as D6's six blocks (App Flow §5 D6).

Invariants: six provenance fields in every table header; every PR-AUC cell
prints its prevalence; empty splits and zero incidents render explicit
empty states -- never a crash, never a blank, never a 0.0 standing in for
"undefined".

Writing `eval_run` rows is Day 5's job (eval/load.py) -- Day 4 has no live
merchant DB dependency, so this module only ever writes the markdown file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from eval.cost import load_cost_model
from eval.harness import COST_TIER, HarnessRun, Report
from eval.provenance import build_hash

THETA_CHALLENGE = 0.257  # report block 2's episode/attempt-FP threshold (the auto-ceiling tier)
SANITY_SCORER_ORDER = ("perfect", "random", "inverted", "always_positive")
SANITY_SCORER_LABEL = {
    "perfect": "PerfectScorer", "random": "RandomScorer",
    "inverted": "InvertedScorer", "always_positive": "AlwaysPositiveScorer",
}


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_recall(recall) -> str:
    if recall is None:
        return "n/a (single-class split)"
    if recall.value is None:
        return f"unreachable (n_neg={recall.n_neg}, resolvable={recall.resolvable})"
    resolvable = "resolvable" if recall.resolvable else "UNRESOLVABLE (too few negatives)"
    ci = f"[{_fmt(recall.ci_low)}, {_fmt(recall.ci_high)}]" if recall.ci_low is not None else "n/a"
    return f"{_fmt(recall.value)} (95% CI {ci}, n_neg={recall.n_neg}, {resolvable})"


def _provenance_header(report: Report) -> List[str]:
    p = report.provenance
    return [
        f"- model_version: `{p.model_version}`",
        f"- config_hash: `{p.config_hash}`",
        f"- policy_version: `{p.policy_version}`",
        f"- eval_prevalence (declared): `{_fmt(p.eval_prevalence)}`",
        f"- split: `{report.split_name}`",
        f"- split raw prevalence: `{_fmt(report.prevalence)}` (n={report.n}, n_positive={report.n_positive})",
    ]


def _across_seeds(runs: Sequence[HarnessRun], scorer_key: str, tier: str, field: str) -> List[float]:
    """
    Collect one value per run (temporal_test split, given scorer/tier/field)
    across ALL runs passed in -- the multi-seed min/median/max source.
    Silently skips a run if that split/tier/value is unavailable there.
    """
    values: List[float] = []
    for run in runs:
        split_name = next((name for name in run.eval_reports if name.startswith("temporal_test")), None)
        if split_name is None:
            continue
        report = next(
            (r for r in run.eval_reports[split_name] if r.provenance.model_version == f"none:{scorer_key}"), None,
        )
        if report is None:
            continue
        tm = report.tier_breakdown.get(tier)
        if tm is None:
            continue
        if field == "recall" and tm.recall_at_target_fpr is not None and tm.recall_at_target_fpr.value is not None:
            values.append(tm.recall_at_target_fpr.value)
        elif field == "ap_raw" and tm.ap_raw is not None:
            values.append(tm.ap_raw)
    return values


def _seed_summary(values: List[float]) -> str:
    if not values:
        return ""
    import statistics as _statistics
    return f" (min={_fmt(min(values))}, median={_fmt(_statistics.median(values))}, max={_fmt(max(values))}, n_seeds={len(values)})"


def _block1_per_tier(reports_by_scorer: Dict[str, Report], runs: Sequence[HarnessRun]) -> List[str]:
    multi_seed = len(runs) > 1
    lines = ["## Block 1 -- Per-tier recall@FPR and PR-AUC", ""]
    lines.append(
        "**Deferred**: `cards_exposed_before_alert`, `attempts_before_alert`, `time_to_detect_s` -- "
        "deferred to Day 6, requires the incident detector; the harm unit is not yet measured."
    )
    if multi_seed:
        lines.append("")
        lines.append(
            f"Multi-seed run ({len(runs)} seeds): recall@target_fpr and AP (raw pi) below carry a "
            "min/median/max summary across seeds where resolvable in more than one."
        )
    lines.append("")
    for key in SANITY_SCORER_ORDER:
        report = reports_by_scorer[key]
        lines.append(f"### {SANITY_SCORER_LABEL[key]}")
        lines.extend(_provenance_header(report))
        lines.append("")
        lines.append("| tier | n | prevalence | recall@target_fpr | AP (raw pi) | AP (pi_eval) |")
        lines.append("|---|---|---|---|---|---|")
        for tier in ("easy", "medium", "hard"):
            tm = report.tier_breakdown.get(tier)
            if tm is None:
                lines.append(f"| {tier} | 0 | n/a | n/a (empty) | n/a | n/a |")
                continue
            recall_cell = _fmt_recall(tm.recall_at_target_fpr)
            ap_cell = f"{_fmt(tm.ap_raw)} (pi={_fmt(tm.prevalence)})"
            if multi_seed:
                recall_cell += _seed_summary(_across_seeds(runs, key, tier, "recall"))
                ap_cell += _seed_summary(_across_seeds(runs, key, tier, "ap_raw"))
            lines.append(
                f"| {tier} | {tm.n} | {_fmt(tm.prevalence)} | {recall_cell} | "
                f"{ap_cell} | {_fmt(tm.ap_at_eval_prevalence)} |"
            )
        lines.append("| evasive | -- | -- | pending (Day 7) | -- | -- |")
        lines.append("")
    return lines


def _episode_and_attempt_fp(split_samples, scores, threshold: float) -> tuple:
    """
    (n_episode_fp, n_episodes, n_attempt_fp, n_attempts) for one
    negative-control scenario split. Counts only LEGITIMATE (is_attack=
    False) samples -- shared_ip_legit is the one scenario embedding
    genuinely fraudulent sub-traffic, and flagging that correctly is a
    true positive, not a false positive; it must not inflate this count.
    """
    flagged_by_episode: Dict[str, bool] = {}
    n_attempt_fp = 0
    n_attempts = 0
    for sample, score in zip(split_samples, scores):
        if sample.is_attack:
            continue
        n_attempts += 1
        eid = sample.episode_id or sample.event_id
        flagged_by_episode[eid] = flagged_by_episode.get(eid, False) or (score >= threshold)
        if score >= threshold:
            n_attempt_fp += 1
    n_episode_fp = sum(1 for flagged in flagged_by_episode.values() if flagged)
    return n_episode_fp, len(flagged_by_episode), n_attempt_fp, n_attempts


def _block2_negative_controls(run: HarnessRun) -> List[str]:
    from eval.scorers import AlwaysPositiveScorer, InvertedScorer, PerfectScorer, RandomScorer

    lines = ["## Block 2 -- Negative controls, per scenario", ""]
    lines.append(f"Episode-level FP threshold: score >= theta_challenge = {THETA_CHALLENGE} (the auto-ceiling tier).")
    lines.append("")

    sanity_scorers = {
        "perfect": PerfectScorer(), "random": RandomScorer(seed=run.seed),
        "inverted": InvertedScorer(), "always_positive": AlwaysPositiveScorer(),
    }

    for scenario in run.negative_scenario_names:
        split = run.negative_splits.get(scenario)
        header = f"### {scenario}"
        if scenario == "nri_traffic":
            header += " -- **inert, becomes live on Day 5**"
        lines.append(header)
        if split is None or split.n == 0:
            lines.append("")
            lines.append("n/a -- split is empty.")
            lines.append("")
            continue
        lines.append("")
        lines.append("| scorer | episode FP / total episodes | attempt FP / total attempts |")
        lines.append("|---|---|---|")
        for key in SANITY_SCORER_ORDER:
            scores = [sanity_scorers[key](s) for s in split.samples]
            n_ep_fp, n_ep, n_att_fp, n_att = _episode_and_attempt_fp(split.samples, scores, THETA_CHALLENGE)
            lines.append(f"| {SANITY_SCORER_LABEL[key]} | {n_ep_fp}/{n_ep} | {n_att_fp}/{n_att} |")
        lines.append("")
    return lines


def _block3_discriminability_audit() -> List[str]:
    return [
        "## Block 3 -- Discriminability audit",
        "",
        "deferred to Day 5 -- requires the feature_snapshot corpus (needs Day 5's replay). "
        "The statistic (`eval/audit.py::univariate_auc`) and its planted-perfect-discriminator "
        "test ship today.",
        "",
    ]


def _block4_cost(reports_by_scorer: Dict[str, Report], cost_model) -> List[str]:
    lines = ["## Block 4 -- Cost", ""]
    lines.append(
        f"Curves over achievable (FPR, TPR) operating points at pi0={_fmt(cost_model.prior_steady_state)} "
        f"(steady-state) and pi1={_fmt(cost_model.prior_under_attack)} (under-attack), tier={COST_TIER}. "
        "No theta-indexed curve, no \"cost-optimal threshold\", no Rs gap -- those presuppose a "
        "calibrated posterior, which does not exist on Day 4 (deferred to Day 6)."
    )
    lines.append("")
    lines.append("| scorer | pi0 hull-min point (FPR, TPR) | pi0 cost/10k | pi1 hull-min point (FPR, TPR) | pi1 cost/10k |")
    lines.append("|---|---|---|---|---|")
    for key in SANITY_SCORER_ORDER:
        report = reports_by_scorer[key]
        point0, cost0 = report.min_cost_pi0
        point1, cost1 = report.min_cost_pi1
        point0_str = f"({_fmt(point0[0])}, {_fmt(point0[1])})" if point0 else "n/a"
        point1_str = f"({_fmt(point1[0])}, {_fmt(point1[1])})" if point1 else "n/a"
        lines.append(
            f"| {SANITY_SCORER_LABEL[key]} | {point0_str} | {_fmt(cost0, 2)} | {point1_str} | {_fmt(cost1, 2)} |"
        )
    lines.append("")
    return lines


def _block5_calibration() -> List[str]:
    return ["## Block 5 -- Calibration", "", "not yet measured (Day 5) -- no calibrator exists on Day 4.", ""]


def _block6_baselines(run: HarnessRun) -> List[str]:
    lines = ["## Block 6 -- Baselines", ""]
    b1 = run.baseline_summary.b1_operating_point
    b2 = run.baseline_summary.b2_operating_point
    lines.append(
        "**B0** (live rules layer) is marked `Day 5` -- wired in when the replay corpus exists; "
        "recomputing it offline would credit the live detector with information it never had (Eval Protocol §8)."
    )
    lines.append("")
    lines.append(
        "**B2** shares R3's statistic (`distinct_cards_per_bin_5m`), so B0 already contains it -- "
        "its contribution is not independent of B0's."
    )
    lines.append("**B1** requires completed outcomes the live pre-auth path never has at decision time.")
    lines.append("")
    lines.append("| baseline | native FPR | native TPR | precision | recall@1e-3 |")
    lines.append("|---|---|---|---|---|")
    for name, point in (("B1 (decline-velocity)", b1), ("B2 (BIN-concentration)", b2)):
        if point is None:
            lines.append(f"| {name} | n/a | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {name} | {_fmt(point.fpr)} | {_fmt(point.tpr)} | {_fmt(point.precision)} | "
            f"unreachable (native FPR = {_fmt(point.fpr)}) |"
        )
    lines.append("")
    lines.append("Sanity scorers' recall at each baseline's matched native FPR (the honest ranker-vs-rule comparator):")
    lines.append("| scorer | recall @ B1's FPR | recall @ B2's FPR |")
    lines.append("|---|---|---|")
    for key in SANITY_SCORER_ORDER:
        r1 = run.baseline_summary.sanity_recall_at_b1_fpr.get(key)
        r2 = run.baseline_summary.sanity_recall_at_b2_fpr.get(key)
        lines.append(f"| {SANITY_SCORER_LABEL[key]} | {_fmt(r1)} | {_fmt(r2)} |")
    lines.append("")
    return lines


def render(runs: Sequence[HarnessRun], *, out_path: Path, seeds_used: int = 1, base_seed: int = 42) -> None:
    cost_model = load_cost_model()
    run = runs[0]

    reports_by_scorer: Dict[str, Report] = {}
    temporal_split_name = next(
        (name for name in run.eval_reports if name.startswith("temporal_test")), None
    )
    if temporal_split_name:
        for report in run.eval_reports[temporal_split_name]:
            key = next(k for k in SANITY_SCORER_ORDER if report.provenance.model_version == f"none:{k}")
            reports_by_scorer[key] = report

    lines: List[str] = []
    lines.append("# Tollgate -- Day 4 Evaluation Report")
    lines.append("")
    limitation = (
        " **Limitation**: multi-seed default is cut to 1 for this CLI report "
        "(Day-4 Plan §9 cut ladder item 2) -- pass `--seeds 5` for a multi-seed run."
        if seeds_used == 1 else ""
    )
    lines.append(f"Seeds used: {seeds_used} (base seed {base_seed}).{limitation}")
    lines.append("")
    lines.append(f"build_hash: `{build_hash()}`")
    lines.append("")

    if reports_by_scorer:
        lines.extend(_block1_per_tier(reports_by_scorer, runs))
    else:
        lines.append("## Block 1 -- Per-tier recall@FPR and PR-AUC")
        lines.append("")
        lines.append("n/a -- temporal_test split produced no data for this run.")
        lines.append("")

    lines.extend(_block2_negative_controls(run))
    lines.extend(_block3_discriminability_audit())
    if reports_by_scorer:
        lines.extend(_block4_cost(reports_by_scorer, cost_model))
    lines.extend(_block5_calibration())
    lines.extend(_block6_baselines(run))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
