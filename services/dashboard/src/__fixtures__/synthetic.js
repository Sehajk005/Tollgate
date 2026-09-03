// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.5 -- synthetic artifacts
// with HAND-COMPUTED expected values, for behaviour the real artifact never
// exercises (a resolvable recall, a non-coincident optimum, a flagged_two_sided
// boundary at exactly 0.95, a prior_correction_helped_at_pi1: false, a config
// mismatch). Each is a targeted mutation of the real, real-shaped artifact so
// components render without choking -- only the one branch under test flips.

import real from "./realArtifact.js";
import { deepClone, deepSet } from "./mutate.js";

/** A recall figure that IS resolvable (the real artifact has none). */
export function withResolvableRecall(tier = "medium", mv = "l1-lgbm-v1") {
  return deepSet(real, `block1_per_tier.${mv}.${tier}.recall_at_target_fpr`, {
    value: 0.812,
    n_neg: 1500,
    resolvable: true,
    ci_low: 0.0004,
    ci_high: 0.0021,
    fpr_ci_low: 0.0004,
    fpr_ci_high: 0.0021,
    ci_basis: "wilson_on_achieved_fpr",
  });
}

/** F1-optimal and cost-optimal on DIFFERENT hull vertices (real: coincident). */
export function withNonCoincidentOptima() {
  let a = deepClone(real);
  const co = a.block4_cost.cost_optimal;
  const alt = a.block4_cost.curve_pi0.find(([f, t]) => f !== co.fpr || t !== co.tpr);
  a = deepSet(a, "block4_cost.f1_optimal", { fpr: alt[0], tpr: alt[1], f1: 0.41, cost_pi0: alt[2] });
  a = deepSet(a, "block4_cost.optima_coincident", false);
  a = deepSet(a, "block4_cost.rupee_gap_minor", Math.abs(alt[2] - co.cost_pi0));
  a = deepSet(a, "block4_cost.rupee_gap_is_structural", false);
  a = deepSet(a, "block4_cost.rupee_gap_note", "");
  return a;
}

/** Prior correction did NOT help at pi1 (real: it helped). */
export function withPriorCorrectionFailed() {
  let a = deepClone(real);
  a = deepSet(a, "block5_calibration.prior_correction_helped_at_pi1", false);
  a = deepSet(a, "block5_calibration.pi1.ece_platt", 0.21);
  a = deepSet(a, "block5_calibration.pi1.ece_platt_prior", 0.34);
  a = deepSet(a, "block5_calibration.pi1.ece_gap_platt_prior_vs_platt", 0.21 - 0.34);
  return a;
}

/** A feature sitting EXACTLY on the 0.95 threshold, flagged_two_sided true. */
export function withBoundaryFeature(name = "__on_boundary__") {
  return deepSet(real, `block3_audit.features.${name}`, {
    univariate_auc: 0.95,
    constant: false,
    excluded: false,
    flagged: true,
    reason: "synthetic boundary feature",
    separability: 0.45,
    direction: "positive",
    flagged_two_sided: true,
  });
}

/** Provenance config_hash that does NOT match the build's current hash. */
export function withConfigMismatch() {
  return deepSet(real, "provenance.config_hash", "0".repeat(64));
}

/** A different pi0/pi1 so every rendered π label must move (M-021 drift test). */
export function withDifferentPi() {
  let a = deepSet(real, "block4_cost.pi0", 0.002);
  a = deepSet(a, "block4_cost.pi1", 0.8);
  return a;
}

/** A constant feature whose univariate_auc is NOT 0.5 (negative test: it must
 *  still not render a measurement bar). */
export function withConstantFeatureNonHalfAuc(name = "amount_percentile_vs_store") {
  let a = deepSet(real, `block3_audit.features.${name}.univariate_auc`, 0.62);
  a = deepSet(a, `block3_audit.features.${name}.constant`, true);
  a = deepSet(a, `block3_audit.features.${name}.separability`, 0.12);
  a = deepSet(a, `block3_audit.features.${name}.direction`, null);
  a = deepSet(a, `block3_audit.features.${name}.flagged_two_sided`, false);
  return a;
}
