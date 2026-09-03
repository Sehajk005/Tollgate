// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §14 / §23.6 FE-T-B4-01..18.
// Real rendering; SVG *attribute* geometry only (jsdom does not lay out --
// pixel overlap / bbox is Playwright's job, §23.3).

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { withNonCoincidentOptima, withDifferentPi } from "../../__fixtures__/synthetic.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import { pathHasSelfIntersection, parsePathPoints } from "./costCurveGeometry.js";
import CostCurve from "./CostCurve.jsx";

const b4 = (art = real) => buildMetricsModel(parseArtifact(art)).block4;
const renderCC = (art = real) => render(<CostCurve block4={b4(art)} />);

const panel = (c, id) => c.querySelector(`svg[aria-labelledby="${id}-t ${id}-d"]`);
const curvePath = (svg) => svg.querySelector('path[stroke="var(--viz-series)"]');
const ribbonPathEl = (svg) => svg.querySelector("path[data-ribbon]");

describe("FE-T-B4: subtitle, headline, gap (M-037, M-014, M-039)", () => {
  it("states series / tier / split from the artifact", () => {
    renderCC();
    expect(
      screen.getByText("series l1-lgbm-v1 · tier challenge · split temporal_test"),
    ).toBeInTheDocument();
  });

  it("renders the ₹2,32,145 headline", () => {
    renderCC();
    // in the headline paragraph (also echoed in Panel C's <desc>)
    expect(screen.getByText(/Regime-switch saving:/)).toHaveTextContent("₹2,32,145");
  });

  it("never shows the ₹0 gap without the word 'structural'", () => {
    renderCC();
    const gap = screen.getByText(/F1-vs-cost gap at π₀/);
    expect(gap).toHaveTextContent("₹0");
    expect(gap).toHaveTextContent(/structural/);
    expect(gap).toHaveTextContent(/precision collapses/);
  });
});

describe("FE-T-B4: three panels, each with a title + desc (A4)", () => {
  it("renders panels A, B, C as role=img with title/desc", () => {
    const { container } = renderCC();
    for (const id of ["cc-a", "cc-b", "cc-c"]) {
      const svg = panel(container, id);
      expect(svg).not.toBeNull();
      expect(svg.getAttribute("role")).toBe("img");
      expect(svg.querySelector("title").textContent.length).toBeGreaterThan(10);
      expect(svg.querySelector("desc").textContent.length).toBeGreaterThan(10);
    }
  });

  it("Panel B and Panel C each draw the full 10-vertex hull curve", () => {
    const { container } = renderCC();
    expect(parsePathPoints(curvePath(panel(container, "cc-b")).getAttribute("d"))).toHaveLength(10);
    expect(parsePathPoints(curvePath(panel(container, "cc-c")).getAttribute("d"))).toHaveLength(10);
  });
});

describe("FE-T-B4: optimum markers (M-004)", () => {
  it("renders exactly ONE optimum marker in Panel A when the optima coincide", () => {
    const { container } = renderCC();
    expect(panel(container, "cc-a").querySelectorAll("circle[data-marker]")).toHaveLength(1);
  });

  it("renders TWO optimum markers when a fixture makes them non-coincident", () => {
    const { container } = renderCC(withNonCoincidentOptima());
    expect(panel(container, "cc-a").querySelectorAll("circle[data-marker]")).toHaveLength(2);
  });

  it("the cost-optimal marker sits >= 6 px clear of the y-axis line", () => {
    const { container } = renderCC();
    const svg = panel(container, "cc-a");
    const axisX = Number(svg.querySelector("line").getAttribute("x1"));
    const cx = Number(svg.querySelector("circle[data-marker]").getAttribute("cx"));
    expect(cx - axisX).toBeGreaterThanOrEqual(6);
  });
});

describe("FE-T-B4: Panel A legibility (M-003) and axis honesty (M-034)", () => {
  it("Panel A's min-to-max vertical extent (curve + ribbon) is >= 40 px", () => {
    const { container } = renderCC();
    const svg = panel(container, "cc-a");
    const ys = [
      ...parsePathPoints(curvePath(svg).getAttribute("d")),
      ...parsePathPoints(ribbonPathEl(svg).getAttribute("d")),
    ].map((p) => p[1]);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThanOrEqual(40);
  });

  it("no <text> is rotated (the y-axis label is horizontal, above the axis)", () => {
    const { container } = renderCC();
    for (const t of container.querySelectorAll("text")) {
      expect(t.getAttribute("transform") || "").not.toMatch(/rotate/);
    }
  });

  it("every <text> is >= 11 px and its anchor lies inside the viewBox", () => {
    const { container } = renderCC();
    for (const t of container.querySelectorAll("text")) {
      expect(Number(t.getAttribute("font-size"))).toBeGreaterThanOrEqual(11);
      const x = Number(t.getAttribute("x"));
      const y = Number(t.getAttribute("y"));
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(520);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(200);
    }
  });
});

describe("FE-T-B4: ribbon validity and placement (M-005)", () => {
  it("the Panel A and Panel B ribbons are SIMPLE polygons", () => {
    const { container } = renderCC();
    expect(
      pathHasSelfIntersection(ribbonPathEl(panel(container, "cc-a")).getAttribute("d")),
    ).toBe(false);
    expect(
      pathHasSelfIntersection(ribbonPathEl(panel(container, "cc-b")).getAttribute("d")),
    ).toBe(false);
  });

  it("Panel C (π₁) carries NO ribbon", () => {
    const { container } = renderCC();
    expect(ribbonPathEl(panel(container, "cc-c"))).toBeNull();
    for (const el of panel(container, "cc-c").querySelectorAll("*")) {
      expect(String(el.getAttribute("fill") || "")).not.toMatch(/viz-ribbon/);
    }
  });
});

describe("FE-T-B4: operating-point table + π drift (M-021)", () => {
  it("renders the exact operating-point table row for the coincident optimum", () => {
    renderCC();
    const table = screen.getByRole("table");
    const row = within(table).getByRole("row", { name: /cost-optimal = F1-optimal/ });
    expect(row).toHaveTextContent("0.0000");
    expect(row).toHaveTextContent("0.469");
    expect(row).toHaveTextContent("₹276");
  });

  it("a fixture with pi0 = 0.002 moves every rendered π label", () => {
    renderCC(withDifferentPi());
    expect(screen.getByText(/F1-vs-cost gap at π₀ = 0\.002/)).toBeInTheDocument();
    expect(screen.getAllByText(/π₁ = 0\.8/).length).toBeGreaterThan(0);
  });
});
