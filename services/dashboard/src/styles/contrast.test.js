// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §21.1 (FIX-M-023) + §23.6
// FE-T-A11Y-01..04 -- the contrast unit test.
//
// The audit measured five WCAG-AA failures on the Metrics page, ALL caused by
// one token: `--tg-text-mute` (#6E7885, 4.34:1 on the canvas), which styles
// every caption, the provenance line, both SVG axis labels and -- worst -- every
// `n/a` / `n_neg=` value. The remediation lightens it to #8B95A3.
//
// This test recomputes the WCAG 2.1 contrast ratio straight from the hex values
// in `tokens.css` (the source of truth -- no browser, no computed style) for
// every (foreground-text token, background token) pair the Metrics page paints,
// and asserts >= 4.5:1 for all of them. Playwright (E2E #17) separately checks
// the running page's *computed* styles resolve to these same tokens.
//
// Token pairs the page actually uses (grepped from components/metrics/**,
// components/charts/**, screens/D6Metrics.jsx):
//   foreground text : --tg-text  --tg-text-2  --tg-text-mute  --viz-flag
//   background      : --tg-canvas  --tg-surface-1  --tg-surface-2
// `--tg-primary` as the nav active-item colour is an interactive affordance, not
// a body/caption role, and is paired with a 2px border + aria-current (WCAG
// 1.4.1); §21.1 scopes M-023 to `--tg-text-mute` and it is out of scope here.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Read the real stylesheet off disk. `import "./tokens.css"` can't be used --
// vitest.config.js sets `css: false`, so a CSS import resolves to nothing; and
// under jsdom `import.meta.url` is an http: URL, not a file: one. vitest runs
// with cwd = services/dashboard (its config root).
const CSS = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

/** Pull a `--name: #rrggbb;` value out of tokens.css, or throw if it is gone. */
function token(name) {
  const m = CSS.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})\\b`));
  if (!m) throw new Error(`tokens.css no longer defines --${name}`);
  return m[1];
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

// WCAG 2.1 relative luminance (https://www.w3.org/TR/WCAG21/#dfn-relative-luminance).
function channel(c8) {
  const c = c8 / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
function contrast(fgHex, bgHex) {
  const a = luminance(fgHex);
  const b = luminance(bgHex);
  const [hi, lo] = a >= b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

const AA_NORMAL = 4.5;

const BACKGROUNDS = ["tg-canvas", "tg-surface-1", "tg-surface-2"];
const BODY_TEXT = ["tg-text", "tg-text-2", "tg-text-mute", "viz-flag"];

describe("contrast helper is calibrated against the audit's own measurements", () => {
  it("reproduces the audit's 4.34:1 for the pre-remediation muted token on the canvas", () => {
    // METRICS-AUDIT §21.1 measured rgb(110,120,133) on rgb(11,13,16) = 4.34.
    expect(contrast("#6E7885", "#0B0D10")).toBeCloseTo(4.34, 2);
  });
  it("reproduces the audit's 8.88:1 for --tg-text-2 on the canvas", () => {
    expect(contrast("#A7B0BC", "#0B0D10")).toBeCloseTo(8.88, 2);
  });
});

describe("FE-T-A11Y-01: FIX-M-023 -- --tg-text-mute clears WCAG AA", () => {
  it("is no longer the failing #6E7885", () => {
    expect(token("tg-text-mute").toLowerCase()).not.toBe("#6e7885");
    expect(token("tg-text-mute").toLowerCase()).toBe("#8b95a3");
  });

  it("reaches >= 4.5:1 on the page background (the headline M-023 fix)", () => {
    const ratio = contrast(token("tg-text-mute"), token("tg-canvas"));
    expect(ratio).toBeGreaterThanOrEqual(AA_NORMAL);
    // chosen with headroom, not on the line -- guards a drift back toward 4.5
    expect(ratio).toBeGreaterThan(5);
  });

  it("also clears AA on both raised surfaces (captions sit on panels too)", () => {
    expect(contrast(token("tg-text-mute"), token("tg-surface-1"))).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(contrast(token("tg-text-mute"), token("tg-surface-2"))).toBeGreaterThanOrEqual(AA_NORMAL);
  });
});

describe("FE-T-A11Y-02..03: every body/caption text token on every page surface", () => {
  for (const fg of BODY_TEXT) {
    for (const bg of BACKGROUNDS) {
      it(`--${fg} on --${bg} is >= 4.5:1`, () => {
        expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(AA_NORMAL);
      });
    }
  }
});

describe("FE-T-A11Y-04: the muted token stays the lowest step of the text hierarchy", () => {
  it("keeps --tg-text > --tg-text-2 > --tg-text-mute in luminance (§21.1)", () => {
    const text = luminance(token("tg-text"));
    const text2 = luminance(token("tg-text-2"));
    const mute = luminance(token("tg-text-mute"));
    expect(text).toBeGreaterThan(text2);
    expect(text2).toBeGreaterThan(mute);
  });

  it("--tg-text clears AAA (7:1) on the canvas -- the primary reading colour", () => {
    expect(contrast(token("tg-text"), token("tg-canvas"))).toBeGreaterThanOrEqual(7);
  });
});
