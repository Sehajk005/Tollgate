import { useMemo } from "react";

import d6 from "../../../../eval/outputs/d6.json";
import { parseArtifact } from "../lib/d6Contract.js";
import { buildMetricsModel } from "../lib/metricsModel.js";
import { count as fmtCount } from "../lib/format.js";
import Block1PerTier from "../components/metrics/Block1PerTier.jsx";
import Block2NegativeControls from "../components/metrics/Block2NegativeControls.jsx";
import CostCurve from "../components/charts/CostCurve.jsx";
import AuditBars from "../components/charts/AuditBars.jsx";
import Block5Calibration from "../components/metrics/Block5Calibration.jsx";
import Block6Baselines from "../components/metrics/Block6Baselines.jsx";
import ProvenanceHeader from "../components/metrics/ProvenanceHeader.jsx";
import MethodologyPanel from "../components/metrics/MethodologyPanel.jsx";

// D6 -- Metrics & Evaluation (App Flow §5 D6). Six blocks, in argument order,
// rendered from a BUILD-TIME `import` of the committed artifact
// eval/outputs/d6.json -- no network call, no live subscription (App Flow §5:
// "Static render. No live computation on stage.").
//
// Remediation (METRICS-REMEDIATION-PLAN-2026-09-02.md §7): the screen is a
// COMPOSITION over `buildMetricsModel(parseArtifact(artifact))`, not a curator
// that hand-picks fields. `parseArtifact` runs INSIDE render (useMemo) so a
// malformed artifact throws an `ArtifactContractError` that <MetricsErrorBoundary>
// catches -- it never crashes the module or the shell.
//
// Blocks referenced via the view model: block1_per_tier, block2_negative_controls,
// block3_audit, block4_cost, block5_calibration, block6_baselines (+ provenance,
// tier_e). Every block is a dedicated, individually-tested component.

// §17.2 -- the current working tree's config_hash, injected at build time by a
// Vite `define` (vite.config.js). `null` in a bare build with no Python -> the
// page discloses "freshness not verifiable", never a false "current".
const CURRENT_CONFIG_HASH =
  typeof __TG_CONFIG_HASH__ !== "undefined" ? __TG_CONFIG_HASH__ : null;

function ExecutiveSummary({ summary }) {
  return (
    <section
      aria-label="Executive summary"
      style={{
        margin: "16px 0 24px",
        padding: "12px 16px",
        borderLeft: "2px solid var(--tg-hairline-firm)",
        background: "var(--tg-surface-1)",
      }}
    >
      <h2 className="tg-label" style={{ margin: "0 0 8px", color: "var(--tg-text-2)" }}>
        Executive summary
      </h2>
      {summary.map((s) => (
        <p key={s.id} className="tg-body" style={{ margin: "0 0 6px", color: "var(--tg-text)" }}>
          {s.text}
        </p>
      ))}
    </section>
  );
}

function Section({ n, title, children }) {
  return (
    <section style={{ marginBottom: 32, borderTop: "1px solid var(--tg-hairline)", paddingTop: 12 }}>
      <h2 className="tg-display-sm" style={{ margin: "0 0 6px" }}>
        {n}. {title}
      </h2>
      {children}
    </section>
  );
}


function TierEFooter({ tierE }) {
  const c = tierE.convergedParams;
  return (
    <p className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
      Tier E (adaptive adversary): split n = {fmtCount(tierE.splitN)}, prevalence{" "}
      {tierE.prevalence == null ? "n/a" : tierE.prevalence.toFixed(3)}
      {c ? ` · ${c.ipPoolSize} IPs, ${c.binPoolSize} BINs, ${c.attemptsPerHour}/h` : ""}.
    </p>
  );
}

export default function D6Metrics({ artifact = d6, currentConfigHash = CURRENT_CONFIG_HASH } = {}) {
  const model = useMemo(
    () => buildMetricsModel(parseArtifact(artifact), { currentConfigHash }),
    [artifact, currentConfigHash],
  );

  return (
    <div className="tg-metrics" style={{ padding: 24, maxWidth: 1280, margin: "0 auto" }}>
      <h1 className="tg-display-md" style={{ margin: "0 0 4px" }}>Metrics &amp; Evaluation</h1>
      <ProvenanceHeader
        provenance={model.provenance}
        freshness={model.freshness}
        primarySplit={model.block4.split || "temporal_test"}
      />

      <ExecutiveSummary summary={model.summary} />

      <Section n={1} title="Per-tier performance">
        <Block1PerTier block1={model.block1} />
      </Section>
      <Section n={2} title="Negative-control false positives">
        <Block2NegativeControls block2={model.block2} />
      </Section>
      <Section n={3} title="Discriminability audit">
        <AuditBars block3={model.block3} />
      </Section>
      <Section n={4} title="Cost curves">
        <CostCurve block4={model.block4} />
      </Section>
      <Section n={5} title="Calibration">
        <Block5Calibration block5={model.block5} />
      </Section>
      <Section n={6} title="Baseline comparison">
        <Block6Baselines block6={model.block6} />
      </Section>

      <TierEFooter tierE={model.tierE} />

      <MethodologyPanel
        provenance={model.provenance}
        block3={model.block3}
        block5={model.block5}
        tierE={model.tierE}
      />
    </div>
  );
}
