// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §8.2 / FIX-FE-01 / RC-3.
// The single ingestion boundary for the committed D6 artifact.
//
//   * checks `schema_version` is one this build understands
//   * checks the seven top-level sections are present and object-shaped
//   * normalises the incompatible "unknown" encodings the artifact uses (the
//     rich `recall_at_target_fpr` object, the `Unavailable` envelope, a bare
//     `null`, and an absent key) into ONE internal shape so every component
//     sees exactly one missing-value concept
//   * throws a TYPED `ArtifactContractError` with an actionable message --
//     never a raw TypeError, and never returns `0` for a missing value.
//
// EXPLICITLY FORBIDDEN in this module (FE-T-CONTRACT-10): `?? 0`, `|| 0`,
// `Number(x) || 0`. A missing value is `{ available: false }`, full stop.

export const SUPPORTED_SCHEMA_VERSIONS = Object.freeze([1, 2]);

const REGEN_HINT =
  "regenerate it with `python -m eval.harness --split all --seed 42 " +
  "--corpus-db data/corpus/tollgate.db --model-dir models`";

const REQUIRED_SECTIONS = Object.freeze([
  "provenance",
  "block1_per_tier",
  "block2_negative_controls",
  "block3_audit",
  "block4_cost",
  "block5_calibration",
  "block6_baselines",
]);

export class ArtifactContractError extends Error {
  constructor(message, { path } = {}) {
    super(message);
    this.name = "ArtifactContractError";
    this.path = path === undefined ? null : path;
  }
}

const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const first = (...vals) => {
  for (const v of vals) if (v !== undefined && v !== null) return v;
  return null;
};

/**
 * One internal missing-value shape:
 *   { available: true,  value: <number>, reason: null,  detail: {...} }
 *   { available: false, value: null,     reason: <str>, detail: {...} }
 *
 * `reason` codes: "unresolvable" | "unreachable" | "unspecified" | "absent" |
 * "non-finite" | "malformed" | any backend Unavailable-envelope string.
 */
export function normaliseMetric(node) {
  if (node === undefined) {
    return { available: false, value: null, reason: "absent", detail: {} };
  }
  if (node === null) {
    return { available: false, value: null, reason: "unspecified", detail: {} };
  }
  if (typeof node === "number") {
    return Number.isFinite(node)
      ? { available: true, value: node, reason: null, detail: {} }
      : { available: false, value: null, reason: "non-finite", detail: {} };
  }
  if (!isObject(node)) {
    return { available: false, value: null, reason: "malformed", detail: {} };
  }

  // the rich recall object -- identified by `resolvable`
  if ("resolvable" in node) {
    const detail = {
      n_neg: first(node.n_neg),
      fpr_ci_low: first(node.fpr_ci_low, node.ci_low),
      fpr_ci_high: first(node.fpr_ci_high, node.ci_high),
      ci_basis: first(node.ci_basis),
      stored_value: first(node.value),
    };
    if (node.resolvable === false) {
      return { available: false, value: null, reason: "unresolvable", detail };
    }
    if (node.value === null || node.value === undefined) {
      return { available: false, value: null, reason: "unreachable", detail };
    }
    return { available: true, value: node.value, reason: null, detail };
  }

  // the Unavailable envelope -- identified by an explicit `available` flag
  if ("available" in node) {
    if (node.available) {
      return { available: true, value: first(node.value), reason: null, detail: {} };
    }
    return {
      available: false,
      value: null,
      reason: typeof node.reason === "string" && node.reason ? node.reason : "unavailable",
      detail: node.value === undefined ? {} : { stored_value: node.value },
    };
  }

  return { available: false, value: null, reason: "unrecognised-shape", detail: {} };
}

/**
 * Validate the raw imported artifact and return `{ schemaVersion, artifact }`.
 * Throws `ArtifactContractError` (caught by `<MetricsErrorBoundary>`), never a
 * bare TypeError, and never fabricates a value.
 */
export function parseArtifact(raw) {
  if (!isObject(raw)) {
    throw new ArtifactContractError(
      `the evaluation artifact is not an object (got ${raw === null ? "null" : typeof raw}); ${REGEN_HINT}`,
    );
  }

  const version = raw.schema_version;
  if (typeof version !== "number" || !Number.isInteger(version)) {
    throw new ArtifactContractError(
      `eval/outputs/d6.json has no integer schema_version (got ${JSON.stringify(version)}); ${REGEN_HINT}`,
      { path: "schema_version" },
    );
  }
  if (!SUPPORTED_SCHEMA_VERSIONS.includes(version)) {
    throw new ArtifactContractError(
      `eval/outputs/d6.json declares schema_version ${version}; this build supports ` +
        `${SUPPORTED_SCHEMA_VERSIONS.join("–")}. ${REGEN_HINT}`,
      { path: "schema_version" },
    );
  }

  for (const section of REQUIRED_SECTIONS) {
    if (!(section in raw)) {
      throw new ArtifactContractError(
        `eval/outputs/d6.json is missing the "${section}" section; ${REGEN_HINT}`,
        { path: section },
      );
    }
    if (!isObject(raw[section])) {
      const got = Array.isArray(raw[section]) ? "array" : typeof raw[section];
      throw new ArtifactContractError(
        `eval/outputs/d6.json "${section}" is not an object (got ${got}); ${REGEN_HINT}`,
        { path: section },
      );
    }
  }

  const b4 = raw.block4_cost;
  if (!Array.isArray(b4.curve_pi0) || b4.curve_pi0.length === 0) {
    throw new ArtifactContractError(
      `block4_cost.curve_pi0 is empty or not an array; ${REGEN_HINT}`,
      { path: "block4_cost.curve_pi0" },
    );
  }
  if (!Array.isArray(b4.curve_pi1) || b4.curve_pi1.length === 0) {
    throw new ArtifactContractError(
      `block4_cost.curve_pi1 is empty or not an array; ${REGEN_HINT}`,
      { path: "block4_cost.curve_pi1" },
    );
  }
  if (!isObject(raw.block3_audit.features) || Object.keys(raw.block3_audit.features).length === 0) {
    throw new ArtifactContractError(
      `block3_audit.features is empty; ${REGEN_HINT}`,
      { path: "block3_audit.features" },
    );
  }

  return { schemaVersion: version, artifact: raw };
}
