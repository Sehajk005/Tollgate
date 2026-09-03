// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §16 / §23.6 FE-T-B6-01..12.

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import Block6Baselines from "./Block6Baselines.jsx";

const b6 = () => buildMetricsModel(parseArtifact(real)).block6;
const renderB6 = () => render(<Block6Baselines block6={b6()} />);

describe("FE-T-B6: the comparison has a subject (the model row)", () => {
  it("renders a model row with a numeric AP 0.945 and ROC-AUC 0.889", () => {
    renderB6();
    const row = screen.getByRole("row", { name: /model l1-lgbm-v1/ });
    expect(row).toHaveTextContent("0.945");
    expect(row).toHaveTextContent("0.889");
  });

  it("renders B0 AP 0.997 / ROC-AUC 0.994, B1 TPR 0.075, B2 TPR 0.718", () => {
    renderB6();
    expect(screen.getByRole("row", { name: /B0 rules/ })).toHaveTextContent("0.997");
    expect(screen.getByRole("row", { name: /B0 rules/ })).toHaveTextContent("0.994");
    expect(screen.getByRole("row", { name: /B1 decline-velocity/ })).toHaveTextContent("0.075");
    expect(screen.getByRole("row", { name: /B2 BIN-concentration/ })).toHaveTextContent("0.718");
  });

  it("recall @ FPR 1e-3 for model and B0 renders 'not resolvable · n_neg=758', never a number", () => {
    renderB6();
    for (const name of [/model l1-lgbm-v1/, /B0 rules/]) {
      const cell = within(screen.getByRole("row", { name })).getByText(/not resolvable · n_neg=758/);
      expect(cell.textContent).not.toMatch(/\d\.\d{3}/);
    }
  });

  it("Overall rows share a fixed height (M-026 structural proxy; layout is Playwright's)", () => {
    const { container } = renderB6();
    const rows = [...container.querySelectorAll("tbody tr")].slice(0, 4);
    for (const r of rows) expect(r.style.height).toBe("34px");
  });
});

describe("FE-T-B6: B3 sanity floor with a reason on the null (M-038)", () => {
  it("always_positive renders its unreachable reason and no number, for both B1 and B2", () => {
    renderB6();
    const b1floor = screen.getByText(/recall at the B1 operating FPR/);
    const b2floor = screen.getByText(/recall at the B2 operating FPR/);
    expect(b1floor).toHaveTextContent(/always_positive unreachable/);
    expect(b2floor).toHaveTextContent(/always_positive unreachable/);
    expect(b1floor.textContent).toMatch(/always_positive unreachable[^0-9]/);
  });

  it("perfect / random / inverted still render their numeric floor", () => {
    renderB6();
    const b1floor = screen.getByText(/recall at the B1 operating FPR/);
    expect(b1floor).toHaveTextContent("perfect 1.000");
    expect(b1floor).toHaveTextContent("random 0.001");
    expect(b1floor).toHaveTextContent("inverted 0.000");
  });
});

describe("FE-T-B6: per-tier matrix (4 tiers x 4 series)", () => {
  it("renders 16 TPR cells with the right spot values", () => {
    renderB6();
    const perTier = screen.getByRole("table", { name: /beside the model, on every tier/ });
    const bodyRows = within(perTier).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(4);
    for (const r of bodyRows) expect(within(r).getAllByRole("cell")).toHaveLength(4);
    expect(within(perTier).getByRole("row", { name: /^easy/ })).toHaveTextContent("0.000");
    expect(within(perTier).getByRole("row", { name: /^medium/ })).toHaveTextContent("0.946");
    expect(within(perTier).getByRole("row", { name: /^hard/ })).toHaveTextContent("0.791");
  });
});

describe("FE-T-B6: caveats preserved verbatim in meaning", () => {
  it("B2's caveat names B0 and states non-independence (Eval §8)", () => {
    renderB6();
    const c = screen.getByText(/B2 \(BIN-concentration\)/);
    expect(c).toHaveTextContent("B0");
    expect(c).toHaveTextContent(/not independent/);
  });

  it("B1's bitemporal caveat is present", () => {
    renderB6();
    expect(
      screen.getByText(/B1 \(decline-velocity\) needs completed outcomes/),
    ).toBeInTheDocument();
  });
});
