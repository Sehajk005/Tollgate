// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §11 FIX-M-028 / §20.5 -- the
// shared null-state primitive: one reason, N rows, ZERO filled track elements,
// the denominator retained in every row.

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import UnavailableGroup from "./UnavailableGroup.jsx";

const rows = [
  { key: "a", label: "easy · l1-lgbm-v1", detail: { n_neg: 221 } },
  { key: "b", label: "hard · l1-lgbm-v1", detail: { n_neg: 316 } },
];

describe("UnavailableGroup", () => {
  it("states the shared reason exactly once", () => {
    render(<UnavailableGroup reason="not resolvable at these negative counts" rows={rows} testid="g" />);
    expect(screen.getAllByText("not resolvable at these negative counts")).toHaveLength(1);
  });

  it("renders each row as a group with its denominator, and no filled bar element", () => {
    const { container } = render(<UnavailableGroup reason="r" rows={rows} testid="g" />);
    const grp = screen.getByTestId("g");
    const rowGroups = within(grp).getAllByRole("group");
    expect(rowGroups).toHaveLength(2);
    expect(rowGroups[0].textContent).toMatch(/n_neg=221/);
    expect(rowGroups[1].textContent).toMatch(/n_neg=316/);
    for (const el of container.querySelectorAll("*")) {
      const bg = el.style && el.style.background;
      const w = el.style && el.style.width;
      expect(w && w.endsWith("%")).toBeFalsy();
      expect(bg && bg.includes("--viz-series")).toBeFalsy();
    }
  });

  it("a row's accessible name never reads as a bare zero", () => {
    render(<UnavailableGroup reason="r" rows={rows} testid="g" />);
    for (const g of screen.getAllByRole("group")) {
      expect(g.getAttribute("aria-label")).not.toMatch(/\b0(\.0+)?\b/);
    }
  });
});
