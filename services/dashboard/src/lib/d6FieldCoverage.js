// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §18.4 / FIX-FE-03 / RC-1.
//
// THE field-coverage contract -- the single most important anti-regression
// device in the plan. Every leaf of the committed D6 artifact is declared here
// as exactly one of:
//
//   RENDERED                         -- shown in a block on the page
//   RENDERED_IN_METHODOLOGY_PANEL    -- shown, but in the collapsed panel
//   OMITTED("<reason >= 20 chars>")  -- deliberately not shown, with a reason
//
// `checkCoverage(artifact)` walks the REAL artifact, collapses dynamic
// segments (model version / tier / scenario / feature / scorer / array index)
// to wildcards, and reports:
//   * unlisted  -- a leaf pattern with no entry (a field was added and forgotten)
//   * stale     -- an entry pattern absent from the artifact (map is stale)
//   * badReason -- an OMITTED entry whose reason is shorter than 20 chars
//
// FE-T-COVERAGE-01..03 fail on any of the three.

export const RENDERED = { kind: "RENDERED" };
export const RENDERED_IN_METHODOLOGY_PANEL = { kind: "RENDERED_IN_METHODOLOGY_PANEL" };
export function OMITTED(reason) {
  return { kind: "OMITTED", reason: String(reason) };
}

const R = RENDERED;
const MP = RENDERED_IN_METHODOLOGY_PANEL;

function operatingPoint(prefix) {
  const out = {};
  for (const k of ["fpr", "tpr", "precision", "recall", "tp", "fp", "tn", "fn"]) {
    out[`${prefix}.${k}`] = R;
  }
  return out;
}

function baselineRow(prefix) {
  return {
    [`${prefix}.split`]: R,
    [`${prefix}.n`]: R,
    [`${prefix}.prevalence`]: R,
    [`${prefix}.ap_raw`]: R,
    [`${prefix}.roc_auc`]: R,
    [`${prefix}.recall_at_target_fpr.value`]: R,
    [`${prefix}.recall_at_target_fpr.n_neg`]: R,
    [`${prefix}.recall_at_target_fpr.resolvable`]: R,
    [`${prefix}.recall_at_target_fpr.fpr_ci_low`]: R,
    [`${prefix}.recall_at_target_fpr.fpr_ci_high`]: R,
    [`${prefix}.recall_at_target_fpr.ci_basis`]: R,
    [`${prefix}.recall_at_target_fpr.ci_low`]: OMITTED(
      "deprecated alias of fpr_ci_low; the correctly-named twin is rendered (M-040)",
    ),
    [`${prefix}.recall_at_target_fpr.ci_high`]: OMITTED(
      "deprecated alias of fpr_ci_high; the correctly-named twin is rendered (M-040)",
    ),
  };
}

// Patterns: `*` = any dynamic dict key, `[]` = an array index.
export const FIELD_COVERAGE = {
  "schema_version": MP,

  "provenance.seed": R,
  "provenance.config_hash": R,
  "provenance.model_version": R,
  "provenance.policy_version": R,
  "provenance.eval_prevalence": R,
  "provenance.seeds_used": R,
  "provenance.generated_at": R,
  "provenance.build_hash": MP,
  "provenance.calibrator_version": MP,
  "provenance.fixture_sha256": MP,
  "provenance.base_seed": MP,
  "provenance.generation_command": MP,
  "provenance.head_at_generation": MP,
  "provenance.tree_dirty_at_generation": MP,
  "provenance.corpus_db_sha256": MP,
  "provenance.model_files_sha256.*": MP,

  "block1_per_tier.*.*.ap_raw": R,
  "block1_per_tier.*.*.ap_at_eval_prevalence": R,
  "block1_per_tier.*.*.prevalence": R,
  "block1_per_tier.*.*.eval_prevalence": R,
  "block1_per_tier.*.*.n": R,
  "block1_per_tier.*.*.split": R,
  "block1_per_tier.*.*.recall_at_target_fpr.value": R,
  "block1_per_tier.*.*.recall_at_target_fpr.n_neg": R,
  "block1_per_tier.*.*.recall_at_target_fpr.resolvable": R,
  "block1_per_tier.*.*.recall_at_target_fpr.fpr_ci_low": R,
  "block1_per_tier.*.*.recall_at_target_fpr.fpr_ci_high": R,
  "block1_per_tier.*.*.recall_at_target_fpr.ci_basis": R,
  "block1_per_tier.*.*.recall_at_target_fpr.ci_low": OMITTED(
    "deprecated alias of fpr_ci_low; retained for compatibility, the correctly-named twin is rendered (M-040)",
  ),
  "block1_per_tier.*.*.recall_at_target_fpr.ci_high": OMITTED(
    "deprecated alias of fpr_ci_high; retained for compatibility, the correctly-named twin is rendered (M-040)",
  ),

  "block2_theta_challenge": R,
  "block2_negative_controls.*.[].scorer": R,
  "block2_negative_controls.*.[].attempt_fp": R,
  "block2_negative_controls.*.[].attempts": R,
  "block2_negative_controls.*.[].episode_flagged": R,
  "block2_negative_controls.*.[].denominator_basis": R,
  "block2_negative_controls.*.[].available": R,
  "block2_negative_controls.*.[].reason": R,
  "block2_negative_controls.*.[].episode_fp": R,
  "block2_negative_controls.*.[].episodes": OMITTED(
    "structurally always 1 (one run, one episode per negative-control scenario); rendered as the boolean episode_flagged (M-017)",
  ),

  "block3_audit.features.*.univariate_auc": R,
  "block3_audit.features.*.separability": R,
  "block3_audit.features.*.direction": R,
  "block3_audit.features.*.flagged_two_sided": R,
  "block3_audit.features.*.constant": R,
  "block3_audit.features.*.excluded": R,
  "block3_audit.features.*.reason": R,
  "block3_audit.features.*.flagged": OMITTED(
    "one-sided v1 flag; the page consumes the two-sided flagged_two_sided and never recomputes a rule of its own (M-012, M-013)",
  ),
  "block3_audit.univariate_auc_threshold": R,
  "block3_audit.observed_max_univariate_auc": R,
  "block3_audit.max_univariate_auc": OMITTED(
    "misnamed v1 field (it is the threshold, not a maximum); superseded by univariate_auc_threshold and observed_max_univariate_auc (M-011)",
  ),
  "block3_audit.statistic": MP,
  "block3_audit.training_set.n": MP,
  "block3_audit.training_set.n_positive": MP,
  "block3_audit.training_set.prevalence": MP,

  "block4_cost.tier": R,
  "block4_cost.series": R,
  "block4_cost.split": R,
  "block4_cost.pi0": R,
  "block4_cost.pi1": R,
  "block4_cost.curve_pi0.[].[]": R,
  "block4_cost.curve_pi1.[].[]": R,
  "block4_cost.ribbon_envelope.[].[]": R,
  "block4_cost.ribbon_pis.[]": R,
  "block4_cost.decision_region_fpr_max": R,
  "block4_cost.optima_coincident": R,
  "block4_cost.rupee_gap_minor": R,
  "block4_cost.rupee_gap_is_structural": R,
  "block4_cost.rupee_gap_note": R,
  "block4_cost.regime_switch_saving_minor": R,
  "block4_cost.f1_optimal.fpr": R,
  "block4_cost.f1_optimal.tpr": R,
  "block4_cost.f1_optimal.f1": R,
  "block4_cost.f1_optimal.cost_pi0": R,
  "block4_cost.cost_optimal.fpr": R,
  "block4_cost.cost_optimal.tpr": R,
  "block4_cost.cost_optimal.cost_pi0": R,
  "block4_cost.cost_optimal_pi1.fpr": R,
  "block4_cost.cost_optimal_pi1.tpr": R,
  "block4_cost.cost_optimal_pi1.cost_pi1": R,
  "block4_cost.inputs.c_fn_minor": MP,
  "block4_cost.inputs.c_fp_minor_challenge": MP,
  "block4_cost.series_substitution": OMITTED(
    "null in every real run (the l1-lgbm-v1 series is always available); a substitution note renders only when it is non-null",
  ),
  "block4_cost.ribbon.[].pi": OMITTED(
    "per-pi ribbon curves superseded by the pre-computed ribbon_envelope; the pi range is disclosed via ribbon_pis (M-005)",
  ),
  "block4_cost.ribbon.[].curve.[].[]": OMITTED(
    "raw per-pi ribbon curves; the page draws the valid per-x ribbon_envelope so the band cannot self-intersect (M-005)",
  ),
  "block4_cost.inputs.pi0": OMITTED(
    "duplicate of block4_cost.pi0, kept only as a hand-check convenience inside the artifact",
  ),
  "block4_cost.inputs.pi1": OMITTED(
    "duplicate of block4_cost.pi1, kept only as a hand-check convenience inside the artifact",
  ),
  "block4_cost.inputs.f1_optimal_point.[]": OMITTED(
    "duplicate of block4_cost.f1_optimal.fpr/tpr, a flat hand-check pair kept in the artifact only",
  ),
  "block4_cost.inputs.cost_optimal_point.[]": OMITTED(
    "duplicate of block4_cost.cost_optimal.fpr/tpr, a flat hand-check pair kept in the artifact only",
  ),

  "block5_calibration.n": R,
  "block5_calibration.raw_prevalence": R,
  "block5_calibration.prior_correction_helped_at_pi1": R,
  "block5_calibration.pi0.brier_raw": R,
  "block5_calibration.pi0.brier_platt": R,
  "block5_calibration.pi0.brier_platt_prior": R,
  "block5_calibration.pi0.ece_raw": R,
  "block5_calibration.pi0.ece_platt": R,
  "block5_calibration.pi0.ece_platt_prior": R,
  "block5_calibration.pi0.ece_gap_platt_prior_vs_platt": R,
  "block5_calibration.pi0.effective_n": R,
  "block5_calibration.pi1.brier_raw": R,
  "block5_calibration.pi1.brier_platt": R,
  "block5_calibration.pi1.brier_platt_prior": R,
  "block5_calibration.pi1.ece_raw": R,
  "block5_calibration.pi1.ece_platt": R,
  "block5_calibration.pi1.ece_platt_prior": R,
  "block5_calibration.pi1.ece_gap_platt_prior_vs_platt": R,
  "block5_calibration.pi1.effective_n": R,
  "block5_calibration.reliability_pi0.[].mean_predicted": R,
  "block5_calibration.reliability_pi0.[].observed_rate": R,
  "block5_calibration.reliability_pi0.[].weight": R,
  "block5_calibration.reliability_pi1.[].mean_predicted": R,
  "block5_calibration.reliability_pi1.[].observed_rate": R,
  "block5_calibration.reliability_pi1.[].weight": R,
  "block5_calibration.pi_t": MP,
  "block5_calibration.n_bins": MP,
  "block5_calibration.reliability_pi0.[].lo": OMITTED(
    "reliability bin lower edge; the diagram plots mean_predicted vs observed_rate, so the raw edge is not drawn",
  ),
  "block5_calibration.reliability_pi0.[].hi": OMITTED(
    "reliability bin upper edge; the diagram plots mean_predicted vs observed_rate, so the raw edge is not drawn",
  ),
  "block5_calibration.reliability_pi1.[].lo": OMITTED(
    "reliability bin lower edge; the diagram plots mean_predicted vs observed_rate, so the raw edge is not drawn",
  ),
  "block5_calibration.reliability_pi1.[].hi": OMITTED(
    "reliability bin upper edge; the diagram plots mean_predicted vs observed_rate, so the raw edge is not drawn",
  ),

  ...baselineRow("block6_baselines.model"),
  ...baselineRow("block6_baselines.b0"),
  ...operatingPoint("block6_baselines.b1"),
  ...operatingPoint("block6_baselines.b2"),
  "block6_baselines.b1_sanity_floor.*.value": R,
  "block6_baselines.b1_sanity_floor.*.available": R,
  "block6_baselines.b1_sanity_floor.*.reason": R,
  "block6_baselines.b2_sanity_floor.*.value": R,
  "block6_baselines.b2_sanity_floor.*.available": R,
  "block6_baselines.b2_sanity_floor.*.reason": R,
  ...operatingPoint("block6_baselines.per_tier.*.model"),
  ...operatingPoint("block6_baselines.per_tier.*.b0"),
  ...operatingPoint("block6_baselines.per_tier.*.b1"),
  ...operatingPoint("block6_baselines.per_tier.*.b2"),
  "block6_baselines.sanity_recall_at_b1_fpr.*": OMITTED(
    "v1 raw sanity-recall dict; re-homed and rendered via b1_sanity_floor with a reason on the null (M-038)",
  ),
  "block6_baselines.sanity_recall_at_b2_fpr.*": OMITTED(
    "v1 raw sanity-recall dict; re-homed and rendered via b2_sanity_floor with a reason on the null (M-038)",
  ),

  "tier_e.split_n": R,
  "tier_e.prevalence": R,
  "tier_e.converged_params.ip_pool_size": R,
  "tier_e.converged_params.bin_pool_size": R,
  "tier_e.converged_params.attempts_per_hour": R,
  "tier_e.converged_params.distinct_cards": MP,
  "tier_e.converged_params.episode_duration_s": MP,
  "tier_e.converged_params.amount_quantile_band.[]": MP,
};

// ---------------------------------------------------------------------------
// walker
// ---------------------------------------------------------------------------

// dotted-path prefixes whose direct children are dynamic keys -> collapse to `*`
const DYNAMIC_MAP_PREFIXES = new Set([
  "block1_per_tier",
  "block1_per_tier.*",
  "block2_negative_controls",
  "block3_audit.features",
  "block6_baselines.b1_sanity_floor",
  "block6_baselines.b2_sanity_floor",
  "block6_baselines.per_tier",
  "block6_baselines.sanity_recall_at_b1_fpr",
  "block6_baselines.sanity_recall_at_b2_fpr",
]);

function walk(node, patternPath, out) {
  // model_files_sha256 keys carry dots -> one wildcard, do not descend
  if (patternPath === "provenance.model_files_sha256") {
    out.add("provenance.model_files_sha256.*");
    return;
  }
  if (Array.isArray(node)) {
    if (node.length === 0) {
      out.add(`${patternPath}.[]`);
      return;
    }
    walk(node[0], `${patternPath}.[]`, out);
    return;
  }
  if (node !== null && typeof node === "object") {
    const keys = Object.keys(node);
    if (keys.length === 0) {
      out.add(patternPath);
      return;
    }
    const collapse = DYNAMIC_MAP_PREFIXES.has(patternPath);
    for (const key of keys) {
      const nextSeg = collapse ? "*" : key;
      walk(node[key], patternPath ? `${patternPath}.${nextSeg}` : nextSeg, out);
    }
    return;
  }
  out.add(patternPath);
}

export function checkCoverage(artifact) {
  const seen = new Set();
  walk(artifact, "", seen);

  const declared = new Set(Object.keys(FIELD_COVERAGE));
  const unlisted = [...seen].filter((p) => !declared.has(p)).sort();
  const stale = [...declared].filter((p) => !seen.has(p)).sort();
  const badReason = Object.entries(FIELD_COVERAGE)
    .filter(([, v]) => v.kind === "OMITTED" && v.reason.trim().length < 20)
    .map(([k]) => k)
    .sort();

  return { unlisted, stale, badReason, seen: [...seen].sort() };
}
