// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §12 FIX-M-007-FE / M-017 / M-024.
//
// The section titled "Negative-control false positives" now actually contains
// the PRODUCT's false positives: each scenario carries `l1-lgbm-v1` and
// `rules-only-v0` rows (at θ_challenge) BEFORE the four sanity scorers, which
// are retained as the harness floor.
//
//   * episode flagged is a BOOLEAN (structurally -- one run, one episode per
//     scenario, §1(B)/M-017): `yes` / `no`, never `0/1`
//   * attempt FP is a rate over LEGITIMATE attempts only (denominator basis in
//     the header). n >= 30 -> a Wilson interval; n < 30 -> a power badge and a
//     bare count (`0 of 1`), because a percentage of one sample is noise
//   * semantic table: <caption>, <th scope="col">, real <th scope="row"
//     rowSpan={6}> for the scenario -- no empty <td> used as a visual rowspan

import { count as fmtCount, pct as fmtPct } from "../../lib/format.js";
import ScrollableTableRegion from "./ScrollableTableRegion.jsx";

const SANITY = new Set(["perfect", "random", "inverted", "always_positive"]);
const Z = 1.959963984540054; // 95%

function wilson(k, n) {
  if (!(n > 0) || k < 0 || k > n) return null;
  const p = k / n;
  const z2 = Z * Z;
  const denom = 1 + z2 / n;
  const centre = (p + z2 / (2 * n)) / denom;
  const half = (Z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

function AttemptFpCell({ row }) {
  if (!row.available) {
    return (
      <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--tg-text-mute)" }}>
        {row.reason || "not computed"}
      </td>
    );
  }
  const { attemptFp, attempts } = row;
  if (attempts != null && attempts < 30) {
    const badge = attempts === 1 ? "single sample — n=1" : `underpowered — n=${attempts}`;
    return (
      <td style={{ padding: "4px 8px", textAlign: "right" }}>
        {attemptFp} of {attempts}
        <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
          {badge}
        </div>
      </td>
    );
  }
  const ci = wilson(attemptFp, attempts);
  return (
    <td style={{ padding: "4px 8px", textAlign: "right" }}>
      {attemptFp} FP · {fmtPct(attemptFp / attempts)}
      <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
        n = {fmtCount(attempts)}
        {ci ? ` · 95% CI [${fmtPct(ci[0])}, ${fmtPct(ci[1])}]` : ""}
      </div>
    </td>
  );
}

export default function Block2NegativeControls({ block2 }) {
  const theta = block2.thetaChallenge;

  return (
    <div>
      <ScrollableTableRegion label="Negative-control false positives, scrollable table">
      <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
        <caption
          className="tg-caption"
          style={{ textAlign: "left", color: "var(--tg-text-mute)", marginBottom: 6 }}
        >
          Negative-control false positives on <strong>legitimate attempts only</strong>, scored at
          θ_challenge = {theta == null ? "n/a" : theta.toFixed(6)}. Rows 1–2 are the product
          (<code>l1-lgbm-v1</code>, <code>rules-only-v0</code>); rows 3–6 are the harness sanity
          floor. Episode-flagged is a boolean: one run, one episode per scenario.
        </caption>
        <thead>
          <tr className="tg-label">
            <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>scenario</th>
            <th scope="col" style={{ textAlign: "left", padding: "4px 8px" }}>scorer</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>episode flagged</th>
            <th scope="col" style={{ textAlign: "right", padding: "4px 8px" }}>
              attempt FP (legitimate attempts)
            </th>
          </tr>
        </thead>
        {block2.scenarios.map((s) => (
          <tbody key={s.name}>
            {s.rows.map((r, i) => (
              <tr
                key={r.scorer}
                style={{
                  borderTop:
                    i === 0
                      ? "2px solid var(--tg-hairline-firm)"
                      : "1px solid var(--tg-hairline)",
                }}
              >
                {i === 0 && (
                  <th
                    scope="row"
                    rowSpan={s.rows.length}
                    style={{
                      textAlign: "left",
                      padding: "4px 8px",
                      color: "var(--tg-text-2)",
                      verticalAlign: "top",
                    }}
                  >
                    {s.name}
                    {s.name === "shared_ip_legit" && (
                      <div className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
                        F14 case — evaluated on one legitimate attempt (60 of 61 samples are the
                        attacker's).
                      </div>
                    )}
                  </th>
                )}
                <td
                  style={{
                    padding: "4px 8px",
                    color: SANITY.has(r.scorer) ? "var(--tg-text-mute)" : "var(--tg-text)",
                  }}
                >
                  {r.scorer}
                </td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>
                  {r.available ? (r.episodeFlagged ? "yes" : "no") : "—"}
                </td>
                <AttemptFpCell row={r} />
              </tr>
            ))}
          </tbody>
        ))}
      </table>
      </ScrollableTableRegion>
    </div>
  );
}
