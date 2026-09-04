// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.2 FIX-M-031.
//
// The three live subscriptions (useReplayStatus / useEventStream / useIncidents)
// and every event-derived surface (SSE status, Stream Rail, Threat Band, System
// Banner, Demo Control Strip) live HERE, mounted ONLY for the `live` and
// `incident` routes. On `#/metrics` this component is not rendered, so React
// unmounts it and the hooks' cleanup closes the EventSource and clears the poll
// timer -- "Static render. No live computation on stage." at the screen level.

import { useMemo } from "react";

import useEventStream from "../hooks/useEventStream.js";
import useReplayStatus from "../hooks/useReplayStatus.js";
import useIncidents from "../hooks/useIncidents.js";
import StreamRail from "./StreamRail.jsx";
import ThreatBand from "./ThreatBand.jsx";
import SystemBanner from "./SystemBanner.jsx";
import DemoControlStrip from "./DemoControlStrip.jsx";
import D1Live from "../screens/D1Live.jsx";
import D3Incident from "../screens/D3Incident.jsx";

const WINDOW_MS = 60_000;

export default function LiveShell({ route }) {
  const { replayStatus, applyControlFrame, applySnapshot, runId } = useReplayStatus();
  const { events, connectionMode, lastEventAt } = useEventStream(runId, applyControlFrame);
  const { newestIncidentId, loading: incidentsLoading, error: incidentsError } = useIncidents(
    runId,
    events,
  );

  const latest = events[0];
  const threatState = latest?.threat_state || "calm";
  const regime = latest?.regime || "in_control";
  const enforcement = latest?.enforcement || null;
  const latestIngest = latest?.ingest_time ?? null;
  const stale = connectionMode !== "live";
  const staleAgo = lastEventAt ? Math.round((Date.now() - lastEventAt) / 1000) : null;

  const shedInLast60 = useMemo(() => {
    if (latestIngest == null) return 0;
    return events.filter(
      (e) => e.availability?.shed && latestIngest - e.ingest_time <= WINDOW_MS,
    ).length;
  }, [events, latestIngest]);

  const failOpenAgoS = useMemo(() => {
    if (latestIngest == null) return null;
    const recent = events.filter(
      (e) => e.availability?.fail_open && latestIngest - e.ingest_time <= WINDOW_MS,
    );
    if (recent.length === 0) return null;
    const earliest = recent.reduce((a, b) => (a.ingest_time <= b.ingest_time ? a : b));
    return Math.max(0, Math.round((latestIngest - earliest.ingest_time) / 1000));
  }, [events, latestIngest]);

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          padding: "0 24px",
          background: "var(--tg-surface-1)",
        }}
      >
        <span className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
          SSE: {connectionMode}
          {stale && staleAgo != null ? ` · last event ${staleAgo}s ago` : ""}
        </span>
      </div>

      <StreamRail events={events} />
      <ThreatBand threatState={threatState} regime={regime} />
      <SystemBanner
        enforcement={enforcement}
        shedInLast60={shedInLast60}
        failOpenAgoS={failOpenAgoS}
      />

      <main style={{ flex: 1 }}>
        {route === "live" && <D1Live events={events} enforcement={enforcement} latest={latest} />}
        {route === "incident" && (
          <D3Incident
            incidentId={newestIncidentId}
            listLoading={incidentsLoading}
            listError={incidentsError}
          />
        )}
      </main>

      <DemoControlStrip replayStatus={replayStatus} onReplayStatus={applySnapshot} />
    </>
  );
}
