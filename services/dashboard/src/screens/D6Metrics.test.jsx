// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §7 / §20.2 / §23.6 -- the D6
// screen is a composition over buildMetricsModel(parseArtifact(artifact)).
// Smoke + FE-T-SUM (executive summary generated from the artifact) + the
// identity line. Full per-block coverage lives in the block test files.

import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";

import D6Metrics from "./D6Metrics.jsx";
import { explicitNulls, missingCalibration } from "../__fixtures__/malformed.js";

afterEach(() => vi.restoreAllMocks());

describe("D6Metrics composition (happy path against the real artifact)", () => {
  it("renders the six blocks in argument order", () => {
    render(<D6Metrics />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(
      expect.arrayContaining([
        "1. Per-tier performance",
        "2. Negative-control false positives",
        "3. Discriminability audit",
        "4. Cost curves",
        "5. Calibration",
        "6. Baseline comparison",
      ]),
    );
  });

  it("shows the Eval §9 identity line without interaction", () => {
    render(<D6Metrics />);
    const line = screen.getByText(/seed 42/);
    expect(line).toHaveTextContent("model l1-lgbm-v1");
    expect(line).toHaveTextContent("policy 1");
    expect(line).toHaveTextContent("π_eval 0.01");
    expect(line).toHaveTextContent("split temporal_test");
    expect(line).toHaveTextContent("seeds_used 1");
  });

  it("FE-T-SUM: the executive summary is generated from the artifact and leads with B0-beats-model", () => {
    render(<D6Metrics />);
    const summary = screen.getByRole("region", { name: /executive summary/i });
    expect(within(summary).getByText(/B0 outperforms the learned model/i)).toBeInTheDocument();
    expect(within(summary).getByText(/₹2,32,145/)).toBeInTheDocument();
    expect(within(summary).getByText(/0\.3955/)).toBeInTheDocument();
    expect(within(summary).getByText(/0\.2807/)).toBeInTheDocument();
  });

  it("the executive summary renders above block 1 (DOM order)", () => {
    render(<D6Metrics />);
    const summary = screen.getByRole("region", { name: /executive summary/i });
    const block1 = screen.getByRole("heading", { level: 2, name: "1. Per-tier performance" });
    expect(summary.compareDocumentPosition(block1) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders no NaN, and no bare-zero / bare-undefined leaf, on the happy path", () => {
    const { container } = render(<D6Metrics />);
    // "NaN" never appears in any artifact string -- a real red flag.
    expect(container.textContent).not.toMatch(/\bNaN\b/);
    // A leaf that is EXACTLY "0" / "undefined" / "NaN" signals a fabricated
    // value; "0.000" (a real measurement) and prose containing "undefined" (a
    // faithfully rendered reason string) are fine. SVG axis origins excluded.
    const leaves = [...container.querySelectorAll("*")].filter(
      (el) => el.children.length === 0 && el.closest("svg") == null,
    );
    for (const el of leaves) expect(el.textContent.trim()).not.toMatch(/^(0|NaN|undefined)$/);
  });
});

describe("D6Metrics degrades gracefully on non-throwing malformed inputs", () => {
  it("missingCalibration -> Block 5 says 'not measured', page still renders", () => {
    render(<D6Metrics artifact={missingCalibration} />);
    // rendered both in the generated summary sentence and in the Block 5 body
    expect(screen.getAllByText(/not measured in this artifact/i).length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("heading", { level: 2, name: "1. Per-tier performance" }),
    ).toBeInTheDocument();
  });

  it("explicitNulls -> nulled fields render 'n/a', never a fabricated 0", () => {
    const { container } = render(<D6Metrics artifact={explicitNulls} />);
    expect(container.textContent).not.toMatch(/\bNaN\b/);
    // the nulled model easy ap_raw shows as n/a in the generated summary
    expect(screen.getByText(/easy: 1\.000 vs n\/a/)).toBeInTheDocument();
    const leaves = [...container.querySelectorAll("*")].filter(
      (el) => el.children.length === 0 && el.closest("svg") == null,
    );
    for (const el of leaves) expect(el.textContent.trim()).not.toMatch(/^(0|NaN|undefined)$/);
  });
});
