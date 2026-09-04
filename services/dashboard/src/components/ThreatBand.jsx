import { THREAT_LABELS, THREAT_GLYPHS, THREAT_TOKENS, THREAT_WASH_TOKENS } from "../lib/labels.js";

// Day 8, Step 3 -- D1 threat band (UIUX v2 SS6.1). Full width, top of every
// screen (it is the "global threat indicator" of D0's shell, App Flow SS5).
//
// Renders `event.threat_state` VERBATIM -- never derived locally. Colour is
// never load-bearing: the uppercase text label and a distinct ring glyph
// (hollow / half / filled / check) both carry the state (UIUX v2 SS2.5).

function ThreatGlyph({ variant, color }) {
  // 26px ring. `variant` is one of hollow | half | filled | check.
  const base = {
    width: 26,
    height: 26,
    borderRadius: "50%",
    display: "inline-block",
    verticalAlign: "middle",
    border: `3px solid ${color}`,
    boxSizing: "border-box",
  };
  if (variant === "half") {
    return (
      <span
        aria-hidden="true"
        style={{ ...base, background: `linear-gradient(90deg, ${color} 50%, transparent 50%)` }}
      />
    );
  }
  if (variant === "filled") {
    return <span aria-hidden="true" style={{ ...base, background: color }} />;
  }
  if (variant === "check") {
    return (
      <span
        aria-hidden="true"
        style={{ ...base, background: color, color: "#fff", textAlign: "center", lineHeight: "20px", fontSize: 13 }}
      >
        {"✓"}
      </span>
    );
  }
  return <span aria-hidden="true" style={base} />; // hollow
}

export default function ThreatBand({ threatState = "calm", regime = "in_control", detectedAgo = null }) {
  const state = THREAT_LABELS[threatState] ? threatState : "calm";
  const token = THREAT_TOKENS[state];
  const label = THREAT_LABELS[state];
  const glyph = THREAT_GLYPHS[state];
  const showRegime = regime === "alarm";
  // FIX-018: a defined token, never string concatenation onto a var() call.
  const wash = `var(${THREAT_WASH_TOKENS[state]})`;

  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: showRegime ? "12px 24px 16px" : "16px 24px",
        background: wash,
        borderLeft: `3px solid var(${token})`,
        borderBottom: "1px solid var(--tg-hairline)",
      }}
    >
      <ThreatGlyph variant={glyph} color={`var(${token})`} />
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <strong className="tg-body-strong" style={{ letterSpacing: "0.06em", fontSize: 18 }}>
          {label}
        </strong>
        {showRegime && (
          <span className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
            Prior: under-attack regime &middot; thresholds shifted
          </span>
        )}
      </div>
      {detectedAgo != null && (
        <span className="tg-caption tg-num" style={{ marginLeft: "auto", color: "var(--tg-text-mute)" }}>
          Detected {detectedAgo}s ago
        </span>
      )}
    </div>
  );
}
