// Day 8, Step 5 -- the cost curves (UIUX v2 SS6.13). Two polylines, SAME
// colour, solid = steady state (pi0), dashed = under attack (pi1), each
// labelled inline at its right terminus. `--viz-ribbon` fill for the
// prevalence sensitivity band across pi in [1e-4, 1e-2]. Two
// `--viz-threshold` markers -- `F1-optimal` and `cost-optimal` -- with the
// rupee gap set between them in `mono-metric`. Both regimes' pi values are
// printed on the AXIS LABEL, never hunted for in a caption.
//
// Inline SVG, no charting library.

const W = 520;
const H = 260;
const M = { top: 16, right: 96, bottom: 40, left: 64 };

function rupees(minor) {
  return `₹${Math.round(minor / 100).toLocaleString()}`;
}

export default function CostCurve({ b4 }) {
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;

  const all = [
    ...b4.curve_pi0,
    ...b4.curve_pi1,
    ...b4.ribbon.flatMap((r) => r.curve),
  ];
  const maxCost = Math.max(...all.map((p) => p[2]), 1);
  const x = (fpr) => M.left + fpr * iw;
  const y = (cost) => M.top + ih - (cost / maxCost) * ih;

  const path = (curve) => curve.map((p, i) => `${i === 0 ? "M" : "L"}${x(p[0])},${y(p[2])}`).join(" ");

  const lo = b4.ribbon[0].curve; // pi = 1e-4
  const hi = b4.ribbon[b4.ribbon.length - 1].curve; // pi = 1e-2
  const ribbonPath =
    lo.map((p, i) => `${i === 0 ? "M" : "L"}${x(p[0])},${y(p[2])}`).join(" ") +
    " " +
    [...hi].reverse().map((p) => `L${x(p[0])},${y(p[2])}`).join(" ") +
    " Z";

  const f1x = x(b4.f1_optimal.fpr);
  const cox = x(b4.cost_optimal.fpr);
  const coincident = Math.abs(f1x - cox) < 1;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="expected cost per 10,000 attempts vs FPR">
        {/* axes */}
        <line x1={M.left} y1={M.top} x2={M.left} y2={M.top + ih} stroke="var(--viz-grid)" />
        <line x1={M.left} y1={M.top + ih} x2={M.left + iw} y2={M.top + ih} stroke="var(--viz-grid)" />

        {/* prevalence sensitivity ribbon */}
        <path d={ribbonPath} fill="var(--viz-ribbon)" stroke="none" />

        {/* pi0 solid, pi1 dashed, SAME colour */}
        <path d={path(b4.curve_pi0)} fill="none" stroke="var(--viz-series)" strokeWidth="1.5" />
        <path
          d={path(b4.curve_pi1)}
          fill="none"
          stroke="var(--viz-series-alt)"
          strokeWidth="1.5"
          strokeDasharray="5 4"
        />

        {/* right-terminus inline labels */}
        <text x={M.left + iw + 6} y={y(b4.curve_pi0[b4.curve_pi0.length - 1][2])} fill="var(--tg-text-2)" fontSize="10">
          π₀ solid
        </text>
        <text x={M.left + iw + 6} y={y(b4.curve_pi1[b4.curve_pi1.length - 1][2])} fill="var(--tg-text-2)" fontSize="10">
          π₁ dashed
        </text>

        {/* the two operating-point markers */}
        <line x1={cox} y1={M.top} x2={cox} y2={M.top + ih} stroke="var(--viz-threshold)" strokeWidth="1" />
        {!coincident && (
          <line x1={f1x} y1={M.top} x2={f1x} y2={M.top + ih} stroke="var(--viz-threshold)" strokeWidth="1" strokeDasharray="2 2" />
        )}
        <text x={cox + 3} y={M.top + 10} fill="var(--viz-threshold)" fontSize="9" fontFamily="monospace">
          cost-optimal
        </text>
        <text x={(coincident ? cox : f1x) + 3} y={M.top + 22} fill="var(--viz-threshold)" fontSize="9" fontFamily="monospace">
          F1-optimal
        </text>

        {/* y-axis label carries BOTH pi values */}
        <text x={12} y={M.top + ih / 2} fill="var(--tg-text-mute)" fontSize="9" transform={`rotate(-90 12 ${M.top + ih / 2})`}>
          ₹ / 10,000 attempts · π₀=0.001 (solid) · π₁=0.9 (dashed)
        </text>
        <text x={M.left + iw / 2} y={H - 8} fill="var(--tg-text-mute)" fontSize="9" textAnchor="middle">
          false-positive rate (hull)
        </text>
      </svg>

      <div style={{ display: "flex", gap: 24, alignItems: "baseline", marginTop: 4 }}>
        <div>
          <div className="tg-mono-metric tg-num" style={{ color: "var(--tg-text)" }}>
            {rupees(b4.rupee_gap_minor)}
          </div>
          <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
            rupee gap: cost(F1-optimal) − cost(cost-optimal), at steady-state prevalence (π₀)
          </div>
        </div>
        <div>
          <div className="tg-mono-metric tg-num" style={{ color: "var(--tg-text)" }}>
            {rupees(b4.regime_switch_saving_minor)}
          </div>
          <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
            regime-switch saving per 10,000 attempts, at under-attack prevalence (π₁)
          </div>
        </div>
      </div>
      {coincident && (
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", marginTop: 4 }}>
          At π₀ the F1-optimal and cost-optimal operating points coincide for this series, so the
          rupee gap is ₹0 — the headline is the regime-switch saving.
        </p>
      )}
    </div>
  );
}
