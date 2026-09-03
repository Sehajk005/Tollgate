// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §20.3.
//
// Expandable, collapsed by default. Holds what belongs ON the page but NOT in
// the argument: hashes, the generation command, the seed detail, the audit
// statistic + training set, the tier_e converged parameters not shown in the
// footer, and the split composition. This is how the G-class "intentional
// omission" values (fixture_sha256, calibrator_version) stop being omissions --
// present, addressable and testable, just not competing with the argument.

import { useState } from "react";

function Row({ label, value }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(12rem, 16rem) 1fr",
        gap: 12,
        padding: "2px 0",
      }}
    >
      <span className="tg-mono-caption" style={{ color: "var(--tg-text-2)" }}>
        {label}
      </span>
      <span
        className="tg-mono-caption"
        style={{ color: "var(--tg-text-mute)", overflowWrap: "anywhere" }}
      >
        {value == null || value === "" ? "n/a" : String(value)}
      </span>
    </div>
  );
}

export default function MethodologyPanel({ provenance, block3, block5, tierE }) {
  const [open, setOpen] = useState(false);
  const p = provenance;
  const t = block3.trainingSet || {};
  const c = tierE.convergedParams || {};

  return (
    <section style={{ marginTop: 24, borderTop: "1px solid var(--tg-hairline)", paddingTop: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="tg-label"
        style={{
          background: "transparent",
          border: "none",
          padding: "2px 0",
          cursor: "pointer",
          color: "var(--tg-text-2)",
        }}
      >
        Methodology &amp; provenance {open ? "▾" : "▸"}
      </button>
      {open && (
        <div data-testid="methodology-body" style={{ marginTop: 8 }}>
          <Row label="config_hash" value={p.configHash} />
          <Row label="build_hash" value={p.buildHash} />
          <Row label="head_at_generation" value={p.headAtGeneration} />
          <Row label="tree_dirty_at_generation" value={String(p.treeDirtyAtGeneration)} />
          <Row label="fixture_sha256" value={p.fixtureSha256} />
          <Row label="corpus_db_sha256" value={p.corpusDbSha256} />
          {Object.entries(p.modelFilesSha256 || {}).map(([k, v]) => (
            <Row key={k} label={`model_files_sha256[${k}]`} value={v} />
          ))}
          <Row label="calibrator_version" value={p.calibratorVersion} />
          <Row label="generation_command" value={p.generationCommand} />
          <Row
            label="seed / base_seed / seeds_used"
            value={`${p.seed} / ${p.baseSeed} / ${p.seedsUsed}`}
          />

          <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "12px 0 2px" }}>
            discriminability audit — training set
          </h3>
          <Row label="statistic" value={block3.statistic} />
          <Row
            label="n / n_positive / prevalence"
            value={`${t.n} / ${t.nPositive} / ${t.prevalence}`}
          />

          <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "12px 0 2px" }}>
            calibration
          </h3>
          <Row label="n_bins" value={block5.available ? block5.nBins : "n/a"} />
          <Row label="pi_t" value={block5.available ? block5.piT : "n/a"} />
          <Row label="raw_prevalence" value={block5.available ? block5.rawPrevalence : "n/a"} />

          <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "12px 0 2px" }}>
            tier E — converged adversary parameters
          </h3>
          <Row label="distinct_cards" value={c.distinctCards} />
          <Row label="episode_duration_s" value={c.episodeDurationS} />
          <Row
            label="amount_quantile_band"
            value={
              Array.isArray(c.amountQuantileBand) ? `[${c.amountQuantileBand.join(", ")}]` : "n/a"
            }
          />

          <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "12px 0 2px" }}>
            split composition
          </h3>
          <Row label="Blocks 1 (easy/medium/hard), 4, 6" value="temporal_test" />
          <Row label="Block 1 (evasive) / tier E" value="tier_e" />
          <Row label="Block 3" value="training set" />
        </div>
      )}
    </section>
  );
}
