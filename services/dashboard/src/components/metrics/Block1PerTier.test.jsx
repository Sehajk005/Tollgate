// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §11 / §23.6 FE-T-B1-01..23.
// Real React rendering against the REAL committed artifact (§23.5) -- exact
// numeric strings, roles, accessible names and attribute geometry. Layout
// (overlap / row height / font size) is Playwright's job, never jsdom's.

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { withResolvableRecall } from "../../__fixtures__/synthetic.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import Block1PerTier from "./Block1PerTier.jsx";

const model = (artifact = real) => buildMetricsModel(parseArtifact(artifact));

function renderBlock(artifact = real) {
  return render(<Block1PerTier block1={model(artifact).block1} />);
}

describe("FE-T-B1: 1b prevalence-normalised AP (π_eval = 0.01, comparable)", () => {
  it("renders the model's four ap_at_eval_prevalence values exactly", () => {
    renderBlock();
    expect(screen.getByRole("group", { name: /easy, model, average precision 0\.018/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /medium, model, average precision 0\.978/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /hard, model, average precision 0\.744/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /evasive, model, average precision 0\.411/ })).toBeInTheDocument();
  });

  it("renders B0's four ap_at_eval_prevalence values exactly", () => {
    renderBlock();
    expect(screen.getByRole("group", { name: /easy, B0, average precision 0\.997/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /medium, B0, average precision 0\.988/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /hard, B0, average precision 0\.639/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /evasive, B0, average precision 0\.597/ })).toBeInTheDocument();
  });

  it("names π_eval = 0.01 in the 1b sub-heading; 'comparable' appears only there", () => {
    renderBlock();
    const h1b = screen.getByText(/1b\. Prevalence-normalised AP/);
    expect(h1b).toHaveTextContent("π_eval = 0.01");
    expect(h1b).toHaveTextContent(/comparable across tiers/);
    const h1c = screen.getByText(/1c\. Within-tier AP/);
    expect(h1c.textContent).not.toMatch(/comparable/);
  });

  it("draws the π_eval reference marker at left = 1% on every 1b bar", () => {
    const { container } = renderBlock();
    const markers = container.querySelectorAll('[data-ref-marker="π_eval"]');
    expect(markers.length).toBe(8); // 4 tiers x {model, B0}
    for (const m of markers) expect(parseFloat(m.style.left)).toBeCloseTo(1, 5);
  });
});

describe("FE-T-B1: 1c within-tier AP (tier-own prevalence, NOT cross-tier)", () => {
  it("renders the model's four ap_raw values exactly", () => {
    renderBlock();
    expect(screen.getByRole("group", { name: /easy, model, average precision 0\.789/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /medium, model, average precision 0\.998/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /hard, model, average precision 0\.935/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /evasive, model, average precision 0\.814/ })).toBeInTheDocument();
  });

  it("renders B0's four ap_raw values exactly (0.9998 -> '1.000' pinned)", () => {
    renderBlock();
    expect(screen.getByRole("group", { name: /easy, B0, average precision 1\.000/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /medium, B0, average precision 0\.999/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /hard, B0, average precision 0\.981/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /evasive, B0, average precision 0\.958/ })).toBeInTheDocument();
  });

  it("prints each tier's own prevalence adjacent to its ap_raw", () => {
    renderBlock();
    const easy = screen.getByRole("group", { name: /easy, model, average precision 0\.789/ });
    expect(easy).toHaveTextContent("prevalence 0.731");
    expect(easy).toHaveTextContent("n=821");
    expect(screen.getByRole("group", { name: /medium, model, average precision 0\.998/ })).toHaveTextContent("prevalence 0.685");
    expect(screen.getByRole("group", { name: /hard, model, average precision 0\.935/ })).toHaveTextContent("prevalence 0.476");
    expect(screen.getByRole("group", { name: /evasive, model, average precision 0\.814/ })).toHaveTextContent("prevalence 0.433");
  });

  it("draws the prevalence reference marker at left = prevalence*100% (easy = 73.08%)", () => {
    renderBlock();
    const easy = screen.getByRole("group", { name: /easy, model, average precision 0\.789/ });
    const marker = easy.querySelector("[data-ref-marker='prevalence']");
    expect(marker).not.toBeNull();
    expect(parseFloat(marker.style.left)).toBeCloseTo(73.0816077953715, 4);
  });

  it("labels 1c explicitly as not cross-tier comparable", () => {
    renderBlock();
    expect(screen.getByText(/1c\. Within-tier AP/)).toHaveTextContent(/not cross-tier/);
    expect(screen.getByText(/must not be read across tiers/)).toBeInTheDocument();
  });
});

describe("FE-T-B1: 1a cross-tier comparator (recall @ FPR 1e-3) stays unavailable", () => {
  it("renders no recall value as a number anywhere in the 1a group", () => {
    renderBlock();
    const region = screen.getByTestId("block1-recall-unavailable");
    expect(within(region).queryByText(/\d+\.\d{3}/)).toBeNull();
  });

  it("keeps n_neg in every one of the 8 recall rows and states the reason once", () => {
    renderBlock();
    const region = screen.getByTestId("block1-recall-unavailable");
    const rows = within(region).getAllByRole("group");
    expect(rows).toHaveLength(8);
    for (const r of rows) expect(r.textContent).toMatch(/n_neg=(221|316)/);
    expect(within(region).getAllByText(/not resolvable on these splits/)).toHaveLength(1);
  });

  it("no unavailable row's accessible name reads as a bare zero (§21.2 A7)", () => {
    renderBlock();
    const region = screen.getByTestId("block1-recall-unavailable");
    for (const r of within(region).getAllByRole("group")) {
      expect(r.getAttribute("aria-label")).not.toMatch(/\b0(\.0+)?\b/);
    }
  });

  it("a synthetic resolvable recall is still never drawn as a number in 1a", () => {
    renderBlock(withResolvableRecall("medium"));
    const region = screen.getByTestId("block1-recall-unavailable");
    expect(within(region).queryByText(/0\.812/)).toBeNull();
  });
});

describe("FE-T-B1-19: the evasive tier is labelled with its split, styled identically", () => {
  it("names tier_e on the evasive rows and temporal_test on the easy rows", () => {
    renderBlock();
    expect(screen.getByRole("group", { name: /evasive, model, average precision 0\.411/ })).toHaveTextContent("tier_e");
    expect(screen.getAllByText(/temporal_test/).length).toBeGreaterThan(0);
  });

  it("every model-series bar fill is var(--viz-series) -- no per-tier override", () => {
    const { container } = renderBlock();
    const modelBars = [...container.querySelectorAll("div")].filter(
      (d) => d.style && d.style.background === "var(--viz-series)" && d.style.borderRadius === "2px",
    );
    expect(modelBars.length).toBeGreaterThanOrEqual(8);
  });
});

describe("FE-T-B1-13..18 / FE-T-B1-23: the verdict and caption", () => {
  it("states B0 as stronger at every tier, above the fold (not collapsed)", () => {
    renderBlock();
    const v = screen.getByText(/rules baseline outperforms the learned model/i);
    expect(v).toBeInTheDocument();
    expect(v).toHaveTextContent(/weaker than B0 overall/);
    expect(v).toHaveTextContent(/0\.889 vs 0\.994/);
  });

  it("the caption makes no claim about a bar height (M-015)", () => {
    renderBlock();
    expect(screen.queryByText(/at whatever height it is/i)).toBeNull();
  });
});
