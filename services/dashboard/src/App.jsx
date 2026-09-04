import useHashRoute, { ROUTES } from "./hooks/useHashRoute.js";
import StreamRail from "./components/StreamRail.jsx";
import LiveShell from "./components/LiveShell.jsx";
import D6Metrics from "./screens/D6Metrics.jsx";
import MetricsErrorBoundary from "./components/MetricsErrorBoundary.jsx";

// Day 8, Step 3 -- the D0 shell (App Flow §5 D0). Three routes.
//
// Remediation (METRICS-REMEDIATION-PLAN-2026-09-02.md §19):
//   * FIX-M-018 -- hash routing (`#/live` `#/incident` `#/metrics`), so the
//     evaluation page is addressable, survives a refresh, and back/forward
//     work. `document.title` follows the route; `aria-current="page"` on the
//     active nav item.
//   * FIX-M-031 -- the live subscriptions + every event-derived surface live
//     in <LiveShell>, mounted ONLY for `live`/`incident`. On `#/metrics` no
//     EventSource is opened and no poll timer is armed; the Demo Control Strip
//     is hidden (a live control on a static report is worse than the spec
//     deviation). The Stream Rail renders as an empty signature band.

const NAV = [
  { id: "live", label: "Live" },
  { id: "incident", label: "Incidents" },
  { id: "metrics", label: "Metrics" },
];

export default function App() {
  const [route, navigate] = useHashRoute();
  const known = ROUTES.includes(route) ? route : "live";

  return (
    <div className="tg-app" style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <nav
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "12px 24px",
          background: "var(--tg-surface-1)",
          borderBottom: "1px solid var(--tg-hairline)",
        }}
      >
        <strong className="tg-body-strong" style={{ letterSpacing: "0.14em" }}>
          TOLLGATE
        </strong>
        <div style={{ display: "flex", gap: 4 }}>
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => navigate(n.id)}
              aria-current={known === n.id ? "page" : undefined}
              className="tg-body-strong"
              style={{
                background: "transparent",
                border: "none",
                padding: "6px 10px",
                cursor: "pointer",
                color: known === n.id ? "var(--tg-primary)" : "var(--tg-text-2)",
                borderBottom:
                  known === n.id ? "2px solid var(--tg-primary)" : "2px solid transparent",
              }}
            >
              {n.label}
            </button>
          ))}
        </div>
      </nav>

      {known === "metrics" ? (
        <>
          {/* the signature band -- present for visual continuity, no data path */}
          <StreamRail events={[]} />
          <main style={{ flex: 1 }}>
            <MetricsErrorBoundary>
              <D6Metrics />
            </MetricsErrorBoundary>
          </main>
        </>
      ) : (
        <LiveShell route={known} />
      )}
    </div>
  );
}
