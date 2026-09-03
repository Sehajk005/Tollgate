// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §18.5 -- the seven
// malformed-artifact fixtures, built at import time from the REAL artifact via
// mutate.js. Each drives one FE-T-ERR-* / FE-T-CONTRACT-* case.

import real from "./realArtifact.js";
import { deepClone, deepDelete, deepSet } from "./mutate.js";

export const missingProvenance = deepDelete(real, "provenance");

export const missingBlock = deepDelete(real, "block3_audit");

export const malformedCurve = deepSet(real, "block4_cost.curve_pi0", []);

export const missingCalibration = deepDelete(real, "block5_calibration.pi0");

export const wrongSchemaVersion = deepSet(real, "schema_version", 99);

export const explicitNulls = (() => {
  let a = deepClone(real);
  a = deepSet(a, "block1_per_tier.l1-lgbm-v1.easy.ap_raw", null);
  a = deepSet(a, "block1_per_tier.l1-lgbm-v1.easy.ap_at_eval_prevalence", null);
  a = deepSet(a, "block6_baselines.b0.roc_auc", null);
  return a;
})();

// The current committed file, downgraded in-place to schema_version 1 with every
// v2-only leaf removed -- exercises the "requires artifact v2" degradation path.
export const v1Artifact = (() => {
  const a = deepClone(real);
  a.schema_version = 1;
  delete a.block2_theta_challenge;
  for (const tier of Object.values(a.block1_per_tier)) {
    for (const tm of Object.values(tier)) {
      if (tm) {
        delete tm.split;
        delete tm.eval_prevalence;
      }
    }
  }
  for (const rows of Object.values(a.block2_negative_controls)) {
    for (const row of rows) {
      delete row.episode_flagged;
      delete row.denominator_basis;
      delete row.available;
      delete row.reason;
    }
  }
  delete a.block3_audit.univariate_auc_threshold;
  delete a.block3_audit.observed_max_univariate_auc;
  for (const f of Object.values(a.block3_audit.features)) {
    delete f.separability;
    delete f.direction;
    delete f.flagged_two_sided;
  }
  for (const key of [
    "optima_coincident", "rupee_gap_is_structural", "rupee_gap_note",
    "ribbon_envelope", "decision_region_fpr_max",
  ]) {
    delete a.block4_cost[key];
  }
  delete a.block5_calibration.prior_correction_helped_at_pi1;
  for (const r of [a.block5_calibration.pi0, a.block5_calibration.pi1]) {
    delete r.ece_raw;
    delete r.ece_gap_platt_prior_vs_platt;
  }
  for (const key of ["model", "per_tier", "b1_sanity_floor", "b2_sanity_floor"]) {
    delete a.block6_baselines[key];
  }
  return a;
})();

export const ALL_MALFORMED = {
  missingProvenance,
  missingBlock,
  malformedCurve,
  missingCalibration,
  wrongSchemaVersion,
  explicitNulls,
  v1Artifact,
};
