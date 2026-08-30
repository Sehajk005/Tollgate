import { useEffect, useMemo, useState } from "react";

import useEventStream from "./hooks/useEventStream.js";
import StreamRail from "./components/StreamRail.jsx";
import ThreatBand from "./components/ThreatBand.jsx";
import SystemBanner from "./components/SystemBanner.jsx";
import DemoControlStrip from "./components/DemoControlStrip.jsx";
import D1Live from "./screens/D1Live.jsx";
import D3Incident from "./screens/D3Incident.jsx";
import D6Metrics from "./screens/D6Metrics.jsx";

// Day 8, Step 3 -- the D0 shell (App Flow SS5 D0). Three routes, linear nav,
// no router (`useState('live'|'incident'|'metrics')`). The Stream Rail sits on
// EVERY screen under the nav; the threat band and the system-state banner
// stack under the rail (banner BELOW the band, never above -- SS6.10). The DC
// strip is pinned bottom.
//
// Nav reconciliation (App Flow SS2 cut D2 / SS5 "navigate D1 -> D3 directly"):
// "Incidents" routes straight to D3 for the newest LIVE incident, and renders
// the SS8 empty state when there is none. No D2 list is built.

const WINDOW_MS = 60_000;

const NAV = [
  { id: "live", label: "Live" },
  { id: "incident", label: "Incidents" },
  { id: "metrics", label: "Metrics" },
];

export default function App() {
  const { events, connectionMode, lastEventAt } = useEventStream();
  const [route, setRoute] = useState("live");
  const [replayStatus, setReplayStatus] = useState(null);

  const latest = events[0];
  const threatState = latest?.threat_state || "calm";
  const regime = latest?.regime || "in_control";
  const enforcement = latest?.enforcement || null;
  const latestIngest = latest?.ingest_time ?? null;

  useEffect(() => {
    if (latest?.replay) setReplayStatus(latest.replay);
  }, [latest]);

  // --- system-banner inputs, all in event time -------------------------
  const shedInLast60 = useMemo(() => {
    if (latestIngest == null) return 0;
    return events.filter(
      (e) => e.availability?.shed && latestIngest - e.ingest_time <= WINDOW_MS
    ).length;
  }, [events, latestIngest]);

  const failOpenAgoS = useMemo(() => {
    if (latestIngest == null) return null;
    const recent = events.filter(
      (e) => e.availability?.fail_open && latestIngest - e.ingest_time <= WINDOW_MS
    );
    if (recent.length === 0) return null;
    const earliest = recent.reduce((a, b) => (a.ingest_time <= b.ingest_time ? a : b));
    return Math.max(0, Math.round((latestIngest - earliest.ingest_time) / 1000));
  }, [events, latestIngest]);

  // --- newest live incident (drives the Incidents nav item) -----------
  const liveIncidentId = useMemo(() => {
    for (const e of events) {
      const inc = e.incident;
      if (inc && inc.incident_id && inc.state !== "CLOSED") return inc.incident_id;
    }
    return null;
  }, [events]);

  const stale = connectionMode !== "live";
  const staleAgo = lastEventAt ? Math.round((Date.now() - lastEventAt) / 1000) : null;

  return (
    <div className="tg-app" style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      {/* nav */}
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
        <strong className="tg-body-strong" style={{ letterSpacing: "0.14em" }}>TOLLGATE</strong>
        <div style={{ display: "flex", gap: 4 }}>
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => setRoute(n.id)}
              className="tg-body-strong"
              style={{
                background: "transparent",
                border: "none",
                padding: "6px 10px",
                cursor: "pointer",
                color: route === n.id ? "var(--tg-primary)" : "var(--tg-text-2)",
                borderBottom: route === n.id ? "2px solid var(--tg-primary)" : "2px solid transparent",
              }}
            >
              {n.label}
            </button>
          ))}
        </div>
        <span className="tg-mono-caption" style={{ marginLeft: "auto", color: "var(--tg-text-mute)" }}>
          SSE: {connectionMode}
          {stale && staleAgo != null ? ` · last event ${staleAgo}s ago` : ""}
        </span>
      </nav>

      {/* the signature -- on every screen */}
      <StreamRail events={events} />

      {/* the store's threat level outranks Tollgate's health, always */}
      <ThreatBand threatState={threatState} regime={regime} />
      <SystemBanner
        enforcement={enforcement}
        shedInLast60={shedInLast60}
        failOpenAgoS={failOpenAgoS}
      />

      <main style={{ flex: 1 }}>
        {route === "live" && <D1Live events={events} enforcement={enforcement} />}
        {route === "metrics" && <D6Metrics />}
        {route === "incident" && (
          <D3Incident
            incidentId={liveIncidentId}
            sseIncident={latest?.incident || null}
          />
        )}
      </main>

      <DemoControlStrip replayStatus={replayStatus} onReplayStatus={setReplayStatus} />
    </div>
  );
}
