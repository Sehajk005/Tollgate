import d6 from "../../../../eval/outputs/d6.json";
import BarRow from "../components/charts/BarRow.jsx";
import AuditBars from "../components/charts/AuditBars.jsx";
import CostCurve from "../components/charts/CostCurve.jsx";

// Day 8, Step 5 -- D6 Metrics & Evaluation (App Flow SS5 D6). Six blocks,
// rendered from a BUILD-TIME `import` of the committed artifact
// `eval/outputs/d6.json`. No network call, no live subscription, no runtime
// data path to remove: this is the strongest possible form of "zero live
// computation" (App Flow SS5: "Static render. No live computation on stage.").
// Pinned by tests/acceptance/test_d6_static.py.

const TIERS = ["easy", "medium", "hard", "evasive"];

function Section({ n, title, children }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <h2 className="tg-display-sm" style={{ margin: "0 0 4px" }}>
        {n}. {title}
      </h2>
      {children}
    </section>
  );
}

function Block1() {
  const model = d6.block1_per_tier["l1-lgbm-v1"] || {};
  const b0 = d6.block1_per_tier["rules-only-v0"] || {};
  const recall = (tm) => (tm && tm.recall_at_target_fpr ? tm.recall_at_target_fpr.value : null);
  return (
    <>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
        recall @ FPR 1e-3 per tier. The evasive bar gets no special treatment — it is simply the
        fourth bar, at whatever height it is (UIUX v2 SS6.13).
      </p>
      <div className="tg-label" style={{ color: "var(--tg-text-2)", margin: "8px 0 2px" }}>l1-lgbm-v1</div>
      {TIERS.map((t) => (
        <BarRow key={`m-${t}`} label={t} value={recall(model[t])} max={1} />
      ))}
      <div className="tg-label" style={{ color: "var(--tg-text-2)", margin: "10px 0 2px" }}>B0 — live rules</div>
      {TIERS.map((t) => (
        <BarRow key={`b0-${t}`} label={t} value={recall(b0[t])} max={1} />
      ))}
    </>
  );
}

function Block2() {
  const rows = d6.block2_negative_controls;
  return (
    <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr className="tg-label">
          <th style={{ textAlign: "left", padding: "4px 8px" }}>scenario</th>
          <th style={{ textAlign: "left", padding: "4px 8px" }}>scorer</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>episode FP</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>attempt FP</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(rows).flatMap(([scenario, list]) =>
          list.map((r, i) => (
            <tr key={`${scenario}-${r.scorer}`} style={{ borderTop: "1px solid var(--tg-hairline)" }}>
              <td style={{ padding: "4px 8px", color: "var(--tg-text-2)" }}>{i === 0 ? scenario : ""}</td>
              <td style={{ padding: "4px 8px" }}>{r.scorer}</td>
              <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.episode_fp}/{r.episodes}</td>
              <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.attempt_fp}/{r.attempts}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function Block5() {
  const cb = d6.block5_calibration;
  if (!cb || !cb.pi0) return <p className="tg-caption">not measured in this artifact.</p>;
  const row = (label, r) => (
    <tr style={{ borderTop: "1px solid var(--tg-hairline)" }}>
      <td style={{ padding: "4px 8px", color: "var(--tg-text-2)" }}>{label}</td>
      <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.brier_platt?.toFixed(4)}</td>
      <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.brier_platt_prior?.toFixed(4)}</td>
      <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.ece_platt?.toFixed(4)}</td>
      <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.ece_platt_prior?.toFixed(4)}</td>
    </tr>
  );
  return (
    <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr className="tg-label">
          <th style={{ textAlign: "left", padding: "4px 8px" }}>regime</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>Brier Platt</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>Brier Platt+prior</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>ECE Platt</th>
          <th style={{ textAlign: "right", padding: "4px 8px" }}>ECE Platt+prior</th>
        </tr>
      </thead>
      <tbody>
        {row("π₀ = 0.001 (steady state)", cb.pi0)}
        {row("π₁ = 0.9 (under attack)", cb.pi1)}
      </tbody>
    </table>
  );
}

function Block6() {
  const b = d6.block6_baselines;
  return (
    <>
      {b.b0 && (
        <BarRow
          label="B0 — live rules"
          value={b.b0.recall_at_target_fpr?.value}
          max={1}
          valueText={`recall ${b.b0.recall_at_target_fpr?.value == null ? "n/a" : b.b0.recall_at_target_fpr.value.toFixed(3)}`}
        />
      )}
      {b.b1 && <BarRow label="B1 — decline-velocity" value={b.b1.tpr} max={1} valueText={`TPR ${b.b1.tpr.toFixed(3)}`} />}
      {b.b2 && <BarRow label="B2 — BIN-concentration" value={b.b2.tpr} max={1} valueText={`TPR ${b.b2.tpr.toFixed(3)}`} />}
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", marginTop: 6 }}>
        B2 shares R3's statistic, so B0 already contains it. B1 needs completed outcomes the pre-auth
        path never has at decision time.
      </p>
    </>
  );
}

export default function D6Metrics() {
  const te = d6.tier_e || {};
  return (
    <div style={{ padding: 24, maxWidth: 900 }}>
      <h1 className="tg-display-md" style={{ margin: "0 0 4px" }}>Metrics &amp; Evaluation</h1>
      <p className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
        static render · build {d6.provenance.build_hash?.slice(0, 12)} · config{" "}
        {d6.provenance.config_hash?.slice(0, 12)} · seed {d6.provenance.seed} · model{" "}
        {d6.provenance.model_version}
      </p>

      <Section n={1} title="Per-tier performance"><Block1 /></Section>
      <Section n={2} title="Negative-control false positives"><Block2 /></Section>
      <Section n={3} title="Discriminability audit">
        <AuditBars features={d6.block3_audit.features || {}} />
      </Section>
      <Section n={4} title="Cost curves">
        <CostCurve b4={d6.block4_cost} />
      </Section>
      <Section n={5} title="Calibration"><Block5 /></Section>
      <Section n={6} title="Baseline comparison"><Block6 /></Section>

      <p className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
        Tier E (adaptive adversary): split n={te.split_n}, prevalence{" "}
        {te.prevalence == null ? "n/a" : te.prevalence.toFixed(3)}
        {te.converged_params
          ? ` · ${te.converged_params.ip_pool_size} IPs, ${te.converged_params.bin_pool_size} BINs, ${te.converged_params.attempts_per_hour}/h`
          : ""}
        .
      </p>
    </div>
  );
}
