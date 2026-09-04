// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §21.2 (FIX-M-024) + §23.6
// FE-T-A11Y-05..12 -- axe-core over the full page render.
//
// jsdom does not lay out and vitest.config.js sets `css: false`, so the
// `color-contrast` rule cannot resolve custom properties here -- that check is
// split between contrast.test.js (token maths) and Playwright E2E #17 (computed
// styles). Everything else axe checks -- roles, names, ARIA validity, nested
// interactives, table semantics, heading order, landmark containment -- is
// structural and runs fine.

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";

import D6Metrics from "./D6Metrics.jsx";
import { withDifferentPi } from "../__fixtures__/synthetic.js";

function renderPage(props) {
  // the real landmark structure App.jsx mounts: .tg-app > main > screen
  return render(
    <div className="tg-app">
      <main>
        <D6Metrics {...props} />
      </main>
    </div>,
  );
}

const axeOpts = { rules: { "color-contrast": { enabled: false } } };

// axe-core walking the whole page under jsdom is slow (~5-10s) and single-flight
// -- give each run room and never overlap two.
const AXE_TIMEOUT = 30000;

describe("FE-T-A11Y-05..12: axe-core over the whole D6 page", () => {
  it(
    "reports zero violations on the happy path against the real artifact",
    async () => {
      const { container } = renderPage();
      expect(await axe(container, axeOpts)).toHaveNoViolations();
    },
    AXE_TIMEOUT,
  );

  it(
    "reports zero violations on a drifted-π artifact (copy still generated, not hard-coded)",
    async () => {
      const { container } = renderPage({ artifact: withDifferentPi() });
      expect(await axe(container, axeOpts)).toHaveNoViolations();
    },
    AXE_TIMEOUT,
  );
});

describe("FE-T-A11Y: named structure the axe run relies on", () => {
  it("every data table has an accessible name (caption or aria-label)", () => {
    const { container } = renderPage();
    const tables = [...container.querySelectorAll("table")];
    expect(tables.length).toBeGreaterThan(0);
    for (const t of tables) {
      const named =
        t.querySelector("caption")?.textContent?.trim() ||
        t.getAttribute("aria-label") ||
        (t.getAttribute("aria-labelledby") &&
          container.querySelector(`#${t.getAttribute("aria-labelledby")}`)?.textContent);
      expect(named, `table #${tables.indexOf(t)} has no accessible name`).toBeTruthy();
    }
  });

  it("every chart SVG marked role=img carries a <title>", () => {
    const { container } = renderPage();
    const imgSvgs = [...container.querySelectorAll('svg[role="img"]')];
    expect(imgSvgs.length).toBeGreaterThan(0);
    for (const svg of imgSvgs) {
      expect(svg.querySelector("title")?.textContent?.trim()).toBeTruthy();
    }
  });

  it("the page content sits inside a single <main> landmark", () => {
    const { container } = renderPage();
    expect(container.querySelectorAll("main")).toHaveLength(1);
  });
});

describe("FE-T-A11Y: null rows never announce as a bare zero (§21.1)", () => {
  // Scope: the UnavailableGroup rows -- the null-state primitive. A resolved
  // measurement row legitimately carries "0.018" in its name; an UNAVAILABLE
  // row must read "not resolvable, n_neg=221" and never a standalone "0".
  it("no unavailable-row accessible name matches /\\b0(\\.0+)?\\b/", () => {
    const { container } = renderPage();
    const rows = [
      ...container.querySelectorAll(
        '[data-testid="block1-recall-unavailable"] [role="group"], ' +
          '[data-testid="block3-not-fed"] [role="group"]',
      ),
    ];
    expect(rows.length).toBeGreaterThan(0); // block1's 8 recall-unavailable rows
    for (const g of rows) {
      const name = g.getAttribute("aria-label") || "";
      expect(name, `unavailable row announces a bare zero: "${name}"`).not.toMatch(
        /\b0(\.0+)?\b/,
      );
      expect(name).toMatch(/not resolvable|not fed|unreachable|n_neg=/i);
    }
  });
});
