// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §14.2 / §21.2 -- the cost
// chart's genuine accessible data alternative (real text, not a caption). The
// exact numbers behind the three SVG panels.

import { fpr as fmtFpr, inr as fmtInr, rate as fmtRate, pi as fmtPi } from "../../lib/format.js";
import ScrollableTableRegion from "./ScrollableTableRegion.jsx";

export default function OperatingPointTable({ block4 }) {
  const b = block4;
  const rows = [
    {
      name: b.optimaCoincident ? "cost-optimal = F1-optimal (π₀)" : "cost-optimal (π₀)",
      fpr: b.costOptimal.fpr,
      tpr: b.costOptimal.tpr,
      cost: b.costOptimal.costPi0,
      regime: `π₀ = ${fmtPi(b.pi0)}`,
    },
  ];
  if (!b.optimaCoincident) {
    rows.push({
      name: "F1-optimal (π₀)",
      fpr: b.f1Optimal.fpr,
      tpr: b.f1Optimal.tpr,
      cost: b.f1Optimal.costPi0,
      regime: `π₀ = ${fmtPi(b.pi0)}`,
    });
  }
  rows.push({
    name: "cost-optimal (π₁ — under attack)",
    fpr: b.costOptimalPi1.fpr,
    tpr: b.costOptimalPi1.tpr,
    cost: b.costOptimalPi1.costPi1,
    regime: `π₁ = ${fmtPi(b.pi1)}`,
  });

  return (
    <ScrollableTableRegion label="Cost-curve operating points, scrollable table">
    <table
      className="tg-mono-data tg-num"
      style={{ borderCollapse: "collapse", width: "100%", marginTop: 8 }}
    >
      <caption
        className="tg-caption"
        style={{ textAlign: "left", color: "var(--tg-text-mute)", marginBottom: 6 }}
      >
        operating points — exact values behind the panels · decision region FPR ≤{" "}
        {fmtFpr(b.decisionRegionFprMax)}
      </caption>
      <thead>
        <tr className="tg-label">
          <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>point</th>
          <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>FPR</th>
          <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>TPR</th>
          <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>expected cost / 10k</th>
          <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>regime</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name} style={{ borderTop: "1px solid var(--tg-hairline)" }}>
            <th
              scope="row"
              style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
            >
              {r.name}
            </th>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtFpr(r.fpr)}</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtRate(r.tpr)}</td>
            <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtInr(r.cost)}</td>
            <td style={{ padding: "4px 8px", textAlign: "left", color: "var(--tg-text-mute)" }}>
              {r.regime}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </ScrollableTableRegion>
  );
}
