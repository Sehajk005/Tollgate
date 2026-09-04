// Day 8, Step 5 -- the discriminability audit (UIUX v2 SS6.13). Horizontal
// bars of univariate AUC per feature, sorted DESCENDING, with a
// `--viz-threshold` rule at 0.95. Any bar crossing it renders in `--viz-flag`
// amber with a `FLAGGED — GENERATOR ARTIFACT` annotation.
//
// This is the ONLY place in the product where amber is not threat state, and
// it is justified: the flag means "this measurement is suspect".

const THRESHOLD = 0.95;

export default function AuditBars({ features }) {
  const rows = Object.entries(features || {})
    .map(([name, v]) => ({
      name,
      auc: v.univariate_auc,
      flagged: (v.univariate_auc != null && v.univariate_auc >= THRESHOLD) || !!v.excluded,
    }))
    .sort((a, b) => (b.auc ?? 0) - (a.auc ?? 0));

  return (
    <div>
      {rows.map((r) => {
        const frac = Math.max(0, Math.min(1, r.auc ?? 0));
        return (
          <div
            key={r.name}
            style={{
              display: "grid",
              gridTemplateColumns: "200px 1fr 64px",
              alignItems: "center",
              gap: 12,
              padding: "2px 0",
            }}
          >
            <span className="tg-mono-caption" style={{ color: "var(--tg-text-2)" }}>{r.name}</span>
            <div style={{ position: "relative", height: 12, background: "var(--tg-surface-2)", borderRadius: 2 }}>
              {/* the 0.95 operating-threshold rule, on every track so it reads as a column */}
              <div
                aria-hidden="true"
                style={{ position: "absolute", left: `${THRESHOLD * 100}%`, top: -2, bottom: -2, width: 1, background: "var(--viz-threshold)" }}
              />
              <div
                style={{
                  width: `${frac * 100}%`,
                  height: 12,
                  borderRadius: 2,
                  background: r.flagged ? "var(--viz-flag)" : "var(--viz-series)",
                }}
              />
              {r.flagged && (
                <span
                  className="tg-label"
                  style={{ position: "absolute", right: 0, top: -15, color: "var(--viz-flag)" }}
                >
                  FLAGGED — GENERATOR ARTIFACT
                </span>
              )}
            </div>
            <span className="tg-mono-data tg-num" style={{ textAlign: "right" }}>
              {r.auc == null ? "n/a" : r.auc.toFixed(3)}
            </span>
          </div>
        );
      })}
      <div className="tg-caption" style={{ marginTop: 8, color: "var(--tg-text-mute)" }}>
        Operating threshold {THRESHOLD.toFixed(2)} (Eval Protocol SS4/V2). A feature over it is
        excluded from the model and stays active only in the R1/R3 rule floors.
      </div>
    </div>
  );
}
