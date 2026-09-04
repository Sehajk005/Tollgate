import { useEffect, useRef, useState } from "react";

// Day 8, Step 3 -- the resilient live connection (App Flow SS7: "Native
// reconnect; 5 s polling fallback"). Never surfaces an error page: on a drop
// the dashboard degrades to last-known-good and keeps polling until SSE
// recovers (App Flow SS7 "Degrade to last-known-good with a staleness
// timestamp, never an error page").
//
//   connecting  -- the first EventSource has been opened, not yet confirmed
//   live        -- EventSource open, events arriving
//   polling     -- EventSource errored; GET /v1/stream/recent every 5000 ms,
//                  and a fresh EventSource attempted on each poll
//   reconnecting-- a fresh EventSource has been opened after a real drop
//
// Remediation plan FIX-013 (AUDIT-009) -- BACK-FILL ON MOUNT. This hook used
// to mount with `events: []` and reach `/v1/stream/recent` only from the SSE
// ERROR path, so opening the dashboard mid-attack showed a calm, empty screen
// until the next event happened to arrive. The back-fill now runs on every
// mount, CONCURRENTLY with opening the stream:
//
//   * opening after the fetch would drop everything published in between;
//   * fetching after the open would duplicate it.
//
// So live frames are QUEUED until the back-fill resolves, then merged through a
// bounded seen-uid set. Neither a gap nor a duplicate is possible at the seam.
//
// Remediation plan FIX-014 (AUDIT-015) -- ONE RESET SIGNAL. `runId` is the
// backend's `run_id`. When it changes -- including to null on Reset -- every
// piece of event-derived state here is reinitialised and the back-fill re-runs.
// No component clears itself, so no surface can be forgotten.
//
// Remediation plan FIX-012 -- lifecycle control frames are routed to
// `onControlFrame` instead of being mistaken for attempts.

const POLL_INTERVAL_MS = 5000;
const MAX_EVENTS = 200;

function isControlFrame(frame) {
  return Boolean(frame) && frame.type === "replay_status";
}

export default function useEventStream(runId = null, onControlFrame = null) {
  const [events, setEvents] = useState([]);
  const [connectionMode, setConnectionMode] = useState("connecting");
  const [lastEventAt, setLastEventAt] = useState(null);

  const lastUidRef = useRef(null);
  const sourceRef = useRef(null);
  const pollRef = useRef(null);
  const seenRef = useRef(new Set());
  const controlRef = useRef(onControlFrame);
  controlRef.current = onControlFrame;

  useEffect(() => {
    let cancelled = false;
    // Live frames that arrive before the back-fill resolves wait here, so the
    // merge can order them after it without losing or repeating any.
    let backfillPending = true;
    let queued = [];

    // Reinitialise EVERY piece of event-derived state on a run boundary.
    lastUidRef.current = null;
    seenRef.current = new Set();
    setEvents([]);
    setLastEventAt(null);

    function markSeen(uid) {
      const seen = seenRef.current;
      seen.add(uid);
      // Sized at 2x the buffer: the buffer is the only thing that can produce
      // a repeat, so anything older than that cannot come back.
      if (seen.size > MAX_EVENTS * 2) {
        const excess = seen.size - MAX_EVENTS * 2;
        let dropped = 0;
        for (const key of seen) {
          seen.delete(key);
          if (++dropped >= excess) break;
        }
      }
    }

    function ingest(list) {
      if (cancelled || !list || list.length === 0) return;
      const attempts = [];
      for (const frame of list) {
        if (isControlFrame(frame)) {
          if (controlRef.current) controlRef.current(frame);
          continue;
        }
        const uid = frame && frame.attempt_uid;
        if (uid) {
          if (seenRef.current.has(uid)) continue;
          markSeen(uid);
        }
        attempts.push(frame);
      }
      if (attempts.length === 0) return;
      setEvents((prev) => [...attempts].reverse().concat(prev).slice(0, MAX_EVENTS));
      const newest = attempts[attempts.length - 1];
      if (newest && newest.attempt_uid) lastUidRef.current = newest.attempt_uid;
      setLastEventAt(Date.now());
    }

    function accept(list) {
      if (backfillPending) {
        queued.push(...list);
        return;
      }
      ingest(list);
    }

    function stopPolling() {
      if (pollRef.current != null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }

    async function fetchRecent() {
      const after = lastUidRef.current;
      const url = after
        ? `/v1/stream/recent?after=${encodeURIComponent(after)}`
        : "/v1/stream/recent";
      const resp = await fetch(url);
      if (!resp.ok) return [];
      const body = await resp.json();
      return body.events || [];
    }

    async function pollOnce() {
      try {
        ingest(await fetchRecent());
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
      setConnectionMode((m) => (m === "polling" ? "polling" : m === "connecting" ? "connecting" : "reconnecting"));

      es.onopen = () => {
        if (cancelled) return;
        stopPolling();
        setConnectionMode("live");
        // On a reconnect, close the gap the drop opened before trusting live
        // frames again.
        if (!backfillPending && lastUidRef.current) {
          fetchRecent().then(ingest).catch(() => {});
        }
      };
      es.onmessage = (evt) => {
        if (cancelled) return;
        try {
          accept([JSON.parse(evt.data)]);
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

    // Concurrently: open the stream AND back-fill. See the header comment for
    // why neither order alone is correct.
    openStream();
    fetchRecent()
      .then((backfill) => {
        if (cancelled) return;
        backfillPending = false;
        const merged = [...backfill, ...queued];
        queued = [];
        ingest(merged);
      })
      .catch(() => {
        if (cancelled) return;
        backfillPending = false;
        const merged = queued;
        queued = [];
        ingest(merged);
      });

    return () => {
      cancelled = true;
      stopPolling();
      if (sourceRef.current != null) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    };
  }, [runId]);

  return { events, connectionMode, lastEventAt };
}
