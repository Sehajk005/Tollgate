// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.1/§19.2 / §23.6
// FE-T-ROUTE-01..06 + FE-T-ARCH-01..04. The Metrics route opens ZERO live
// subscriptions; navigating away from a live route closes the EventSource.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";

import App from "../App.jsx";

let esInstances;

class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.close = vi.fn();
    esInstances.push(this);
  }
  addEventListener() {}
  removeEventListener() {}
}

beforeEach(() => {
  esInstances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
        text: () => Promise.resolve("[]"),
      }),
    ),
  );
  window.location.hash = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.location.hash = "";
});

describe("FE-T-ROUTE: the Metrics route is addressable", () => {
  it("#/metrics renders D6 on first paint, with aria-current on the Metrics nav", () => {
    window.location.hash = "#/metrics";
    render(<App />);
    expect(
      screen.getByRole("heading", { level: 1, name: /Metrics & Evaluation/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Metrics" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Live" })).not.toHaveAttribute("aria-current");
    expect(document.title).toBe("Tollgate — Metrics & Evaluation");
  });
});

describe("FE-T-ARCH: no live subscription on Metrics", () => {
  it("constructs ZERO EventSource instances on #/metrics", () => {
    window.location.hash = "#/metrics";
    render(<App />);
    expect(esInstances).toHaveLength(0);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("the Demo Control Strip is absent on Metrics and present on Live", () => {
    window.location.hash = "#/metrics";
    const { unmount } = render(<App />);
    expect(screen.queryByText(/Launch/)).toBeNull();
    unmount();

    window.location.hash = "#/live";
    render(<App />);
    expect(esInstances.length).toBeGreaterThan(0);
    expect(screen.getByText(/Launch/)).toBeInTheDocument();
  });

  it("navigating live -> metrics unmounts LiveShell and closes the EventSource", () => {
    window.location.hash = "#/live";
    const { rerender } = render(<App />);
    const es = esInstances[0];
    expect(es).toBeDefined();

    act(() => {
      window.location.hash = "#/metrics";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    rerender(<App />);
    expect(es.close).toHaveBeenCalled();
  });
});
