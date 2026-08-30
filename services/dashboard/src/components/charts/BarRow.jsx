// Day 8, Step 5 -- a single horizontal bar. Inline markup, no charting
// library (UIUX v2 SS6.13: three chart shapes do not justify a dependency).
// `--viz-series` grey by default -- the story every chart tells is departure
// from baseline, not absolute value (UIUX v2 SS2.4).

export default function BarRow({ label, value, max = 1, valueText, color = "var(--viz-series)", note }) {
  const frac = max > 0 && value != null ? Math.max(0, Math.min(1, value / max)) : 0;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "200px 1fr 96px",
        alignItems: "center",
        gap: 12,
        padding: "3px 0",
      }}
    >
      <span className="tg-body" style={{ color: "var(--tg-text-2)" }}>{label}</span>
      <div style={{ position: "relative", height: 14, background: "var(--tg-surface-2)", borderRadius: 2 }}>
        <div style={{ width: `${frac * 100}%`, height: 14, background: color, borderRadius: 2 }} />
        {note && (
          <span
            className="tg-label"
            style={{ position: "absolute", left: 8, top: -1, color: "var(--tg-canvas)" }}
          >
            {note}
          </span>
        )}
      </div>
      <span className="tg-mono-data tg-num" style={{ textAlign: "right", color: "var(--tg-text)" }}>
        {valueText != null ? valueText : value == null ? "n/a" : value.toFixed(3)}
      </span>
    </div>
  );
}
