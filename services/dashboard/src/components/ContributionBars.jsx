import { featureLabel } from "../lib/featureLabels.js";

// Day 8, Step 7 -- contribution bars (UIUX v2 SS6.7). Top 3 from
// `attempt_score.top_contributors`. --tg-text-2 fill on --tg-surface-2 track;
// GREY, never indigo -- these are measurements, not actions. Operator-facing
// names from lib/featureLabels.js.

export default function ContributionBars({ contributions = [] }) {
  const top = [...contributions]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 3);
  const max = Math.max(...top.map((c) => Math.abs(c.contribution)), 1e-9);

  if (top.length === 0) {
    return <p className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>No model contributions (rules-only decision).</p>;
  }

  return (
    <div>
      {top.map((c) => (
        <div
          key={c.feature}
          style={{ display: "grid", gridTemplateColumns: "1fr 120px 72px", alignItems: "center", gap: 12, padding: "3px 0" }}
        >
          <span className="tg-body" style={{ color: "var(--tg-text-2)" }}>{featureLabel(c.feature)}</span>
          <div style={{ height: 12, background: "var(--tg-surface-2)", borderRadius: 2 }}>
            <div
              style={{
                width: `${(Math.abs(c.contribution) / max) * 100}%`,
                height: 12,
                borderRadius: 2,
                background: "var(--tg-text-2)",
              }}
            />
          </div>
          <span className="tg-mono-data tg-num" style={{ textAlign: "right" }}>
            {c.contribution.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}
