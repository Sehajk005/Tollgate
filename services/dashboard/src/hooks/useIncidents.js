import { useCallback, useEffect, useRef, useState } from "react";

// Remediation plan FIX-015 (AUDIT-008) -- INCIDENTS COME FROM THE API.
//
// `App.jsx` used to pick the newest live incident by scanning the SSE event
// array. That array holds at most 200 events, so once an attack pushed the
// incident-opening event out of the buffer the Incidents nav item routed to the
// empty state -- while the incident was still open and `GET /v1/incidents`
// would have returned it. The audit could not reach D3 at all, so Confirm and
// Resolve went entirely untested.
//
// The API is now the source and SSE is only an accelerator: a fetch on mount,
// a fetch on every run boundary, and a debounced fetch when a live event
// mentions an incident_id we have not seen. Never an interval.
//
// Loading, empty and error are DISTINCT states. "No incidents" must never be
// what the operator sees when the fetch failed.

const DEBOUNCE_MS = 500;
const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

export default function useIncidents(runId = null, events = []) {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const seenIncidentIds = useRef(new Set());
  const debounceRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/v1/incidents?state=live", {
        headers: { "X-Tollgate-Key": API_KEY },
      });
      if (!resp.ok) {
        setError(
          resp.status === 401
            ? "API key rejected — check VITE_TOLLGATE_API_KEY"
            : `Could not load incidents (HTTP ${resp.status})`
        );
        setLoading(false);
        return;
      }
      const body = await resp.json();
      // Newest first by opened_at, so "the newest live incident" is position 0
      // and the nav never has to guess.
      const rows = (body.incidents || [])
        .slice()
        .sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0));
      setIncidents(rows);
      setError(null);
      setLoading(false);
    } catch (err) {
      setError("Cannot reach the scorer");
      setLoading(false);
    }
  }, []);

  // Mount, and every run boundary: a new run_id means the previous run's
  // incidents are gone and this one's have not been fetched yet.
  useEffect(() => {
    seenIncidentIds.current = new Set();
    setLoading(true);
    load();
  }, [load, runId]);

  // SSE as an accelerator only -- change-triggered and debounced, never polled.
  useEffect(() => {
    let unseen = false;
    for (const e of events) {
      const id = e && e.incident && e.incident.incident_id;
      if (id && !seenIncidentIds.current.has(id)) {
        seenIncidentIds.current.add(id);
        unseen = true;
      }
    }
    if (!unseen) return undefined;
    if (debounceRef.current != null) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      load();
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current != null) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [events, load]);

  return {
    incidents,
    newestIncidentId: incidents.length > 0 ? incidents[0].incident_id : null,
    loading,
    error,
    reload: load,
  };
}
