// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.4 -- Vitest setup.
// jest-dom DOM matchers (`toHaveAccessibleName`, `toBeVisible`, ...) + the
// axe-core matcher `toHaveNoViolations` bound to Vitest for the §21 a11y gate.

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";
import { afterEach, expect } from "vitest";

expect.extend(axeMatchers);

// Unmount the React tree between tests so accessible-name / role queries in one
// test never see another test's DOM.
afterEach(() => {
  cleanup();
});

// jsdom does not implement <canvas> 2d context; StreamRail paints one. A no-op
// context keeps App/LiveShell renders from crashing (the rail's pixels are a
// Playwright concern, not jsdom's).
if (typeof HTMLCanvasElement !== "undefined" && !HTMLCanvasElement.prototype.__tgStubbed) {
  HTMLCanvasElement.prototype.getContext = () => ({
    clearRect() {},
    fillRect() {},
    strokeRect() {},
    setTransform() {},
    scale() {},
  });
  HTMLCanvasElement.prototype.__tgStubbed = true;
}

// jsdom has no matchMedia; StreamRail and the reduced-motion path call it.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
  });
}
