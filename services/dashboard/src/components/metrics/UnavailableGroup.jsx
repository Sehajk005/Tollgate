// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §11 FIX-M-015/028, §13
// FIX-M-006, §20.5 -- ONE visual language for every null state, learned once.
//
// Three null semantics, all NON-numeric, all NON-bar-shaped:
//
//   unresolvable  -- measured, cannot be resolved      (recall@1e-3, n_neg=221)
//   unreachable   -- undefined for this scorer         (always_positive sanity)
//   unavailable   -- not computed in this run          (model row, no --model-dir)
//
// The block's shared reason renders ONCE above N rows (never the 8x / 6x
// caps-lock repetition the audit measured). Each row keeps its own denominator
// (`n_neg=221`) -- the brief is explicit that it must not be hidden. No filled
// track element is emitted: a rule is not a magnitude and cannot be misread as
// a 100% bar.

const RULE = {
  height: 0,
  borderTop: "1px dashed var(--tg-hairline-firm)",
};

function detailSuffix(detail) {
  if (!detail) return "";
  if (detail.n_neg != null) return ` · n_neg=${detail.n_neg}`;
  return "";
}

/**
 * @param {string} reason  the single shared explanation, rendered once
 * @param {Array<{key?, label, text?, detail?, ariaLabel?}>} rows
 * @param {string} [testid]
 */
export default function UnavailableGroup({ reason, rows = [], testid }) {
  return (
    <div data-testid={testid}>
      {reason && (
        <p
          className="tg-caption"
          style={{ color: "var(--tg-text-mute)", margin: "4px 0 8px" }}
        >
          {reason}
        </p>
      )}
      {rows.map((r, i) => {
        const suffix = detailSuffix(r.detail);
        const shown = r.text != null ? r.text : `not resolvable${suffix}`;
        const aria = r.ariaLabel != null ? r.ariaLabel : `${r.label}: ${shown}`;
        return (
          <div
            key={r.key || r.label || i}
            className="tg-metric-row"
            role="group"
            aria-label={aria}
            style={{
              display: "grid",
              gridTemplateColumns:
                "minmax(9rem, 14rem) minmax(6rem, 1fr) minmax(7rem, max-content)",
              alignItems: "center",
              gap: 12,
              padding: "3px 0",
            }}
          >
            <span className="tg-body" style={{ color: "var(--tg-text-2)" }}>
              {r.label}
            </span>
            {/* a dashed baseline rule -- deliberately NOT a filled track */}
            <div aria-hidden="true" style={RULE} />
            <span
              className="tg-mono-data tg-num"
              style={{ textAlign: "right", color: "var(--tg-text-mute)" }}
            >
              {shown}
            </span>
          </div>
        );
      })}
    </div>
  );
}
