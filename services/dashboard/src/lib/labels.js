// Day 8, Step 3 -- the label / glyph / token maps the shell and its screens
// share. Source: UIUX v2 SS2.1 (colour is never load-bearing -- every threat
// state carries a text label AND a shape) and SS6.1 (threat band states).
//
// `threat_state` is ALWAYS rendered verbatim from the SSE event; it is never
// derived in the frontend (that discipline is from Day 2 and holds).

// Uppercase text label per state -- the primary, colour-independent signal.
export const THREAT_LABELS = {
  calm: "CALM",
  elevated: "ELEVATED",
  under_attack: "UNDER ATTACK",
  resolved: "RESOLVED",
};

// A DISTINCT shape per state (UIUX v2 SS2.5): hollow ring / half-filled ring /
// filled ring / check ring. No two states share a glyph, so a colourblind
// operator reads the band perfectly.
export const THREAT_GLYPHS = {
  calm: "hollow",
  elevated: "half",
  under_attack: "filled",
  resolved: "check",
};

// State colour token (secondary -- reinforces, never carries, the signal).
export const THREAT_TOKENS = {
  calm: "--tg-calm",
  elevated: "--tg-elevated",
  under_attack: "--tg-attack",
  resolved: "--tg-resolved",
};

// Remediation plan FIX-018 (AUDIT-018) -- the band's background WASH.
// ThreatBand built it as `var(${token})1A`, which produces the literal string
// "var(--tg-attack)1A": not a colour, so the browser dropped the declaration
// and the band rendered with no wash at all in every non-calm state. The
// low-alpha tokens it needed already existed in tokens.css; this maps to them.
// No new token, no color-mix() dependency, and colour stays non-load-bearing
// (UIUX v2 SS2.5) -- the label and glyph carry the state.
export const THREAT_WASH_TOKENS = {
  calm: "--tg-surface-1",
  elevated: "--tg-elevated-wash",
  under_attack: "--tg-attack-wash",
  resolved: "--tg-resolved-wash",
};

// Decision tier -> stream-rail / ticker stripe colour token. Monitoring is
// neutral grey, never blue (UIUX v2 SS2.1).
export const TIER_TOKENS = {
  allow: "--tg-calm",
  monitor: "--tg-calm",
  throttle: "--tg-elevated",
  challenge: "--tg-elevated",
  step_up: "--tg-attack",
  block: "--tg-attack",
};

export function threatLabel(state) {
  return THREAT_LABELS[state] || String(state || "calm").toUpperCase().replace(/_/g, " ");
}

export function threatGlyph(state) {
  return THREAT_GLYPHS[state] || "hollow";
}
