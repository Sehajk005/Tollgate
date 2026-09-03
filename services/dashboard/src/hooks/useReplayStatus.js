import { useCallback, useEffect, useRef, useState } from "react";

// Remediation plan FIX-012 (AUDIT-002, 003, 013, 022) -- the AUTHORITATIVE
// replay state.
//
// Day 8 derived the strip's state from `events[0].replay`: the newest SSE
// attempt event's piggybacked snapshot. That works only while events are
// flowing, and every symptom the audit recorded happened precisely when they
// were not:
//
//   * a finished run showed `RUNNING (820/821)` forever, because the last
//     attempt event was published BEFORE `sent` was incremented and the
//     terminal transition published nothing at all;
//   * Stop showed the pre-stop snapshot;
//   * a crashed replay task was indistinguishable from a slow one;
//   * the tier selector was local `useState` and never reconciled with the
//     tier the backend was actually replaying.
//
// Three transports now carry the SAME snapshot, in increasing latency and
// decreasing fragility (plan §8):
//
//   1. control frame  -- pushed on the existing SSE bus; lowest latency,
//                        best-effort.
//   2. HTTP response  -- every start/stop/reset returns the snapshot.
//   3. poll           -- GET /v1/replay/status on mount and every 1000 ms
//                        while non-terminal. THIS is the path that survives a
//                        missed frame, a dead task and a page refresh.
//
// The reducer ignores any snapshot older than the one it holds
// (`updated_at_ms`), so an out-of-order frame can never move the UI backwards.

const POLL_INTERVAL_MS = 1000;

// Mirrors services/scorer/replay.py::TERMINAL_STATES. Terminal means the
// operator may act; anything else means a lifecycle transition owns the driver.
export const TERMINAL_STATES = new Set(["idle", "stopped", "finished", "failed"]);

export function isTerminal(status) {
  if (!status) return true;
  if (typeof status.terminal === "boolean") return status.terminal;
  return TERMINAL_STATES.has(status.state);
}

export function isBusy(status) {
  return !isTerminal(status);
}

export default function useReplayStatus() {
  const [replayStatus, setReplayStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const statusRef = useRef(null);

  // One reducer for all three transports. Stable identity (no deps) so the
  // event-stream hook can take it as a prop without re-subscribing.
  const applySnapshot = useCallback((snapshot) => {
    if (!snapshot || typeof snapshot.state !== "string") return;
    const current = statusRef.current;
    if (
      current &&
      typeof snapshot.updated_at_ms === "number" &&
      typeof current.updated_at_ms === "number" &&
      snapshot.updated_at_ms < current.updated_at_ms
    ) {
      return; // a late frame must never move the UI backwards
    }
    statusRef.current = snapshot;
    setReplayStatus(snapshot);
  }, []);

  const applyControlFrame = useCallback(
    (frame) => {
      if (frame && frame.type === "replay_status") applySnapshot(frame.replay);
    },
    [applySnapshot]
  );

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch("/v1/replay/status");
      if (!resp.ok) {
        setStatusError(`status ${resp.status}`);
        return null;
      }
      const body = await resp.json();
      setStatusError(null);
      applySnapshot(body);
      return body;
    } catch (err) {
      setStatusError("Cannot reach the scorer");
      return null;
    }
  }, [applySnapshot]);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    async function tick() {
      if (cancelled) return;
      const body = await refresh();
      if (cancelled) return;
      // Stop polling once the run is terminal: an always-on 1 Hz request for
      // the life of the tab is a real cost, and the control frame plus the
      // next operator action cover the terminal state.
      if (isTerminal(body)) return;
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer != null) clearTimeout(timer);
    };
    // Re-armed whenever the run leaves a terminal state, which is what makes a
    // Launch resume polling without an always-on timer.
  }, [refresh, replayStatus && replayStatus.run_id, replayStatus && replayStatus.state]);

  return {
    replayStatus,
    statusError,
    applyControlFrame,
    applySnapshot,
    refresh,
    busy: isBusy(replayStatus),
    terminal: isTerminal(replayStatus),
    runId: replayStatus ? replayStatus.run_id : null,
  };
}
