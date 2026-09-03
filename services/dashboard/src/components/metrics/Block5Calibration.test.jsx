// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §15 / §23.6 FE-T-B5-01..12.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { withPriorCorrectionFailed, withDifferentPi } from "../../__fixtures__/synthetic.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import Block5Calibration from "./Block5Calibration.jsx";

const b5 = (art = real) => buildMetricsModel(parseArtifact(art)).block5;
const renderB5 = (art = real) => render(<Block5Calibration block5={b5(art)} />);

describe("FE-T-B5: the 2 x 6 grid (raw + Platt + Platt+prior for Brier AND ECE)", () => {
  it("renders every exact value for π₀", () => {
    renderB5();
    const row = screen.getByRole("row", { name: /π₀ = 0\.001/ });
    for (const v of ["0.1193", "0.0108", "0.0007", "0.2620", "0.0703"]) {
      expect(row).toHaveTextContent(v);
    }
    expect(row).toHaveTextContent("759.5");
  });

  it("renders every exact value for π₁", () => {
    renderB5();
    const row = screen.getByRole("row", { name: /π₁ = 0\.9/ });
    for (const v of ["0.1403", "0.3413", "0.2020", "0.2089", "0.3955", "0.2807"]) {
      expect(row).toHaveTextContent(v);
    }
    expect(row).toHaveTextContent("1650.9");
  });

  it("states n and raw prevalence in the caption", () => {
    renderB5();
    expect(screen.getByText(/n = 2125/)).toHaveTextContent("raw prevalence 0.643");
  });
});

describe("FE-T-B5: the verdict, first (5a)", () => {
  it("states the π₁ result, the word 'reduces', and the direction convention", () => {
    renderB5();
    const v = screen.getByText(/Prior correction works at both regimes/);
    expect(v).toHaveTextContent("0.3955");
    expect(v).toHaveTextContent("0.2807");
    expect(v).toHaveTextContent(/reduces/);
    expect(v.textContent.toLowerCase()).toContain("lower is better");
  });

  it("a prior_correction_helped_at_pi1:false fixture flips the verdict and drops 'reduces'", () => {
    renderB5(withPriorCorrectionFailed());
    const v = screen.getByText(/Prior correction does NOT improve ECE/);
    expect(v).toHaveTextContent(/broken/);
    expect(v.textContent).not.toMatch(/reduces/);
  });
});

describe("FE-T-B5: magnitude encoding (M-036)", () => {
  it("0.3955 renders a wider magnitude bar than 0.0007 (not typographically identical)", () => {
    renderB5();
    const bar = (cellText) => {
      const cell = screen.getAllByText(cellText)[0].closest("td");
      const fill = cell.querySelector("span > span");
      return parseFloat(fill.style.width);
    };
    expect(bar("0.3955")).toBeGreaterThan(bar("0.0007"));
  });
});

describe("FE-T-B5: reliability diagrams (5c)", () => {
  it("plots 5 non-empty bins at π₀ and 6 at π₁, and states the omitted count", () => {
    const { container } = renderB5();
    const svgs = container.querySelectorAll('svg[role="img"]');
    expect(svgs).toHaveLength(2);
    expect(svgs[0].querySelectorAll("circle[data-weight]")).toHaveLength(5);
    expect(svgs[1].querySelectorAll("circle[data-weight]")).toHaveLength(6);
    expect(screen.getByText(/5 empty bins omitted/)).toBeInTheDocument();
    expect(screen.getByText(/4 empty bins omitted/)).toBeInTheDocument();
  });

  it("point radius is a monotone function of bin weight", () => {
    const { container } = renderB5();
    const circles = [...container.querySelectorAll("circle[data-weight]")]
      .map((c) => ({ w: Number(c.getAttribute("data-weight")), r: Number(c.getAttribute("r")) }))
      .sort((a, b) => a.w - b.w);
    for (let i = 1; i < circles.length; i += 1) {
      expect(circles[i].r).toBeGreaterThanOrEqual(circles[i - 1].r - 1e-9);
    }
  });

  it("each diagram carries a title + desc (A4)", () => {
    const { container } = renderB5();
    for (const svg of container.querySelectorAll('svg[role="img"]')) {
      expect(svg.querySelector("title").textContent).toMatch(/Reliability diagram/);
      expect(svg.querySelector("desc").textContent.length).toBeGreaterThan(10);
    }
  });
});

describe("FE-T-B5: regime labels sourced from the artifact (M-021)", () => {
  it("a fixture with pi0 = 0.002 moves the regime label and the diagram label", () => {
    renderB5(withDifferentPi());
    expect(screen.getByRole("row", { name: /π₀ = 0\.002/ })).toBeInTheDocument();
    expect(screen.getAllByText(/π₀ = 0\.002/).length).toBeGreaterThan(1);
  });
});

describe("guard", () => {
  it("renders 'not measured' when calibration is unavailable", () => {
    render(<Block5Calibration block5={{ available: false }} />);
    expect(screen.getByText(/not measured in this artifact/i)).toBeInTheDocument();
  });
});
