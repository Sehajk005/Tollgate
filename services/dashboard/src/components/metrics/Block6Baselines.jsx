// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §16 FIX-M-008 / M-038 / M-026 / M-002.
//
// A baseline comparison that HAS a subject: the learned model row, the B3
// sanity floor, and a per-tier matrix (App Flow §5 D6 #6: "beside the model, on
// every tier"). Three verified-accurate caveats are preserved verbatim in
// meaning:
//   B1 -- needs completed outcomes the pre-auth path never has at decision time
//   B2 -- shares R3's statistic, so B0 already contains it (NOT independent of B0)
//   B0 and B1 are never reported as one (Eval §8)
//
// M-038: `always_positive` sanity recall is null because a constant scorer has
// <= 2 distinct ROC points -- it renders its reason, never a number, never 0.
// M-026: value cells are a fixed-height two-line structure so no row wraps
// taller than its neighbours.

import { ap as fmtAp, auc as fmtAuc, fpr as fmtFpr, rate as fmtRate } from "../../lib/format.js";
import ScrollableTableRegion from "./ScrollableTableRegion.jsx";

const TIERS = ["easy", "medium", "hard", "evasive"];
const ROW_MIN_H = 34;

function recallText(m) {
  if (m == null) return "—";
  if (m.available) return fmtRate(m.value);
  if (m.reason === "unresolvable") {
    const n = m.detail && m.detail.n_neg != null ? m.detail.n_neg : null;
    return n == null ? "not resolvable" : `not resolvable · n_neg=${n}`;
  }
  return m.reason || "unavailable";
}

function OpCell({ point }) {
  if (point == null || point.tpr == null) {
    return <td style={{ padding: "4px 8px", textAlign: "right", height: ROW_MIN_H }}>—</td>;
  }
  return (
    <td style={{ padding: "4px 8px", textAlign: "right", height: ROW_MIN_H }}>
      <div>{fmtRate(point.tpr)}</div>
      <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
        fpr {fmtFpr(point.fpr)} · prec {point.precision == null ? "n/a" : fmtRate(point.precision)}
      </div>
    </td>
  );
}

function SanityFloor({ title, floor }) {
  const order = ["perfect", "random", "inverted", "always_positive"];
  return (
    <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "4px 0" }}>
      {title}:{" "}
      {order
        .filter((k) => floor[k])
        .map((k) => {
          const m = floor[k];
          const val = m.available ? fmtRate(m.value) : `${m.reason || "unreachable"}`;
          return `${k} ${val}`;
        })
        .join(" · ")}
    </p>
  );
}

export default function Block6Baselines({ block6 }) {
  const b = block6;

  return (
    <div>
      {/* Overall */}
      <ScrollableTableRegion label="Baseline comparison, overall, scrollable table">
      <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
        <caption
          className="tg-caption"
          style={{ textAlign: "left", color: "var(--tg-text-mute)", marginBottom: 6 }}
        >
          overall — the model beside every baseline · recall @ FPR 1e-3 is unresolvable at
          n_neg = 758
        </caption>
        <thead>
          <tr className="tg-label">
            <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>series</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>AP</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>ROC-AUC</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>recall @ FPR 1e-3</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>TPR @ own op-point</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderTop: "1px solid var(--tg-hairline)", height: ROW_MIN_H }}>
            <th
              scope="row"
              style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
            >
              model l1-lgbm-v1
            </th>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtAp(b.model && b.model.apRaw)}</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>
              {fmtAuc(b.model && b.model.rocAuc)}
            </td>
            <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--tg-text-mute)" }}>
              {recallText(b.model && b.model.recall)}
            </td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
          </tr>
          <tr style={{ borderTop: "1px solid var(--tg-hairline)", height: ROW_MIN_H }}>
            <th
              scope="row"
              style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
            >
              B0 rules
            </th>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtAp(b.b0 && b.b0.apRaw)}</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtAuc(b.b0 && b.b0.rocAuc)}</td>
            <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--tg-text-mute)" }}>
              {recallText(b.b0 && b.b0.recall)}
            </td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
          </tr>
          <tr style={{ borderTop: "1px solid var(--tg-hairline)", height: ROW_MIN_H }}>
            <th
              scope="row"
              style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
            >
              B1 decline-velocity
            </th>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <OpCell point={b.b1} />
          </tr>
          <tr style={{ borderTop: "1px solid var(--tg-hairline)", height: ROW_MIN_H }}>
            <th
              scope="row"
              style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
            >
              B2 BIN-concentration
            </th>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>—</td>
            <OpCell point={b.b2} />
          </tr>
        </tbody>
      </table>
      </ScrollableTableRegion>

      {/* B3 sanity floor */}
      <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "16px 0 2px" }}>
        B3 sanity floor
      </h3>
      <SanityFloor title="recall at the B1 operating FPR" floor={b.b1SanityFloor} />
      <SanityFloor title="recall at the B2 operating FPR" floor={b.b2SanityFloor} />
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "4px 0" }}>
        always_positive is unreachable — a constant scorer has no intermediate operating point,
        so its recall at a matched FPR is undefined (not a measured 0).
      </p>

      {/* Per tier */}
      <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "16px 0 2px" }}>
        per tier — TPR at each series' operating point
      </h3>
      <ScrollableTableRegion label="Baseline comparison, per tier, scrollable table">
      <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
        <caption
          className="tg-caption"
          style={{ textAlign: "left", color: "var(--tg-text-mute)", marginBottom: 6 }}
        >
          beside the model, on every tier
        </caption>
        <thead>
          <tr className="tg-label">
            <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>tier</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>model</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>B0</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>B1</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>B2</th>
          </tr>
        </thead>
        <tbody>
          {TIERS.map((t) => {
            const row = b.perTier[t] || {};
            return (
              <tr key={t} style={{ borderTop: "1px solid var(--tg-hairline)" }}>
                <th
                  scope="row"
                  style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
                >
                  {t}
                </th>
                {["model", "b0", "b1", "b2"].map((s) => (
                  <td key={s} style={{ padding: "4px 8px", textAlign: "right" }}>
                    {row[s] && row[s].tpr != null ? fmtRate(row[s].tpr) : "—"}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      </ScrollableTableRegion>

      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", marginTop: 8 }}>
        {b.caveats.b1}
      </p>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "4px 0 0" }}>
        {b.caveats.b2}
      </p>
    </div>
  );
}
