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
from packages.features.compute import FEATURE_NAMES

MODEL_ROW_VERSIONS = ("l1-lgbm-v1", "rules-only-v0")

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


def _model_per_tier_rows(report: Report) -> List[str]:
    rows = [
        "| tier | n | prevalence | recall@target_fpr | AP (raw pi) | AP (pi_eval) |",
        "|---|---|---|---|---|---|",
    ]
    for tier in ("easy", "medium", "hard"):
        tm = report.tier_breakdown.get(tier)
        if tm is None:
            rows.append(f"| {tier} | 0 | n/a | n/a (empty) | n/a | n/a |")
            continue
        rows.append(
            f"| {tier} | {tm.n} | {_fmt(tm.prevalence)} | {_fmt_recall(tm.recall_at_target_fpr)} | "
            f"{_fmt(tm.ap_raw)} (pi={_fmt(tm.prevalence)}) | {_fmt(tm.ap_at_eval_prevalence)} |"
        )
    rows.append("| evasive | -- | -- | pending (Day 7) | -- | -- |")
    return rows


def _block1_model_rows(
    model_reports: Dict[str, Report], holdout_model_reports: Dict[str, Report],
) -> List[str]:
    """Source: Day-5 Plan Step 11 -- l1-lgbm-v1 and B0 beside the sanity scorers."""
    lines = ["### Layer 1 -- `l1-lgbm-v1` and B0 (live rules)", ""]
    lines.append(
        "The discriminability audit (Block 3) excluded 6 features from the model per the "
        "pre-committed remedy (a) (Day-5 Plan §11/R1); it runs on the remaining live slots. "
        "Reported on the SAME `temporal_test` split as the sanity scorers. If the model is "
        "weaker than B0, that is stated here in exactly that form (Eval Protocol §8)."
    )
    lines.append("")
    labels = {
        "l1-lgbm-v1": "l1-lgbm-v1 (Layer 1 LightGBM detector, Platt-calibrated)",
        "rules-only-v0": "B0 -- live Day-1 rules (R1+R2+R3), read from attempt_score.score_raw",
    }
    for mv in MODEL_ROW_VERSIONS:
        report = model_reports.get(mv)
        if report is None:
            continue
        lines.append(f"#### {labels[mv]}")
        lines.extend(_provenance_header(report))
        lines.append(f"- ROC-AUC (overall): `{_fmt(report.roc_auc_value)}`")
        lines.append("")
        lines.extend(_model_per_tier_rows(report))
        lines.append("")
    hr = holdout_model_reports.get("l1-lgbm-v1")
    if hr is not None:
        lines.append("#### l1-lgbm-v1 on the attack-shape holdout (`stream_tier == hard`, held out from training)")
        lines.append(
            f"- split: `{hr.split_name}` (n={hr.n}, prevalence `{_fmt(hr.prevalence)}`) -- "
            f"ROC-AUC `{_fmt(hr.roc_auc_value)}`, AP (raw pi) `{_fmt(hr.ap_raw)}`, "
            f"recall@target_fpr {_fmt_recall(hr.recall_at_target_fpr)}"
        )
        lines.append("")
    return lines


def _block1_per_tier(
    reports_by_scorer: Dict[str, Report],
    runs: Sequence[HarnessRun],
    model_reports: Dict[str, Report] | None = None,
    holdout_model_reports: Dict[str, Report] | None = None,
) -> List[str]:
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
    if model_reports:
        lines.extend(_block1_model_rows(model_reports, holdout_model_reports or {}))
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


def _block3_discriminability_audit(audit_block: dict | None = None) -> List[str]:
    if not audit_block:
        return [
            "## Block 3 -- Discriminability audit",
            "",
            "deferred to Day 5 -- requires the feature_snapshot corpus (needs Day 5's replay). "
            "The statistic (`eval/audit.py::univariate_auc`) and its planted-perfect-discriminator "
            "test ship today.",
            "",
        ]
    ts = audit_block.get("training_set", {})
    threshold = audit_block.get("max_univariate_auc")
    feats = audit_block.get("features", {})
    lines = ["## Block 3 -- Discriminability audit", ""]
    lines.append(
        f"Univariate AUC (Mann-Whitney) per feature on the training set "
        f"(n={ts.get('n')}, prevalence={_fmt(ts.get('prevalence'))}), flag threshold "
        f"{threshold} (Eval Protocol §4/V2). A feature over threshold is EXCLUDED from the "
        f"model (zeroed on input) per the pre-committed remedy (a), Day-5 Plan §11/R1, and "
        f"stays active in the R1/R3 rule floors (Decision 17) and B0. The 12 constant `0.0` "
        f"features read exactly 0.5 -- an un-fed slot (Decision 43), NOT a measurement."
    )
    lines.append("")
    lines.append("| feature | univariate AUC | marker |")
    lines.append("|---|---|---|")
    for name in FEATURE_NAMES:
        v = feats.get(name, {})
        auc = v.get("univariate_auc")
        if v.get("excluded"):
            marker = f"EXCLUDED -- {v.get('reason') or 'audit remedy (a)'}"
        elif v.get("constant"):
            marker = "constant 0.0 -- un-fed slot, Decision 43"
        elif v.get("flagged"):
            marker = "FLAGGED (> threshold, not excluded)"
        else:
            marker = "ok"
        lines.append(f"| {name} | {_fmt(auc)} | {marker} |")
    lines.append("")
    n_excl = sum(1 for v in feats.values() if v.get("excluded"))
    n_const = sum(1 for v in feats.values() if v.get("constant"))
    n_live = len(feats) - n_excl - n_const
    lines.append(
        f"Summary: {n_excl} excluded by the audit, {n_const} constant `0.0` (un-fed slots, "
        f"Decision 43 -- `store_baseline` / `bin_metadata` / `/v1/outcome` are other days' work), "
        f"so the model runs on {n_live} live feature(s). It is expected to be weaker than B0 on "
        "the tiers whose signal the excluded rate/fan-out features carried (Eval Protocol §8)."
    )
    lines.append("")
    return lines


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


def _reliability_rows(bins: List[dict]) -> List[str]:
    rows = ["| bin | mean predicted | observed rate | weight |", "|---|---|---|---|"]
    any_row = False
    for b in bins:
        if b.get("weight", 0.0) <= 0:
            continue
        any_row = True
        rows.append(
            f"| [{b['lo']:.1f}, {b['hi']:.1f}) | {_fmt(b['mean_predicted'])} | "
            f"{_fmt(b['observed_rate'])} | {_fmt(b['weight'], 1)} |"
        )
    if not any_row:
        rows.append("| -- | n/a | n/a | 0 |")
    return rows


def _block5_calibration(calibration_block: dict | None = None) -> List[str]:
    if not calibration_block:
        return [
            "## Block 5 -- Calibration",
            "",
            "not yet measured (Day 5) -- no calibrator exists on Day 4.",
            "",
        ]
    cb = calibration_block
    lines = ["## Block 5 -- Calibration", ""]
    lines.append(
        f"On `temporal_test` (n={cb['n']}, raw prevalence {_fmt(cb['raw_prevalence'])}), reweighted "
        f"to each regime prevalence via `prevalence_weights` (Eval Protocol §2.3). Platt was fit "
        f"on the held-out `calib` slice (pi_t={_fmt(cb['pi_t'])}); ECE over {cb['n_bins']} bins. "
        f"Prior correction is Eval Protocol §3.2's logit shift by ln(pi_s/(1-pi_s)) - ln(pi_t/(1-pi_t))."
    )
    lines.append("")
    lines.append(
        "| regime | Brier raw | Brier Platt | Brier Platt+prior | ECE Platt | ECE Platt+prior | effective n |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for label, key in (("pi0 = 0.001 (steady state)", "pi0"), ("pi1 = 0.9 (under attack)", "pi1")):
        r = cb[key]
        lines.append(
            f"| {label} | {_fmt(r['brier_raw'])} | {_fmt(r['brier_platt'])} | "
            f"{_fmt(r['brier_platt_prior'])} | {_fmt(r['ece_platt'])} | {_fmt(r['ece_platt_prior'])} | "
            f"{_fmt(r['effective_n'], 1)} |"
        )
    lines.append("")
    e1u, e1c = cb["pi1"]["ece_platt"], cb["pi1"]["ece_platt_prior"]
    improved = (e1c is not None and e1u is not None and e1c < e1u)
    lines.append(
        f"**ECE gap at pi1** (the acceptance criterion, Day-5 Plan §11/R5): prior-corrected "
        f"{_fmt(e1c)} vs uncorrected {_fmt(e1u)} -- "
        + ("prior correction reduces ECE at pi1." if improved
           else "prior correction does not reduce ECE at pi1 on this split.")
    )
    lines.append(
        f"At pi0 = 0.001 the reweighting is extreme (effective n = {_fmt(cb['pi0']['effective_n'], 1)} "
        f"of {cb['n']}), so ECE at pi0 is ill-conditioned; the well-conditioned criterion is ECE at pi1."
    )
    lines.append("")
    lines.append("Reliability (Platt + prior correction) at pi1:")
    lines.extend(_reliability_rows(cb.get("reliability_pi1", [])))
    lines.append("")
    lines.append("Reliability (Platt + prior correction) at pi0:")
    lines.extend(_reliability_rows(cb.get("reliability_pi0", [])))
    lines.append("")
    lines.append(
        "Isotonic comparison: disabled (`config/features.yaml: calibration.isotonic_enabled = false`); "
        "Platt is the shipped calibrator (Eval Protocol §3.1)."
    )
    lines.append("")
    return lines


def _block6_baselines(run: HarnessRun, model_reports: Dict[str, Report] | None = None) -> List[str]:
    lines = ["## Block 6 -- Baselines", ""]
    b1 = run.baseline_summary.b1_operating_point
    b2 = run.baseline_summary.b2_operating_point
    b0_report = (model_reports or {}).get("rules-only-v0")
    if b0_report is not None:
        r0 = b0_report.recall_at_target_fpr
        lines.append(
            "**B0** -- the live Day-1 rules layer (R1+R2+R3), pre-auth, outcome-independent. Read "
            "from `attempt_score.score_raw` exactly as logged at decision time; NEVER recomputed "
            "offline (Eval Protocol §8, Decision 6)."
        )
        lines.append("")
        lines.append("| baseline | split | n | prevalence | ROC-AUC | AP (raw pi) | recall@target_fpr |")
        lines.append("|---|---|---|---|---|---|---|")
        lines.append(
            f"| B0 (live rules) | `{b0_report.split_name}` | {b0_report.n} | "
            f"{_fmt(b0_report.prevalence)} | {_fmt(b0_report.roc_auc_value)} | "
            f"{_fmt(b0_report.ap_raw)} | {_fmt_recall(r0)} |"
        )
        lines.append("")
    else:
        lines.append(
            "**B0** (live rules layer): no replay corpus supplied to this run -- pass "
            "`--corpus-db` + `--model-dir` to `python -m eval.harness` to populate it."
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
    model_reports: Dict[str, Report] = {}
    holdout_model_reports: Dict[str, Report] = {}
    temporal_split_name = next(
        (name for name in run.eval_reports if name.startswith("temporal_test")), None
    )
    if temporal_split_name:
        for report in run.eval_reports[temporal_split_name]:
            mv = report.provenance.model_version
            key = next((k for k in SANITY_SCORER_ORDER if mv == f"none:{k}"), None)
            if key is not None:
                reports_by_scorer[key] = report
            elif mv in MODEL_ROW_VERSIONS:
                model_reports[mv] = report
    holdout_split_name = next(
        (name for name in run.eval_reports if name.startswith("attack_shape_holdout") and name.endswith("test")),
        None,
    )
    if holdout_split_name:
        for report in run.eval_reports[holdout_split_name]:
            if report.provenance.model_version in MODEL_ROW_VERSIONS:
                holdout_model_reports[report.provenance.model_version] = report

    lines: List[str] = []
    day = 5 if run.model_version else 4
    lines.append(f"# Tollgate -- Day {day} Evaluation Report")
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
        lines.extend(_block1_per_tier(reports_by_scorer, runs, model_reports, holdout_model_reports))
    else:
        lines.append("## Block 1 -- Per-tier recall@FPR and PR-AUC")
        lines.append("")
        lines.append("n/a -- temporal_test split produced no data for this run.")
        lines.append("")

    lines.extend(_block2_negative_controls(run))
    lines.extend(_block3_discriminability_audit(run.audit_block))
    if reports_by_scorer:
        lines.extend(_block4_cost(reports_by_scorer, cost_model))
    lines.extend(_block5_calibration(run.calibration_block))
    lines.extend(_block6_baselines(run, model_reports))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
