import { useEffect, useRef, useState } from "react";

// Day 8, Step 3 -- the resilient live connection (App Flow SS7: "Native
// reconnect; 5 s polling fallback"). Never surfaces an error page: on a drop
// the dashboard degrades to last-known-good and keeps polling until SSE
// recovers (App Flow SS7 "Degrade to last-known-good with a staleness
// timestamp, never an error page").
//
//   live        -- EventSource open, events arriving
//   polling     -- EventSource errored; GET /v1/stream/recent every 5000 ms,
//                  and a fresh EventSource attempted on each poll
//   reconnecting-- a fresh EventSource has been opened but not yet confirmed
//
// The 5000 ms poll is installed on `error` and cleared on `open`; it targets
// /v1/stream/recent?after=<last attempt_uid> so no event between the drop and
// the reconnect is lost. Pinned by tests/acceptance/test_sse_fallback.py.

const POLL_INTERVAL_MS = 5000;
const MAX_EVENTS = 200;

export default function useEventStream() {
  const [events, setEvents] = useState([]);
  const [connectionMode, setConnectionMode] = useState("reconnecting");
  const [lastEventAt, setLastEventAt] = useState(null);

  const lastUidRef = useRef(null);
  const sourceRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    function ingest(list) {
      if (cancelled || !list || list.length === 0) return;
      setEvents((prev) => [...list].reverse().concat(prev).slice(0, MAX_EVENTS));
      const newest = list[list.length - 1];
      if (newest && newest.attempt_uid) lastUidRef.current = newest.attempt_uid;
      setLastEventAt(Date.now());
    }

    function stopPolling() {
      if (pollRef.current != null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }

    async function pollOnce() {
      try {
        const after = lastUidRef.current;
        const url = after
          ? `/v1/stream/recent?after=${encodeURIComponent(after)}`
          : "/v1/stream/recent";
        const resp = await fetch(url);
        if (resp.ok) {
          const body = await resp.json();
          ingest(body.events || []);
        }
      } catch (err) {
        // stay in polling mode -- never an error page
      }
      openStream(); // also attempt a fresh SSE connection on every poll
    }

    function startPolling() {
      if (pollRef.current != null) return;
      setConnectionMode("polling");
      pollRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
      pollOnce();
    }

    function openStream() {
      if (sourceRef.current != null) return;
      const es = new EventSource("/v1/stream");
      sourceRef.current = es;
      setConnectionMode((m) => (m === "polling" ? "polling" : "reconnecting"));

      es.onopen = () => {
        if (cancelled) return;
        stopPolling();
        setConnectionMode("live");
      };
      es.onmessage = (evt) => {
        if (cancelled) return;
        try {
          ingest([JSON.parse(evt.data)]);
        } catch (err) {
          /* ignore a malformed frame */
        }
      };
      es.onerror = () => {
        es.close();
        sourceRef.current = null;
        if (cancelled) return;
        startPolling();
      };
    }

    openStream();

    return () => {
      cancelled = true;
      stopPolling();
      if (sourceRef.current != null) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    };
  }, []);

  return { events, connectionMode, lastEventAt };
}
