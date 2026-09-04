// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §22.2 (M-027 / M-024).
//
// A wide table on a narrow viewport must scroll inside ITSELF, not push the
// document sideways. The accessible pattern (WAI-ARIA APG "scrolling table"):
// wrap it in `role="region"` + `tabindex="0"` + an accessible name, so a
// keyboard user can scroll it and a screen reader announces it as a landmark.
// The scroll itself is `overflow-x: auto` from `.tg-scroll-x` (styles/metrics.css);
// jsdom does not lay out, so the actual no-overflow proof is Playwright (§22.3).

export default function ScrollableTableRegion({ label, children }) {
  return (
    <div className="tg-scroll-x" role="region" tabIndex={0} aria-label={label}>
      {children}
    </div>
  );
}
