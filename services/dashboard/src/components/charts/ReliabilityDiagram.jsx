// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §15 FIX-M-010 (5c).
//
// The canonical calibration picture, named first by the spec and currently
// discarded. A scatter of (mean_predicted, observed_rate) per non-empty bin
// against the y = x identity line, with point AREA proportional to bin weight
// -- essential here, because at π₀ bin 0 carries weight ~2124 of 2125 and the
// other bins carry ~1 in total; without weight encoding the near-empty bins
// would dominate and misrepresent the calibration.
//
// Empty bins (mean_predicted: null, weight 0) are NOT plotted at the origin --
// they are omitted and their count is stated in text.

const S = 180;
const PAD = 24;
const FS = 11;
const R_MIN = 2.5;
const R_MAX = 11;

export default function ReliabilityDiagram({ points, emptyCount, label, id }) {
  const inner = S - 2 * PAD;
  const x = (v) => PAD + v * inner;
  const y = (v) => PAD + (1 - v) * inner;
  const wMax = Math.max(1, ...points.map((p) => p.weight));
  const r = (w) => R_MIN + (R_MAX - R_MIN) * Math.sqrt(Math.max(0, w) / wMax);

  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="tg-label" style={{ color: "var(--tg-text-2)", marginBottom: 2 }}>
        {label}
      </figcaption>
      <svg
        viewBox={`0 0 ${S} ${S}`}
        width="100%"
        role="img"
        aria-labelledby={`${id}-t ${id}-d`}
        style={{ display: "block", maxWidth: 260 }}
      >
        <title id={`${id}-t`}>Reliability diagram: {label}</title>
        <desc id={`${id}-d`}>
          Observed rate vs mean predicted probability for {points.length} non-empty bins; point
          area is proportional to bin weight. {emptyCount} empty bins are omitted. Perfect
          calibration lies on the diagonal.
        </desc>

        <rect x={PAD} y={PAD} width={inner} height={inner} fill="none" stroke="var(--viz-grid)" />
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--viz-grid)"
          strokeDasharray="3 3"
        />

        {points.map((p, i) => (
          <circle
            key={i}
            cx={x(p.meanPredicted)}
            cy={y(p.observedRate)}
            r={r(p.weight)}
            fill="var(--viz-series)"
            fillOpacity="0.65"
            stroke="var(--viz-series)"
            data-weight={p.weight}
          />
        ))}

        <text x={S / 2} y={S - 4} fill="var(--tg-text-2)" fontSize={FS} textAnchor="middle">
          mean predicted
        </text>
        <text x={10} y={PAD - 8} fill="var(--tg-text-2)" fontSize={FS}>
          observed rate
        </text>
      </svg>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "2px 0 0" }}>
        {points.length} non-empty bins · {emptyCount} empty bins omitted
      </p>
    </figure>
  );
}
