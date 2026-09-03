// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §15 FIX-M-010 / M-036 / M-021 / M-022.
//
// Not "another table". Three parts:
//   5a  the verdict, FIRST -- one sentence from `prior_correction_helped_at_pi1`,
//       with the direction stated once ("lower is better for both")
//   5b  the 2 x 6 grid: Brier {raw, Platt, Platt+prior} + ECE {raw, Platt,
//       Platt+prior}, per regime, with n / effective_n / raw_prevalence, and
//       an inline MAGNITUDE bar so 0.3955 and 0.0007 are not identical (M-036)
//   5c  both reliability diagrams, weight-proportional points, empty bins omitted

import {
  brier as fmtBrier,
  count as fmtCount,
  ece as fmtEce,
  pi as fmtPi,
  prevalence as fmtPrev,
} from "../../lib/format.js";
import ReliabilityDiagram from "../charts/ReliabilityDiagram.jsx";
import ScrollableTableRegion from "./ScrollableTableRegion.jsx";

const MAG_MAX = 0.4; // ECE/Brier stay well under this; the bar is a relative cue

function Mag({ value }) {
  const w = value == null ? 0 : Math.max(0, Math.min(1, value / MAG_MAX)) * 44;
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: 44,
        height: 4,
        marginLeft: 6,
        background: "var(--tg-surface-2)",
        borderRadius: 2,
        verticalAlign: "middle",
      }}
    >
      <span
        style={{
          display: "block",
          width: w,
          height: 4,
          background: "var(--viz-series)",
          borderRadius: 2,
        }}
      />
    </span>
  );
}

function Cell({ value, fmt, best }) {
  return (
    <td
      style={{
        padding: "4px 8px",
        textAlign: "right",
        color: best ? "var(--tg-text)" : "var(--tg-text-2)",
        fontWeight: best ? 600 : 400,
      }}
    >
      {fmt(value)}
      <Mag value={value} />
    </td>
  );
}

function argmin(values) {
  let bi = -1;
  let bv = Infinity;
  values.forEach((v, i) => {
    if (typeof v === "number" && v < bv) {
      bv = v;
      bi = i;
    }
  });
  return bi;
}

export default function Block5Calibration({ block5 }) {
  if (!block5.available) {
    return <p className="tg-caption">not measured in this artifact.</p>;
  }
  const { regimes, n, verdict, reliability, emptyBins } = block5;
  const order = ["pi0", "pi1"];
  const regimeLabel = (k) =>
    k === "pi0"
      ? `π₀ = ${fmtPi(regimes.pi0.pi)} (steady state)`
      : `π₁ = ${fmtPi(regimes.pi1.pi)} (under attack)`;

  const brierCols = ["brierRaw", "brierPlatt", "brierPlattPrior"];
  const eceCols = ["eceRaw", "ecePlatt", "ecePlattPrior"];
  const bestBrier = Object.fromEntries(
    order.map((k) => [k, argmin(brierCols.map((c) => regimes[k][c]))]),
  );
  const bestEce = Object.fromEntries(
    order.map((k) => [k, argmin(eceCols.map((c) => regimes[k][c]))]),
  );

  return (
    <div>
      {/* 5a -- the verdict, first */}
      <p className="tg-body" style={{ margin: "0 0 12px", color: "var(--tg-text)" }}>
        {verdict}
      </p>

      {/* 5b -- the 2 x 6 grid */}
      <ScrollableTableRegion label="Calibration metrics grid, scrollable table">
      <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
        <caption
          className="tg-caption"
          style={{ textAlign: "left", color: "var(--tg-text-mute)", marginBottom: 6 }}
        >
          lower is better · Brier and ECE, {"{raw · Platt · Platt+prior}"} · n = {fmtCount(n)} · raw
          prevalence {fmtPrev(block5.rawPrevalence)}
        </caption>
        <thead>
          <tr className="tg-label">
            <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>regime</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>Brier raw</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>Brier Platt</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>Brier Platt+prior</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>ECE raw</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>ECE Platt</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>ECE Platt+prior</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>effective n</th>
          </tr>
        </thead>
        <tbody>
          {order.map((k) => {
            const r = regimes[k];
            return (
              <tr key={k} style={{ borderTop: "1px solid var(--tg-hairline)" }}>
                <th
                  scope="row"
                  style={{ textAlign: "left", padding: "4px 8px", color: "var(--tg-text-2)" }}
                >
                  {regimeLabel(k)}
                </th>
                <Cell value={r.brierRaw} fmt={fmtBrier} best={bestBrier[k] === 0} />
                <Cell value={r.brierPlatt} fmt={fmtBrier} best={bestBrier[k] === 1} />
                <Cell value={r.brierPlattPrior} fmt={fmtBrier} best={bestBrier[k] === 2} />
                <Cell value={r.eceRaw} fmt={fmtEce} best={bestEce[k] === 0} />
                <Cell value={r.ecePlatt} fmt={fmtEce} best={bestEce[k] === 1} />
                <Cell value={r.ecePlattPrior} fmt={fmtEce} best={bestEce[k] === 2} />
                <td
                  style={{ padding: "4px 8px", textAlign: "right", color: "var(--tg-text-mute)" }}
                >
                  {r.effectiveN == null ? "n/a" : r.effectiveN.toFixed(1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </ScrollableTableRegion>

      {/* 5c -- reliability diagrams, side by side */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 16,
          marginTop: 16,
        }}
      >
        <ReliabilityDiagram
          id="rel-pi0"
          label={`π₀ = ${fmtPi(regimes.pi0.pi)}`}
          points={reliability.pi0}
          emptyCount={emptyBins.pi0}
        />
        <ReliabilityDiagram
          id="rel-pi1"
          label={`π₁ = ${fmtPi(regimes.pi1.pi)}`}
          points={reliability.pi1}
          emptyCount={emptyBins.pi1}
        />
      </div>
    </div>
  );
}
