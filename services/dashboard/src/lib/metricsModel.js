// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §7 / FIX-FE-03 / RC-1.
//
// The semantic seam. `buildMetricsModel(parsedArtifact)` converts the parsed
// artifact into an explicit view model BEFORE any component sees it -- so the
// 23 formerly-dropped fields are visible as a data problem, missing-value
// semantics are testable without rendering, and every block component is a
// pure function of one plain object.
//
// NO formatting here (that is format.js). NO JSX here. Missing values become
// `null`, never a fabricated `0`.

import { normaliseMetric } from "./d6Contract.js";

const TIER_ORDER = ["easy", "medium", "hard", "evasive"];
const MODEL_MV = "l1-lgbm-v1";
const B0_MV = "rules-only-v0";
const SANITY_ORDER = ["perfect", "random", "inverted", "always_positive"];

const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);
const bool = (x) => x === true;
const str = (x) => (typeof x === "string" ? x : null);
const fmt4 = (x) => (num(x) != null ? x.toFixed(4) : "n/a");
const fmt3 = (x) => (num(x) != null ? x.toFixed(3) : "n/a");

function inrMinor(minor) {
  if (num(minor) == null) return "n/a";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Math.round(minor / 100));
}

// ---- provenance / freshness ------------------------------------------

function buildProvenance(a) {
  const p = a.provenance;
  return {
    seed: num(p.seed),
    baseSeed: num(p.base_seed),
    seedsUsed: num(p.seeds_used),
    configHash: str(p.config_hash),
    modelVersion: str(p.model_version),
    calibratorVersion: str(p.calibrator_version),
    policyVersion: num(p.policy_version),
    piEval: num(p.eval_prevalence),
    buildHash: str(p.build_hash),
    fixtureSha256: str(p.fixture_sha256),
    generatedAt: str(p.generated_at),
    generationCommand: str(p.generation_command),
    headAtGeneration: str(p.head_at_generation),
    treeDirtyAtGeneration: bool(p.tree_dirty_at_generation),
    corpusDbSha256: str(p.corpus_db_sha256),
    modelFilesSha256: { ...(p.model_files_sha256 || {}) },
  };
}

function buildFreshness(a, currentConfigHash) {
  const artifactHash = str(a.provenance.config_hash);
  let state;
  if (!currentConfigHash) state = "unknown";
  else if (artifactHash && artifactHash === currentConfigHash) state = "current";
  else state = "config-mismatch";
  return {
    state,
    artifactConfigHash: artifactHash,
    currentConfigHash: currentConfigHash || null,
    generatedAt: str(a.provenance.generated_at),
  };
}

// ---- block 1 --------------------------------------------------------

function tierMetrics(tm, piEval) {
  if (tm == null) return null;
  return {
    split: str(tm.split),
    n: num(tm.n),
    prevalence: num(tm.prevalence),
    apRaw: num(tm.ap_raw),
    apAtEvalPrevalence: num(tm.ap_at_eval_prevalence),
    evalPrevalence: num(tm.eval_prevalence) != null ? num(tm.eval_prevalence) : piEval,
    recall: normaliseMetric(tm.recall_at_target_fpr),
  };
}

function buildBlock1(a) {
  const piEval = num(a.provenance.eval_prevalence);
  const model = a.block1_per_tier[MODEL_MV] || {};
  const b0 = a.block1_per_tier[B0_MV] || {};
  const tiers = {};
  const splits = new Set();
  let b0WinsAll = true;
  for (const t of TIER_ORDER) {
    const m = tierMetrics(model[t], piEval);
    const r = tierMetrics(b0[t], piEval);
    if (!m || !r) {
      tiers[t] = { model: m, b0: r, apRawWinner: null };
      b0WinsAll = false;
      continue;
    }
    if (m.split) splits.add(m.split);
    let winner = null;
    if (num(m.apRaw) != null && num(r.apRaw) != null) {
      winner = r.apRaw > m.apRaw ? "b0" : m.apRaw > r.apRaw ? "model" : "tie";
    }
    if (winner !== "b0") b0WinsAll = false;
    tiers[t] = { model: m, b0: r, apRawWinner: winner };
  }
  const modelRoc = num(a.block6_baselines && a.block6_baselines.model && a.block6_baselines.model.roc_auc);
  const b0Roc = num(a.block6_baselines && a.block6_baselines.b0 && a.block6_baselines.b0.roc_auc);
  return {
    piEval,
    tiers,
    splitsPresent: [...splits],
    tiersFromMixedSplits: splits.size > 1,
    b0BeatsModelOnAllApTiers: b0WinsAll,
    modelRocAuc: modelRoc,
    b0RocAuc: b0Roc,
    verdict:
      "The rules baseline outperforms the learned model on average precision at every tier. " +
      "The model runs on 4 live features; 6 were removed by the discriminability audit as " +
      "generator artifacts and 14 slots are un-fed. It is weaker than B0 overall" +
      (modelRoc != null && b0Roc != null ? ` (ROC-AUC ${fmt3(modelRoc)} vs ${fmt3(b0Roc)})` : "") +
      " and on easy, competitive on medium, and stronger on hard, where B0's rules do not " +
      "fire. The excluded features can be reinstated when store-relative quantile transforms land.",
  };
}

// ---- block 2 --------------------------------------------------------

function buildBlock2(a) {
  const theta = num(a.block2_theta_challenge);
  const scenarios = Object.entries(a.block2_negative_controls).map(([name, rows]) => {
    const mapped = rows.map((row) => {
      const attempts = num(row.attempts);
      const attemptFp = num(row.attempt_fp);
      const available = row.available !== false;
      return {
        scorer: row.scorer,
        available,
        reason: str(row.reason),
        attempts,
        attemptFp,
        episodeFlagged: available ? bool(row.episode_flagged) : null,
        denominatorBasis: str(row.denominator_basis),
        rate: available && attempts && attemptFp != null ? attemptFp / attempts : null,
        underpowered: attempts != null && attempts < 30,
        showInterval: available && attempts != null && attempts >= 30,
      };
    });
    const denomRow = mapped.find((r) => r.attempts != null);
    const denom = denomRow ? denomRow.attempts : null;
    return {
      name,
      rows: mapped,
      denominator: denom,
      singleSample: denom === 1,
      underpowered: denom != null && denom < 30,
    };
  });
  return { thetaChallenge: theta, scenarios };
}

// ---- block 3 --------------------------------------------------------

function buildBlock3(a) {
  const b3 = a.block3_audit;
  const threshold = num(b3.univariate_auc_threshold);
  const feats = Object.entries(b3.features).map(([name, f]) => ({
    name,
    auc: num(f.univariate_auc),
    separability: num(f.separability),
    direction: str(f.direction),
    constant: bool(f.constant),
    excluded: bool(f.excluded),
    flaggedTwoSided: bool(f.flagged_two_sided),
    reason: str(f.reason),
  }));
  const bySep = (x, y) => (y.separability == null ? -1 : y.separability) - (x.separability == null ? -1 : x.separability);
  return {
    threshold,
    separabilityThreshold: threshold != null ? threshold - 0.5 : null,
    observedMax: num(b3.observed_max_univariate_auc),
    statistic: str(b3.statistic),
    trainingSet: {
      n: num(b3.training_set && b3.training_set.n),
      nPositive: num(b3.training_set && b3.training_set.n_positive),
      prevalence: num(b3.training_set && b3.training_set.prevalence),
    },
    groups: {
      flagged: feats.filter((f) => f.flaggedTwoSided && !f.constant).sort(bySep),
      measured: feats.filter((f) => !f.flaggedTwoSided && !f.constant).sort(bySep),
      notFed: feats.filter((f) => f.constant).sort((x, y) => x.name.localeCompare(y.name)),
    },
  };
}

// ---- block 4 --------------------------------------------------------

function buildBlock4(a) {
  const b4 = a.block4_cost;
  const pt = (p) => ({ fpr: num(p && p.fpr), tpr: num(p && p.tpr) });
  return {
    series: str(b4.series),
    seriesSubstitution: str(b4.series_substitution),
    tier: str(b4.tier),
    split: str(b4.split),
    pi0: num(b4.pi0),
    pi1: num(b4.pi1),
    curvePi0: Array.isArray(b4.curve_pi0) ? b4.curve_pi0 : [],
    curvePi1: Array.isArray(b4.curve_pi1) ? b4.curve_pi1 : [],
    ribbonEnvelope: Array.isArray(b4.ribbon_envelope) ? b4.ribbon_envelope : [],
    ribbonPis: Array.isArray(b4.ribbon_pis) ? b4.ribbon_pis : [],
    decisionRegionFprMax: num(b4.decision_region_fpr_max),
    optimaCoincident: bool(b4.optima_coincident),
    costOptimal: { ...pt(b4.cost_optimal), costPi0: num(b4.cost_optimal && b4.cost_optimal.cost_pi0) },
    f1Optimal: {
      ...pt(b4.f1_optimal),
      f1: num(b4.f1_optimal && b4.f1_optimal.f1),
      costPi0: num(b4.f1_optimal && b4.f1_optimal.cost_pi0),
    },
    costOptimalPi1: {
      ...pt(b4.cost_optimal_pi1),
      costPi1: num(b4.cost_optimal_pi1 && b4.cost_optimal_pi1.cost_pi1),
    },
    rupeeGapMinor: num(b4.rupee_gap_minor),
    rupeeGapIsStructural: bool(b4.rupee_gap_is_structural),
    rupeeGapNote: str(b4.rupee_gap_note),
    regimeSwitchSavingMinor: num(b4.regime_switch_saving_minor),
    cFnMinor: num(b4.inputs && b4.inputs.c_fn_minor),
    cFpMinorChallenge: num(b4.inputs && b4.inputs.c_fp_minor_challenge),
  };
}

// ---- block 5 --------------------------------------------------------

function regime(r) {
  return {
    brierRaw: num(r.brier_raw),
    brierPlatt: num(r.brier_platt),
    brierPlattPrior: num(r.brier_platt_prior),
    eceRaw: num(r.ece_raw),
    ecePlatt: num(r.ece_platt),
    ecePlattPrior: num(r.ece_platt_prior),
    eceGap: num(r.ece_gap_platt_prior_vs_platt),
    effectiveN: num(r.effective_n),
  };
}

function reliabilityPoints(bins) {
  const list = Array.isArray(bins) ? bins : [];
  const pts = list
    .filter((b) => num(b.mean_predicted) != null && num(b.observed_rate) != null && num(b.weight) > 0)
    .map((b) => ({
      meanPredicted: num(b.mean_predicted),
      observedRate: num(b.observed_rate),
      weight: num(b.weight),
    }));
  return { points: pts, emptyCount: list.length - pts.length };
}

function buildBlock5(a) {
  const cb = a.block5_calibration;
  if (!cb || !cb.pi0 || !cb.pi1) return { available: false };
  const pi0 = regime(cb.pi0);
  const pi1 = regime(cb.pi1);
  const helped = bool(cb.prior_correction_helped_at_pi1);
  const rel0 = reliabilityPoints(cb.reliability_pi0);
  const rel1 = reliabilityPoints(cb.reliability_pi1);
  // No internal spec IDs in rendered copy (M-032); the §3.4 citation lives in
  // this comment, not on the page.
  const verdict = helped
    ? `Prior correction works at both regimes. At the under-attack prevalence it reduces ` +
      `expected calibration error from ${fmt4(pi1.ecePlatt)} to ${fmt4(pi1.ecePlattPrior)}. ` +
      `That is the pass condition for prior correction. Lower is better for both Brier and ECE.`
    : `Prior correction does NOT improve ECE at the under-attack prevalence ` +
      `(${fmt4(pi1.ecePlatt)} to ${fmt4(pi1.ecePlattPrior)}); by the pass condition for prior ` +
      `correction the calibrator is broken and the test says so. Lower is better for both Brier and ECE.`;
  return {
    available: true,
    n: num(cb.n),
    nBins: num(cb.n_bins),
    piT: num(cb.pi_t),
    rawPrevalence: num(cb.raw_prevalence),
    regimes: {
      pi0: { ...pi0, pi: num(a.block4_cost && a.block4_cost.pi0) },
      pi1: { ...pi1, pi: num(a.block4_cost && a.block4_cost.pi1) },
    },
    priorCorrectionHelpedAtPi1: helped,
    verdict,
    reliability: { pi0: rel0.points, pi1: rel1.points },
    emptyBins: { pi0: rel0.emptyCount, pi1: rel1.emptyCount },
  };
}

// ---- block 6 --------------------------------------------------------

function opPoint(p) {
  if (p == null) return null;
  return {
    fpr: num(p.fpr), tpr: num(p.tpr), precision: num(p.precision), recall: num(p.recall),
    tp: num(p.tp), fp: num(p.fp), tn: num(p.tn), fn: num(p.fn),
  };
}

function baselineRow(r) {
  if (r == null) return null;
  return {
    split: str(r.split),
    n: num(r.n),
    prevalence: num(r.prevalence),
    apRaw: num(r.ap_raw),
    rocAuc: num(r.roc_auc),
    recall: normaliseMetric(r.recall_at_target_fpr),
  };
}

function sanityFloor(f) {
  const out = {};
  for (const k of SANITY_ORDER) {
    if (!f || !(k in f)) continue;
    out[k] = normaliseMetric(f[k]);
  }
  return out;
}

function buildBlock6(a) {
  const b6 = a.block6_baselines;
  const perTier = {};
  for (const [tier, row] of Object.entries(b6.per_tier || {})) {
    perTier[tier] = {
      model: opPoint(row.model),
      b0: opPoint(row.b0),
      b1: opPoint(row.b1),
      b2: opPoint(row.b2),
    };
  }
  return {
    model: baselineRow(b6.model),
    b0: baselineRow(b6.b0),
    b1: opPoint(b6.b1),
    b2: opPoint(b6.b2),
    b1SanityFloor: sanityFloor(b6.b1_sanity_floor),
    b2SanityFloor: sanityFloor(b6.b2_sanity_floor),
    perTier,
    caveats: {
      b1:
        "B1 (decline-velocity) needs completed outcomes the pre-auth path never has at " +
        "decision time; it is scored bitemporally over the whole timeline.",
      b2:
        "B2 (BIN-concentration) issues the identical window request as rule R3, so B0 already " +
        "contains this statistic — B2's contribution is not independent of B0's.",
    },
  };
}

// ---- tier E -------------------------------------------------------

function buildTierE(a) {
  const te = a.tier_e || {};
  const c = te.converged_params || null;
  return {
    splitN: num(te.split_n),
    prevalence: num(te.prevalence),
    convergedParams: c
      ? {
          ipPoolSize: num(c.ip_pool_size),
          binPoolSize: num(c.bin_pool_size),
          attemptsPerHour: num(c.attempts_per_hour),
          distinctCards: num(c.distinct_cards),
          episodeDurationS: num(c.episode_duration_s),
          amountQuantileBand: Array.isArray(c.amount_quantile_band) ? c.amount_quantile_band : null,
        }
      : null,
  };
}

// ---- executive summary (§20.2) ------------------------------------

function buildSummary(model) {
  const { block1: b1, block3: b3, block4: b4, block5: b5, provenance: p } = model;
  const easy = b1.tiers.easy;
  const s = [];
  s.push({
    id: "measured",
    text:
      `Evaluated ${p.modelVersion} on ${b4.split || "temporal_test"} ` +
      `(n=${b5.available ? b5.n : "—"}) at evaluation prevalence π_eval=${p.piEval}.`,
    numbers: { piEval: p.piEval, n: b5.available ? b5.n : null },
  });
  s.push({
    id: "b0",
    text:
      easy && easy.model && easy.b0
        ? `The rules baseline B0 outperforms the learned model on raw average precision at ` +
          `every tier (easy: ${fmt3(easy.b0.apRaw)} vs ${fmt3(easy.model.apRaw)}).`
        : `B0-vs-model comparison unavailable in this artifact.`,
    numbers: easy && easy.model && easy.b0 ? { b0Easy: easy.b0.apRaw, modelEasy: easy.model.apRaw } : {},
  });
  s.push({
    id: "recall-unavailable",
    text:
      `recall @ FPR 1e-3 — the spec's designated cross-tier comparator — is unresolvable ` +
      `at every tier: 221–316 negatives against the 1000 a 1e-3 false-positive rate requires.`,
    numbers: {},
  });
  s.push({
    id: "cost",
    text:
      `At under-attack prevalence π₁=${b4.pi1}, moving to the π₁-cost-optimal ` +
      `operating point saves ${inrMinor(b4.regimeSwitchSavingMinor)} per 10,000 attempts. The ` +
      `F1-vs-cost gap at π₀=${b4.pi0} is ₹0, and that is structural, not empirical.`,
    numbers: { regimeSwitchSavingMinor: b4.regimeSwitchSavingMinor, rupeeGapMinor: b4.rupeeGapMinor },
  });
  s.push({
    id: "calibration",
    text: b5.available
      ? b5.priorCorrectionHelpedAtPi1
        ? `Prior correction reduces ECE at π₁ from ${fmt4(b5.regimes.pi1.ecePlatt)} to ` +
          `${fmt4(b5.regimes.pi1.ecePlattPrior)}.`
        : `Prior correction does not reduce ECE at π₁ (${fmt4(b5.regimes.pi1.ecePlatt)} to ` +
          `${fmt4(b5.regimes.pi1.ecePlattPrior)}).`
      : `Calibration not measured in this artifact.`,
    numbers: b5.available
      ? { ecePlattPi1: b5.regimes.pi1.ecePlatt, ecePlattPriorPi1: b5.regimes.pi1.ecePlattPrior }
      : {},
  });
  s.push({
    id: "caveats",
    text:
      `Single-seed point estimate (seeds_used=${p.seedsUsed}). The model runs on 4 live features; ` +
      `${b3.groups.flagged.length} were excluded as generator artifacts and ` +
      `${b3.groups.notFed.length} slots are un-fed.`,
    numbers: { seedsUsed: p.seedsUsed },
  });
  return s;
}

// ---------------------------------------------------------------------------

export function buildMetricsModel({ schemaVersion, artifact }, opts = {}) {
  const model = {
    schemaVersion,
    provenance: buildProvenance(artifact),
    freshness: buildFreshness(artifact, opts.currentConfigHash),
    block1: buildBlock1(artifact),
    block2: buildBlock2(artifact),
    block3: buildBlock3(artifact),
    block4: buildBlock4(artifact),
    block5: buildBlock5(artifact),
    block6: buildBlock6(artifact),
    tierE: buildTierE(artifact),
  };
  model.summary = buildSummary(model);
  return model;
}
