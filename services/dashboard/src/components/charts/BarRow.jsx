// Day 8, Step 5 -- a single horizontal bar. Inline markup, no charting
// library (UIUX v2 SS6.13: three chart shapes do not justify a dependency).
// `--viz-series` grey by default -- the story every chart tells is departure
// from baseline, not absolute value (UIUX v2 SS2.4).
//
// Remediation plan FIX-019 (AUDIT-011) -- FOUR STATES, RENDERED DISTINCTLY.
// This component used to print `value.toFixed(3)` unconditionally. Every
// `recall_at_target_fpr` entry in eval/outputs/d6.json carries
// `resolvable: false` (n_neg = 221 or 316, against the 1000 negatives a
// 1e-3 FPR target needs to resolve at all), so D6 showed the flagship model
// at `0.000` on the EASIEST tier with no caveat -- a fabricated number where
// the artifact was explicitly honest about not knowing. `resolvable` appeared
// nowhere in the dashboard.
//
// The distinctions the eval harness is careful to preserve are now preserved
// end to end:
//
//   measured      -> the bar and the value, plus its Wilson CI
//   unresolvable  -> NO BAR, and the text `n/a · n_neg=221`
//   unavailable   -> `n/a`
//   missing       -> an em dash
//
// A `metric` object takes precedence over the legacy `value` prop, so the
// call sites that pass a plain number are untouched.

function fmtCi(metric) {
  if (metric.ci_low == null || metric.ci_high == null) return null;
  return `[${metric.ci_low.toFixed(3)}, ${metric.ci_high.toFixed(3)}]`;
}

export function metricText(metric) {
  if (metric == null) return "—";
  if (metric.resolvable === false) {
    return metric.n_neg == null ? "n/a" : `n/a · n_neg=${metric.n_neg}`;
  }
  if (metric.value == null) return "n/a";
  return metric.value.toFixed(3);
}

export default function BarRow({
  label,
  value,
  metric = null,
  max = 1,
  valueText,
  color = "var(--viz-series)",
  note,
}) {
  // An unresolvable metric must not draw a bar: a bar IS a claim about
  // magnitude, and there is no magnitude to claim.
  const unresolvable = metric != null && metric.resolvable === false;
  const effectiveValue = metric != null ? metric.value : value;
  const frac =
    unresolvable || max <= 0 || effectiveValue == null
      ? 0
      : Math.max(0, Math.min(1, effectiveValue / max));

  const text =
    valueText != null
      ? valueText
      : metric != null
      ? metricText(metric)
      : value == null
      ? "n/a"
      : value.toFixed(3);

  const ci = metric != null && !unresolvable ? fmtCi(metric) : null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "200px 1fr 168px",
        alignItems: "center",
        gap: 12,
        padding: "3px 0",
      }}
    >
      <span className="tg-body" style={{ color: "var(--tg-text-2)" }}>{label}</span>
      <div style={{ position: "relative", height: 14, background: "var(--tg-surface-2)", borderRadius: 2 }}>
        {!unresolvable && (
          <div style={{ width: `${frac * 100}%`, height: 14, background: color, borderRadius: 2 }} />
        )}
        {unresolvable && (
          <span
            className="tg-label"
            style={{ position: "absolute", left: 8, top: -1, color: "var(--tg-text-mute)" }}
          >
            not resolvable at these negative counts
          </span>
        )}
        {note && (
          <span
            className="tg-label"
            style={{ position: "absolute", left: 8, top: -1, color: "var(--tg-canvas)" }}
          >
            {note}
          </span>
        )}
      </div>
      <span
        className="tg-mono-data tg-num"
        style={{ textAlign: "right", color: unresolvable ? "var(--tg-text-mute)" : "var(--tg-text)" }}
      >
        {text}
        {ci && (
          <span style={{ color: "var(--tg-text-mute)" }}> {ci}</span>
        )}
      </span>
    </div>
  );
}
