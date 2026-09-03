// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §14 -- FIX-M-003/004/005/034/037/021/014.
//
// Rebuilt as THREE panels + an operating-point table, not one chart (§14.2):
//   A  decision region, π₀   -- FPR in [0, decision_region_fpr_max], y LOG,
//                               with the prevalence-sensitivity ribbon
//   B  full range, π₀ (context) -- y LOG, ribbon, Panel-A window shaded
//   C  full range, π₁        -- y LOG on its OWN scale, NO ribbon (π₁ = 0.9 is
//                               outside the ribbon's [1e-4, 1e-2] range, so a
//                               band here would imply a sensitivity it doesn't have)
//
// Log y is a disclosed monotone transform (every axis says "(log scale)"), not
// a distortion -- the exact values are in OperatingPointTable. Optima are INSET
// filled-circle markers with collision-avoided callouts, never full-height
// rules identical to the y-axis (M-004). π values come from the artifact
// (M-021); every rupee string goes through format.inr (M-014).

import {
  buildPanelGeometry,
  costDomain,
  markerLayout,
  ribbonEnvelope,
  ribbonPath,
} from "./costCurveGeometry.js";
import OperatingPointTable from "../metrics/OperatingPointTable.jsx";
import { fpr as fmtFpr, inr as fmtInr, pi as fmtPi, rate as fmtRate } from "../../lib/format.js";

const W = 520;
const H = 200;
const M = { top: 30, right: 20, bottom: 34, left: 66 };
const FS = 11; // §21.1 -- SVG labels rise from 9 to 11

function tickLabel(v) {
  if (v >= 1_000_000) return `₹${Math.round(v / 100_000) / 10}M`;
  if (v >= 1000) return `₹${Math.round(v / 1000)}k`;
  return `₹${Math.round(v)}`;
}

function Panel({ id, title, desc, geo, ribbonD, markers, xMax, windowFrac }) {
  const { plot } = geo;
  const placed = markerLayout(markers, {
    plotTop: plot.top,
    plotBottom: plot.bottom,
    plotLeft: plot.left,
    plotRight: W - 2, // keep callouts inside the viewBox, not just the plot
    calloutW: 150,
    lineH: FS + 1,
  });
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-labelledby={`${id}-t ${id}-d`}
      style={{ display: "block", minHeight: 160 }}
    >
      <title id={`${id}-t`}>{title}</title>
      <desc id={`${id}-d`}>{desc}</desc>

      {/* horizontal y-axis label, ABOVE the axis (M-034) -- never rotated */}
      <text x={2} y={14} fill="var(--tg-text)" fontSize={FS}>
        expected cost, ₹ / 10,000 attempts (log scale)
      </text>

      <line x1={plot.left} y1={plot.top} x2={plot.left} y2={plot.bottom} stroke="var(--viz-grid)" />
      <line x1={plot.left} y1={plot.bottom} x2={plot.right} y2={plot.bottom} stroke="var(--viz-grid)" />

      {geo.yTicks.map((t) => (
        <g key={t.value}>
          <line
            x1={plot.left}
            y1={t.py}
            x2={plot.right}
            y2={t.py}
            stroke="var(--viz-grid)"
            opacity="0.5"
          />
          <text
            x={plot.left - 4}
            y={t.py + 3}
            fill="var(--tg-text-2)"
            fontSize={FS}
            textAnchor="end"
          >
            {tickLabel(t.value)}
          </text>
        </g>
      ))}

      <text
        x={geo.x(0)}
        y={plot.bottom + 14}
        fill="var(--tg-text-2)"
        fontSize={FS}
        textAnchor="middle"
      >
        0
      </text>
      <text
        x={plot.right}
        y={plot.bottom + 14}
        fill="var(--tg-text-2)"
        fontSize={FS}
        textAnchor="end"
      >
        FPR {fmtFpr(xMax)}
      </text>

      {windowFrac != null && (
        <rect
          x={plot.left}
          y={plot.top}
          width={Math.max(2, (plot.right - plot.left) * windowFrac)}
          height={plot.bottom - plot.top}
          fill="var(--viz-threshold)"
          opacity="0.08"
        />
      )}

      {ribbonD && <path d={ribbonD} fill="var(--viz-ribbon)" stroke="none" data-ribbon="true" />}

      <path d={geo.linePath} fill="none" stroke="var(--viz-series)" strokeWidth="1.5" />

      {placed.map((m) => (
        <g key={m.id}>
          <line
            x1={m.cx}
            y1={m.cy}
            x2={m.anchor === "end" ? m.callout.x + 3 : m.callout.x - 3}
            y2={m.box.y + m.box.h / 2}
            stroke="var(--viz-threshold)"
            strokeWidth="1"
          />
          <circle cx={m.cx} cy={m.cy} r="4" fill="var(--viz-threshold)" data-marker={m.id} />
          {m.lines.map((line, i) => (
            <text
              key={i}
              x={m.callout.x}
              y={m.box.y + (i + 1) * (FS + 1)}
              fill="var(--tg-text)"
              fontSize={FS}
              textAnchor={m.anchor}
              data-callout={m.id}
            >
              {line}
            </text>
          ))}
        </g>
      ))}
    </svg>
  );
}

export default function CostCurve({ block4 }) {
  const b = block4;
  const dmax = b.decisionRegionFprMax;

  // ---- Panel A: decision region, π₀ -----------------------------------
  const regionCurve = b.curvePi0.filter((p) => p[0] <= dmax + 1e-12);
  const env = ribbonEnvelope(b.ribbonEnvelope);
  const regionEnv = env.filter((e) => e[0] <= dmax + 1e-12);
  const aDomain = costDomain([
    ...regionCurve.map((p) => p[2]),
    ...regionEnv.flatMap((e) => [e[1], e[2]]),
  ]);
  const geoA = buildPanelGeometry(b.curvePi0, [0, dmax], aDomain, {
    width: W,
    height: H,
    margin: M,
    xInset: 8,
  });
  const ribbonAD = ribbonPath(regionEnv, geoA.x, geoA.y);

  const optLines = [
    b.optimaCoincident ? "cost-optimal = F1-optimal" : "cost-optimal",
    `FPR ${fmtFpr(b.costOptimal.fpr)} · TPR ${fmtRate(b.costOptimal.tpr)}`,
    fmtInr(b.costOptimal.costPi0),
  ];
  const markersA = [
    {
      id: "cost-optimal",
      cx: geoA.x(b.costOptimal.fpr),
      cy: geoA.y(b.costOptimal.costPi0),
      lines: optLines,
    },
  ];
  if (!b.optimaCoincident) {
    markersA.push({
      id: "f1-optimal",
      cx: geoA.x(b.f1Optimal.fpr),
      cy: geoA.y(b.f1Optimal.costPi0),
      lines: [
        "F1-optimal",
        `FPR ${fmtFpr(b.f1Optimal.fpr)} · TPR ${fmtRate(b.f1Optimal.tpr)}`,
        fmtInr(b.f1Optimal.costPi0),
      ],
    });
  }

  // ---- Panel B: full range, π₀ (context) ----------------------------
  const bDomain = costDomain([
    ...b.curvePi0.map((p) => p[2]),
    ...env.flatMap((e) => [e[1], e[2]]),
  ]);
  const geoB = buildPanelGeometry(b.curvePi0, [0, 1], bDomain, {
    width: W,
    height: H,
    margin: M,
    xInset: 8,
  });
  const ribbonBD = ribbonPath(env, geoB.x, geoB.y);

  // ---- Panel C: full range, π₁ (own scale, NO ribbon) --------------
  const cDomain = costDomain(b.curvePi1.map((p) => p[2]));
  const geoC = buildPanelGeometry(b.curvePi1, [0, 1], cDomain, {
    width: W,
    height: H,
    margin: M,
    xInset: 8,
  });
  const stayPt =
    b.curvePi1.find((p) => p[0] === b.costOptimal.fpr && p[1] === b.costOptimal.tpr) || b.curvePi1[1];
  const markersC = [
    {
      id: "stay",
      cx: geoC.x(stayPt[0]),
      cy: geoC.y(stayPt[2]),
      lines: ["stay at π₀ optimum", fmtInr(stayPt[2])],
    },
    {
      id: "pi1-optimal",
      cx: geoC.x(b.costOptimalPi1.fpr),
      cy: geoC.y(b.costOptimalPi1.costPi1),
      lines: [
        "π₁ cost-optimal",
        `FPR ${fmtFpr(b.costOptimalPi1.fpr)} · TPR ${fmtRate(b.costOptimalPi1.tpr)}`,
        fmtInr(b.costOptimalPi1.costPi1),
      ],
    },
  ];

  return (
    <div>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 4px" }}>
        series {b.series} · tier {b.tier} · split {b.split}
      </p>
      <p className="tg-body" style={{ margin: "0 0 6px" }}>
        Regime-switch saving: <strong>{fmtInr(b.regimeSwitchSavingMinor)}</strong> per 10,000
        attempts, at under-attack prevalence π₁ = {fmtPi(b.pi1)}.
      </p>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 12px" }}>
        F1-vs-cost gap at π₀ = {fmtPi(b.pi0)} is <strong>{fmtInr(b.rupeeGapMinor)}</strong> —{" "}
        {b.rupeeGapIsStructural ? "structural, not empirical" : "an empirical difference"}.
        {b.rupeeGapNote ? ` ${b.rupeeGapNote}` : ""}
      </p>

      <div style={{ display: "grid", gap: 16 }}>
        <figure style={{ margin: 0 }}>
          <figcaption className="tg-label" style={{ color: "var(--tg-text-2)", marginBottom: 2 }}>
            A · decision region — π₀ = {fmtPi(b.pi0)} · FPR ≤ {fmtFpr(dmax)}
          </figcaption>
          <Panel
            id="cc-a"
            title={`Expected cost vs FPR in the decision region at prevalence ${fmtPi(
              b.pi0,
            )}, log cost axis.`}
            desc={`The cost-optimal operating point is at FPR ${fmtFpr(b.costOptimal.fpr)}, TPR ${fmtRate(
              b.costOptimal.tpr,
            )}, ${fmtInr(
              b.costOptimal.costPi0,
            )} per 10,000 attempts. The shaded band is the prevalence-sensitivity ribbon across π in ${b.ribbonPis.join(
              ", ",
            )}. Exact values in the operating-point table below.`}
            geo={geoA}
            ribbonD={ribbonAD}
            markers={markersA}
            xMax={dmax}
          />
        </figure>

        <figure style={{ margin: 0 }}>
          <figcaption className="tg-label" style={{ color: "var(--tg-text-2)", marginBottom: 2 }}>
            B · full range — π₀ = {fmtPi(b.pi0)} (context; the shaded sliver is Panel A)
          </figcaption>
          <Panel
            id="cc-b"
            title={`Expected cost across the full FPR range at prevalence ${fmtPi(
              b.pi0,
            )}, log cost axis.`}
            desc={`Context for Panel A: the decision region FPR ≤ ${fmtFpr(
              dmax,
            )} is the shaded sliver at the left. The prevalence-sensitivity ribbon spans π in ${b.ribbonPis.join(
              ", ",
            )}.`}
            geo={geoB}
            ribbonD={ribbonBD}
            markers={[]}
            xMax={1}
            windowFrac={dmax}
          />
        </figure>

        <figure style={{ margin: 0 }}>
          <figcaption className="tg-label" style={{ color: "var(--tg-text-2)", marginBottom: 2 }}>
            C · full range — π₁ = {fmtPi(b.pi1)} (under attack; own scale, no ribbon)
          </figcaption>
          <Panel
            id="cc-c"
            title={`Expected cost across the full FPR range at under-attack prevalence ${fmtPi(
              b.pi1,
            )}, log cost axis.`}
            desc={`Under attack the optimum moves to FPR ${fmtFpr(b.costOptimalPi1.fpr)}, TPR ${fmtRate(
              b.costOptimalPi1.tpr,
            )}. Staying at the π₀ optimum instead would cost ${fmtInr(
              stayPt[2],
            )}; moving saves ${fmtInr(
              b.regimeSwitchSavingMinor,
            )} per 10,000 attempts. No ribbon: π₁ = ${fmtPi(
              b.pi1,
            )} is outside the ribbon's prevalence range.`}
            geo={geoC}
            ribbonD={null}
            markers={markersC}
            xMax={1}
          />
        </figure>
      </div>

      <OperatingPointTable block4={b} />
    </div>
  );
}
