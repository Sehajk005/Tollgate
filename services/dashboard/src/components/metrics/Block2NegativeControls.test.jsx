// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §12 / §23.6 FE-T-B2-01..10.

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import Block2NegativeControls from "./Block2NegativeControls.jsx";

const b2 = () => buildMetricsModel(parseArtifact(real)).block2;
const renderB2 = () => render(<Block2NegativeControls block2={b2()} />);

describe("FE-T-B2: the product's own FP rows, per scenario", () => {
  it("every scenario carries an l1-lgbm-v1 and a rules-only-v0 row, first", () => {
    const { container } = renderB2();
    const bodies = container.querySelectorAll("tbody");
    expect(bodies).toHaveLength(7);
    bodies.forEach((body) => {
      const rows = body.querySelectorAll("tr");
      expect(rows[0].textContent).toMatch(/l1-lgbm-v1/);
      expect(rows[1].textContent).toMatch(/rules-only-v0/);
      expect(rows).toHaveLength(6);
    });
  });

  it("the four sanity scorers are retained after the two product rows", () => {
    const { container } = renderB2();
    const firstBody = container.querySelector("tbody");
    const scorers = [...firstBody.querySelectorAll("tr")].map(
      (r) => r.querySelectorAll("td")[0].textContent,
    );
    expect(scorers).toEqual([
      "l1-lgbm-v1",
      "rules-only-v0",
      "perfect",
      "random",
      "inverted",
      "always_positive",
    ]);
  });
});

describe("FE-T-B2: episode flagged is a boolean, never an x/1 rate (M-017)", () => {
  it("renders yes/no and never a '0/1' or '1/1' episode fraction", () => {
    const { container } = renderB2();
    expect(container.textContent).not.toMatch(/\b\d\/1\b/);
    expect(screen.getAllByText("yes").length).toBeGreaterThan(0);
    expect(screen.getAllByText("no").length).toBeGreaterThan(0);
  });
});

describe("FE-T-B2: underpowered vs powered scenarios are visually distinct", () => {
  it("shared_ip_legit renders '0 of 1' and a 'single sample' badge", () => {
    renderB2();
    const body = screen.getByRole("rowheader", { name: /shared_ip_legit/ }).closest("tbody");
    expect(within(body).getAllByText(/0 of 1/).length).toBeGreaterThan(0);
    expect(within(body).getAllByText(/single sample/).length).toBeGreaterThan(0);
  });

  it("flash_sale renders 'n = 720' and a Wilson interval", () => {
    renderB2();
    const body = screen.getByRole("rowheader", { name: /flash_sale/ }).closest("tbody");
    expect(within(body).getAllByText(/n = 720/).length).toBeGreaterThan(0);
    expect(within(body).getAllByText(/95% CI \[/).length).toBeGreaterThan(0);
  });

  it("retry_storm (n=5) shows an 'underpowered — n=5' badge", () => {
    renderB2();
    const body = screen.getByRole("rowheader", { name: /retry_storm/ }).closest("tbody");
    expect(within(body).getAllByText(/underpowered — n=5/).length).toBeGreaterThan(0);
  });
});

describe("FE-T-B2: semantic table (M-024)", () => {
  it("the table has an accessible name and a real rowspan, no empty grouping cell", () => {
    const { container } = renderB2();
    expect(
      screen.getByRole("table", { name: /Negative-control false positives/ }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll('th[rowspan="6"]')).toHaveLength(7);
    expect(screen.queryAllByRole("cell", { name: "" })).toHaveLength(0);
  });

  it("renders θ_challenge from the artifact to 6 dp in the caption", () => {
    renderB2();
    expect(screen.getByText(/θ_challenge = 0\.257143/)).toBeInTheDocument();
  });
});
