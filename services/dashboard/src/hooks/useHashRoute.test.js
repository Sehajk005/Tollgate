// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.1 / §23.6 FE-T-ROUTE-01..06.

import { afterEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import useHashRoute, { ROUTE_TITLES, routeFromHash } from "./useHashRoute.js";

afterEach(() => {
  window.location.hash = "";
});

describe("routeFromHash", () => {
  it("maps known hashes and falls back to live for anything else", () => {
    expect(routeFromHash("#/metrics")).toBe("metrics");
    expect(routeFromHash("#/incident")).toBe("incident");
    expect(routeFromHash("#/live")).toBe("live");
    expect(routeFromHash("")).toBe("live");
    expect(routeFromHash("#/nonsense")).toBe("live");
    expect(routeFromHash("#garbage")).toBe("live");
  });
});

describe("useHashRoute", () => {
  it("reads the initial hash and sets the document title", () => {
    window.location.hash = "#/metrics";
    const { result } = renderHook(() => useHashRoute());
    expect(result.current[0]).toBe("metrics");
    expect(document.title).toBe(ROUTE_TITLES.metrics);
  });

  it("navigate() changes the hash, the route, and the title", () => {
    window.location.hash = "#/live";
    const { result } = renderHook(() => useHashRoute());
    expect(result.current[0]).toBe("live");
    act(() => result.current[1]("metrics"));
    expect(window.location.hash).toBe("#/metrics");
    expect(result.current[0]).toBe("metrics");
    expect(document.title).toBe(ROUTE_TITLES.metrics);
  });

  it("responds to an external hashchange without throwing", () => {
    const { result } = renderHook(() => useHashRoute());
    act(() => {
      window.location.hash = "#/incident";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current[0]).toBe("incident");
  });

  it("an unknown hash resolves to live", () => {
    window.location.hash = "#/nope";
    const { result } = renderHook(() => useHashRoute());
    expect(result.current[0]).toBe("live");
  });
});
