// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.1 FIX-M-018 / M-024.
//
// A ~30-line hash router. No router dependency (UIUX §10's Day-1 exclusion
// list names "no router"; there are THREE routes, no params, no nesting, no
// guards). Hash routing needs no dev-server or production rewrite rules, which
// matters because `vite` serves the demo and history-API routing would 404 on
// a direct load.
//
//   reads location.hash -> normalises to a known id (unknown -> "live")
//   subscribes to "hashchange"
//   returns [route, navigate]  (navigate sets location.hash)
//   a useEffect sets document.title from ROUTE_TITLES

import { useCallback, useEffect, useState } from "react";

export const ROUTES = ["live", "incident", "metrics"];

export const ROUTE_TITLES = {
  live: "Tollgate — Live Monitor",
  incident: "Tollgate — Incident",
  metrics: "Tollgate — Metrics & Evaluation",
};

export function routeFromHash(hash) {
  const id = String(hash || "")
    .replace(/^#\/?/, "")
    .split(/[/?]/)[0];
  return ROUTES.includes(id) ? id : "live";
}

export default function useHashRoute() {
  const [route, setRoute] = useState(() =>
    routeFromHash(typeof window !== "undefined" ? window.location.hash : ""),
  );

  useEffect(() => {
    const onChange = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    onChange(); // reconcile in case the hash changed before this effect ran
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.title = ROUTE_TITLES[route] || ROUTE_TITLES.live;
    }
  }, [route]);

  const navigate = useCallback((id) => {
    const next = ROUTES.includes(id) ? id : "live";
    if (typeof window === "undefined") return;
    window.location.hash = `/${next}`;
    // Real browsers fire "hashchange" on a hash assignment; some test DOMs do
    // not. Dispatching it ourselves keeps the listener the single source of
    // truth (a redundant real event is idempotent -- setRoute to the same id).
    window.dispatchEvent(new Event("hashchange"));
  }, []);

  return [route, navigate];
}
