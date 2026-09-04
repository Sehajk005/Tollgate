// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.6 FE-T-GEOM-01..10.
// Pure geometry, no DOM. Every expected value is derived independently from
// the real block4_cost data or from a hand-built minimal input.

import { describe, expect, it } from "vitest";

import real from "../../__fixtures__/realArtifact.js";
import {
  boxesOverlap,
  buildPanelGeometry,
  costDomain,
  linScale,
  logScale,
  markerLayout,
  pathHasSelfIntersection,
  ribbonEnvelope,
  ribbonPath,
  segmentsIntersect,
} from "./costCurveGeometry.js";

const b4 = real.block4_cost;
const SIZE = {
  width: 520,
  height: 200,
  margin: { top: 28, right: 16, bottom: 36, left: 64 },
  xInset: 8,
};

describe("FE-T-GEOM-01..03: ribbonEnvelope from the pre-computed [[fpr,lo,hi]] form", () => {
  it("returns hi >= lo at every index with monotone non-decreasing x", () => {
    const env = ribbonEnvelope(b4.ribbon_envelope);
    expect(env).toHaveLength(10);
    for (let i = 0; i < env.length; i += 1) {
      expect(env[i][2]).toBeGreaterThanOrEqual(env[i][1]);
      if (i > 0) expect(env[i][0]).toBeGreaterThanOrEqual(env[i - 1][0]);
    }
    expect(env[0]).toEqual([0, 5200, 520000]);
  });
});

describe("FE-T-GEOM-04..06: ribbonEnvelope from the raw {pi,curve} form (crossing curves)", () => {
  it("still yields a valid non-crossing envelope by per-index min/max", () => {
    const env = ribbonEnvelope(b4.ribbon);
    expect(env.length).toBeGreaterThan(0);
    for (const [, lo, hi] of env) expect(hi).toBeGreaterThanOrEqual(lo);
    expect(env[0]).toEqual([0, 5200, 520000]);
    expect(env[1][1]).toBeCloseTo(2761.6678858814926, 6);
    expect(env[1][2]).toBeCloseTo(276166.78858814924, 6);
  });

  it("the rendered ribbon polygon is SIMPLE (no crossing edge pair)", () => {
    const x = linScale(0, 1, 64, 504, 8);
    const y = logScale(2000, 2e7, 164, 28);
    const d = ribbonPath(ribbonEnvelope(b4.ribbon_envelope), x, y);
    expect(pathHasSelfIntersection(d)).toBe(false);
  });

  it("a deliberate bowtie polygon IS detected as self-intersecting", () => {
    expect(pathHasSelfIntersection("M0,0 L10,10 L10,0 L0,10 Z")).toBe(true);
    expect(segmentsIntersect([0, 0], [10, 10], [10, 0], [0, 10])).toBe(true);
  });
});

describe("FE-T-GEOM: Panel A decision-region geometry (M-003)", () => {
  const dmax = b4.decision_region_fpr_max;
  const visible = b4.curve_pi0.filter((p) => p[0] <= dmax + 1e-12);
  const yDom = costDomain(visible.map((p) => p[2]));
  const geo = buildPanelGeometry(b4.curve_pi0, [0, dmax], yDom, SIZE);

  it("shows exactly the 3 decision-region vertices (both optima + the next)", () => {
    expect(geo.points).toHaveLength(3);
    expect(geo.points[0].fpr).toBe(0);
    expect(geo.points[2].fpr).toBeCloseTo(0.0013192612137203166, 12);
  });

  it("the min-cost to max-cost vertical span is >= 40 px", () => {
    const ys = geo.points.map((p) => p.py);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThanOrEqual(40);
  });

  it("FPR = 0 maps >= 6 px clear of the y-axis line (M-004)", () => {
    expect(geo.points[0].px - geo.plot.left).toBeGreaterThanOrEqual(6);
    expect(geo.points[0].px - geo.plot.left).toBeCloseTo(8, 5);
  });

  it("carries at least one labelled log gridline inside the narrow window", () => {
    expect(geo.yTicks.length).toBeGreaterThanOrEqual(1);
    for (const t of geo.yTicks) {
      expect(t.value).toBeGreaterThanOrEqual(yDom[0]);
      expect(t.value).toBeLessThanOrEqual(yDom[1]);
    }
  });
});

describe("FE-T-GEOM-07..10: markerLayout", () => {
  it("07: two coincident markers collapse to ONE, lines merged", () => {
    const out = markerLayout([
      { id: "cost", cx: 72, cy: 128, lines: ["cost-optimal"] },
      { id: "f1", cx: 72, cy: 128, lines: ["F1-optimal"] },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].lines).toEqual(["cost-optimal", "F1-optimal"]);
  });

  it("08: two non-coincident markers stay two", () => {
    const out = markerLayout([
      { id: "a", cx: 72, cy: 60, lines: ["a"] },
      { id: "b", cx: 72, cy: 130, lines: ["b"] },
    ]);
    expect(out).toHaveLength(2);
  });

  it("09..10: callout boxes never intersect, even when markers are close", () => {
    const out = markerLayout(
      [
        { id: "a", cx: 72, cy: 100, lines: ["a1", "a2"] },
        { id: "b", cx: 72, cy: 108, lines: ["b1", "b2"] },
      ],
      { plotTop: 0, plotBottom: 400 },
    );
    expect(out).toHaveLength(2);
    expect(boxesOverlap(out[0].box, out[1].box)).toBe(false);
  });
});
