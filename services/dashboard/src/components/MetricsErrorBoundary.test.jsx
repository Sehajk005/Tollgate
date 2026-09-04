// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.3 / §18.5 -- FE-T-ERR.
// A malformed artifact degrades ONE screen with a NAMED cause; the boundary
// never swallows the original (always console.error); no fabricated 0 / NaN
// reaches the fallback.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import MetricsErrorBoundary from "./MetricsErrorBoundary.jsx";
import D6Metrics from "../screens/D6Metrics.jsx";
import {
  malformedCurve,
  missingBlock,
  missingProvenance,
  wrongSchemaVersion,
} from "../__fixtures__/malformed.js";

afterEach(() => vi.restoreAllMocks());

function Boom() {
  throw new Error("synthetic render failure");
}

function renderBoundary(child) {
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  const utils = render(
    <div>
      <nav data-testid="shell-nav">nav</nav>
      <MetricsErrorBoundary>{child}</MetricsErrorBoundary>
    </div>,
  );
  return { ...utils, spy };
}

describe("FE-T-ERR: the boundary catches, names and logs", () => {
  it("renders an actionable fallback and keeps the shell mounted", () => {
    const { spy } = renderBoundary(<Boom />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be read/i);
    expect(screen.getByText(/python -m eval\.harness --split all --seed 42/)).toBeInTheDocument();
    expect(screen.getByTestId("shell-nav")).toBeInTheDocument();
    expect(spy).toHaveBeenCalled();
  });

  it("names 'provenance' for the missing-provenance artifact", () => {
    renderBoundary(<D6Metrics artifact={missingProvenance} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/provenance/);
  });

  it("names 'block3_audit' for a missing block", () => {
    renderBoundary(<D6Metrics artifact={missingBlock} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/block3_audit/);
  });

  it("names 'block4_cost.curve_pi0' for an empty curve", () => {
    renderBoundary(<D6Metrics artifact={malformedCurve} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/curve_pi0/);
    expect(alert.textContent).not.toMatch(/\bNaN\b/);
  });

  it("names the schema version and the regeneration command for schema_version 99", () => {
    renderBoundary(<D6Metrics artifact={wrongSchemaVersion} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("99");
    expect(alert).toHaveTextContent(/python -m eval\.harness/);
  });

  it("the fallback contains no bare-zero leaf and no NaN/undefined", () => {
    renderBoundary(<D6Metrics artifact={missingProvenance} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).not.toMatch(/\bNaN\b|\bundefined\b/);
    const leaves = [...alert.querySelectorAll("*")].filter((el) => el.children.length === 0);
    for (const el of leaves) {
      expect(el.textContent.trim()).not.toMatch(/^(0|0\.0+|NaN)$/);
    }
  });

  it("passes children through untouched when nothing throws", () => {
    renderBoundary(<div data-testid="ok">fine</div>);
    expect(screen.getByTestId("ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
