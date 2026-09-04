// Day 8, Step 7 -- the incident narrative block (UIUX v2 SS6.5). `body-lg` at
// 16px, the largest reading type in the product. --tg-surface-2, a 3px left
// border in the incident's state colour, 24px padding, max-width 68 chars.
//
// Threat Model SS5 requirements, all structural here:
//   * a provenance line above, in `label` / --tg-text-mute:
//     GENERATED SUMMARY · EVIDENCE BELOW IS AUTHORITATIVE
//   * PLAIN TEXT ONLY -- the narrative is rendered as a React text node, never
//     as raw markup. No markdown, no links, no HTML.
//   * a HARD 600-character truncation (not an ellipsis-expand).
//   * the component takes only `narrative` + `stateColor` -- it is never told
//     which backend produced the text, which is how "template and LLM render
//     identically, no layout shift" is made structurally true rather than
//     merely tested (pinned by test_ui_narrative_parity.py).

const MAX_NARRATIVE_CHARS = 600;

export default function NarrativeBlock({ narrative, stateColor = "var(--tg-calm)" }) {
  const text = String(narrative || "").slice(0, MAX_NARRATIVE_CHARS);
  return (
    <div style={{ marginBottom: 20 }}>
      <div className="tg-label" style={{ color: "var(--tg-text-mute)", marginBottom: 6 }}>
        GENERATED SUMMARY · EVIDENCE BELOW IS AUTHORITATIVE
      </div>
      <div
        className="tg-body-lg"
        style={{
          background: "var(--tg-surface-2)",
          borderLeft: `3px solid ${stateColor}`,
          padding: 24,
          maxWidth: "68ch",
          whiteSpace: "pre-wrap",
          color: "var(--tg-text-2)",
        }}
      >
        {text || "No narrative yet."}
      </div>
    </div>
  );
}
