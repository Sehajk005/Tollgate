// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §17.2 FIX-M-029 / M-009 / M-022.
//
// Eval Protocol §9, verbatim: "Every reported figure carries, in the artifact
// itself: seed, config_hash, model_version, policy_version, π_eval, and the
// split name. A number that cannot state those six things does not go on a
// slide." All six render here, without interaction, plus `seeds_used` (M-022)
// and a human `generated_at`.
//
// Staleness (§17.2): three states. `build_hash` divergence alone is NOT
// staleness (HEAD moves every commit) -- `config_hash` is the signal.
//   current          -- artifact config_hash == this build's -> neutral line
//   config-mismatch  -- differ -> a PROMINENT warning, both hashes shown
//   unknown          -- this build could not compute a current hash -> honest
//                       "not verifiable", NEVER a false "current"

import { pi as fmtPi } from "../../lib/format.js";

function humanDate(iso) {
  if (typeof iso !== "string") return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(
    d.getUTCHours(),
  )}:${p(d.getUTCMinutes())} UTC`;
}

export default function ProvenanceHeader({ provenance, freshness, primarySplit }) {
  const p = provenance;
  return (
    <header>
      <p
        className="tg-mono-caption"
        style={{ color: "var(--tg-text-2)", margin: "4px 0 0" }}
        data-testid="prov-identity"
      >
        seed {p.seed} · config {p.configHash ? p.configHash.slice(0, 12) : "n/a"} · model{" "}
        {p.modelVersion} · policy {p.policyVersion} · π_eval {fmtPi(p.piEval)} · split{" "}
        {primarySplit} · seeds_used {p.seedsUsed}
      </p>
      <p className="tg-mono-caption" style={{ color: "var(--tg-text-mute)", margin: "2px 0 0" }}>
        Block 1 also draws the evasive tier from <code>tier_e</code>; Block 3 is on the training
        set. Single-seed point estimate — figures to 3–4 dp imply a precision one seed cannot
        support.
      </p>

      {freshness.state === "config-mismatch" ? (
        <p
          role="alert"
          className="tg-body"
          style={{
            margin: "8px 0 0",
            padding: "8px 12px",
            background: "var(--tg-elevated-wash)",
            borderLeft: "3px solid var(--tg-elevated)",
            color: "var(--tg-text)",
          }}
        >
          Configs have changed since this evaluation was generated — regenerate before relying on
          these numbers. artifact {freshness.artifactConfigHash?.slice(0, 12)} · current{" "}
          {freshness.currentConfigHash?.slice(0, 12)}. Generated {humanDate(p.generatedAt)}.
        </p>
      ) : freshness.state === "current" ? (
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "6px 0 0" }}>
          Evaluation snapshot · generated {humanDate(p.generatedAt)} · configs unchanged since.
        </p>
      ) : (
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "6px 0 0" }}>
          Evaluation snapshot · generated {humanDate(p.generatedAt)} · freshness not verifiable in
          this build.
        </p>
      )}
    </header>
  );
}
