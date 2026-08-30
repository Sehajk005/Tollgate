// Day 8, Step 7 -- the detection timeline (UIUX v2 SS6.6). One node per
// tier_transition, `mono-data` timestamps in a fixed-width left gutter.
//
//   * the detector is named at the ALERT node (incident.detector ->
//     "CUSUM alert" / "distinct-card drift");
//   * the `challenge` node is annotated `auto — ceiling reached`;
//   * PROPOSED nodes (step_up / block, not yet confirmed) use the dotted glyph
//     `◌`, a DASHED connector and 0.6 opacity; on confirmation the glyph fills
//     (`●`), the connector solidifies and opacity -> 1 over 400ms -- one of the
//     two motions given real duration (UIUX v2 SS7).

const DETECTOR_LABEL = {
  cusum: "CUSUM alert",
  drift: "distinct-card drift",
  both: "CUSUM + distinct-card drift",
};

const PROPOSED = new Set(["step_up", "block"]);

function fmt(ms) {
  return ms == null ? "--:--:--" : new Date(ms).toISOString().slice(11, 19);
}

export default function DetectionTimeline({ timeline = [], detector, confirmedTiers = [] }) {
  const confirmed = new Set(confirmedTiers);
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {timeline.map((t, i) => {
        const tier = t.to_tier;
        const isAlert = i === 0 || String(t.trigger || "").startsWith("open:");
        const isProposed = PROPOSED.has(tier) && !confirmed.has(tier);
        return (
          <li
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "84px 20px 1fr",
              alignItems: "start",
              gap: 8,
              padding: "4px 0",
              opacity: isProposed ? 0.6 : 1,
              transition: "opacity 400ms ease",
              borderLeft: i === timeline.length - 1
                ? "none"
                : isProposed
                  ? "1px dashed var(--tg-proposed)"
                  : "1px solid var(--tg-hairline-firm)",
              marginLeft: 42,
              paddingLeft: 12,
            }}
          >
            <span className="tg-mono-data tg-num" style={{ color: "var(--tg-text-mute)", marginLeft: -54 }}>
              {fmt(t.at)}
            </span>
            <span aria-hidden="true" style={{ color: "var(--tg-text-2)" }}>
              {isProposed ? "◌" : "●"}
            </span>
            <span className="tg-body">
              <strong className="tg-body-strong">{String(tier || "").toUpperCase()}</strong>
              {isProposed && <span className="tg-caption" style={{ color: "var(--tg-text-mute)" }}> proposed — awaiting confirmation</span>}
              {tier === "challenge" && <span className="tg-caption" style={{ color: "var(--tg-text-mute)" }}> auto — ceiling reached</span>}
              {isAlert && (
                <span className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
                  {" — "}{DETECTOR_LABEL[detector] || detector || "alert"}
                  {t.signal_value != null ? ` (${Number(t.signal_value).toFixed(2)})` : ""}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
