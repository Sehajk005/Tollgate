// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §13 / §23.6 FE-T-B3-01..16.

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import auditBarsSource from "./AuditBars.jsx?raw";
import real from "../../__fixtures__/realArtifact.js";
import { deepSet } from "../../__fixtures__/mutate.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import AuditBars from "./AuditBars.jsx";

const b3 = (art = real) => buildMetricsModel(parseArtifact(art)).block3;
const renderAB = (art = real) => render(<AuditBars block3={b3(art)} />);

describe("FE-T-B3: grouping, sort, and the flag read from the artifact", () => {
  it("renders three groups with the right counts (6 flagged, 4 measured, 14 not fed)", async () => {
    renderAB();
    expect(
      screen.getByText(/6 features excluded as probable generator artifacts/),
    ).toBeInTheDocument();
    expect(screen.getByText(/^4 measured$/)).toBeInTheDocument();
    const disclosure = screen.getByRole("button", { name: /14 not fed/ });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(disclosure);
    expect(within(screen.getByTestId("block3-not-fed")).getAllByRole("group")).toHaveLength(14);
  });

  it("card_seen_24h sorts above bin_entropy_5m and renders inverted + its raw AUC 0.225", () => {
    const { container } = renderAB();
    const html = container.innerHTML;
    expect(html.indexOf("card_seen_24h")).toBeLessThan(html.indexOf("bin_entropy_5m"));
    const row = screen.getByRole("group", { name: /card_seen_24h/ });
    expect(row).toHaveTextContent("AUC 0.225");
    expect(row.getAttribute("aria-label")).toMatch(/inverted/);
  });

  it("bar length encodes separability, not raw AUC (bin_hhi_5m AUC 0.289 still gets a long bar)", () => {
    renderAB();
    const row = screen.getByRole("group", { name: /bin_hhi_5m/ });
    const fill = [...row.querySelectorAll("div")].find(
      (d) => d.style.width && d.style.width.endsWith("%"),
    );
    expect(parseFloat(fill.style.width)).toBeGreaterThan(40);
  });

  it("the flagged bars are amber, the measured bars are grey, the not-fed have none", async () => {
    const { container } = renderAB();
    const amber = [...container.querySelectorAll("div")].filter(
      (d) => d.style.background === "var(--viz-flag)",
    );
    const grey = [...container.querySelectorAll("div")].filter(
      (d) => d.style.background === "var(--viz-series)" && d.style.borderRadius === "2px",
    );
    expect(amber).toHaveLength(6);
    expect(grey).toHaveLength(4);
    await userEvent.click(screen.getByRole("button", { name: /14 not fed/ }));
    const notFed = screen.getByTestId("block3-not-fed");
    expect(
      [...notFed.querySelectorAll("*")].some((el) => el.style && el.style.width.endsWith("%")),
    ).toBe(false);
  });
});

describe("FE-T-B3-06: the 14 un-fed constants are not measurements", () => {
  it("the string '0.500' appears nowhere, collapsed or expanded", async () => {
    const { container } = renderAB();
    expect(container.textContent).not.toContain("0.500");
    await userEvent.click(screen.getByRole("button", { name: /14 not fed/ }));
    expect(container.textContent).not.toContain("0.500");
  });

  it("each not-fed row's accessible name never reads as a bare zero (A7)", async () => {
    renderAB();
    await userEvent.click(screen.getByRole("button", { name: /14 not fed/ }));
    for (const g of within(screen.getByTestId("block3-not-fed")).getAllByRole("group")) {
      expect(g.getAttribute("aria-label")).not.toMatch(/\b0(\.0+)?\b/);
    }
  });
});

describe("FE-T-B3: threshold read from the artifact, no 0.95 literal (M-012)", () => {
  it("the threshold marker sits at 90% and MOVES to 80% when the artifact threshold is 0.90", () => {
    const { container: a } = renderAB();
    expect(parseFloat(a.querySelector("[data-threshold-marker]").style.left)).toBeCloseTo(90, 5);

    const { container: b } = renderAB(deepSet(real, "block3_audit.univariate_auc_threshold", 0.9));
    expect(parseFloat(b.querySelector("[data-threshold-marker]").style.left)).toBeCloseTo(80, 5);
  });

  it("the component source contains no 0.95 literal (legitimate absence assertion)", () => {
    const code = auditBarsSource.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(code).not.toMatch(/0\.95\b/);
  });

  it("the component authors no internal spec-ID copy (M-032)", () => {
    // M-032 bans component-AUTHORED build-log strings, not faithfully rendered
    // artifact data (feature `reason`s legitimately cite the spec -- FIX-M-006
    // requires rendering them). Scan the source with comments stripped.
    const code = auditBarsSource.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(code).not.toMatch(/UIUX v2|SS6\.13|SS\d|Eval Protocol §/);
  });
});

describe("FE-T-B3: the 6 flagged features each render their own reason", () => {
  it("shows distinct per-feature reasons, not a repeated 6x label", () => {
    renderAB();
    expect(screen.getByText(/card enumeration within a small issuer pool/)).toBeInTheDocument();
    expect(screen.getByText(/small BIN pool \(bin_pool_size 4\)/)).toBeInTheDocument();
    expect(screen.queryByText(/FLAGGED — GENERATOR ARTIFACT/)).toBeNull();
  });
});
