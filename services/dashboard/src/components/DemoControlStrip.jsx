import { useEffect, useRef, useState } from "react";
import { isTerminal } from "../hooks/useReplayStatus.js";

// Day 8, Step 3 -- the demo control strip (UIUX v2 SS6.12), pinned bottom,
// 1px top hairline. All four tiers, Launch / Stop / Reset, a speed selector,
// the pace-from-episode checkbox, and the permanent virtual-clock chip.
//
// Day 9 Plan Phase 3 -- J6 steps 7 & 8. FLOOD and KILL SCORER toggles are
// added, in a visually separated group labelled "DEMO", rendered only when
// VITE_TOLLGATE_DEMO_CONTROLS=1 (the Compose stack sets it). Both call
// /v1/demo/*, which 404s on the backend unless TOLLGATE_DEMO_CONTROLS=1 -- so
// in production the group is absent AND inert. Neither toggle fakes a state:
// FLOOD starts a real concurrent /v1/score load that drains the token bucket;
// KILL SCORER flips the in-scorer fault injector so /v1/score fails OPEN for
// real. The negative-control selector remains omitted.
//
// Remediation plan FIX-012 / FIX-022 / FIX-023 (AUDIT-013, 022, 024):
//
//   * TIER RECONCILIATION -- the selector was local `useState("easy")` and was
//     never reconciled with `replayStatus.tier`, so after a refresh mid-run it
//     read "easy" while the backend replayed "hard". It is now seeded from the
//     authoritative status and editable only while the run is terminal.
//   * CONTROL STATE -- `disabled` derives from the backend's terminal/busy
//     sets, not from a guess about whether events are still arriving.
//   * STYLING -- Stop, Reset and both selects were raw browser defaults next to
//     a styled Launch; the UI gate forbids raw browser-default primary controls.
//   * ERRORS -- `JSON.stringify(null)` produced the literal `HTTP 500: NULL`.
//     Now: `body.detail` when present, an operator-readable map otherwise.

const TIER_OPTIONS = [
  { value: "easy", label: "easy" },
  { value: "medium", label: "medium" },
  { value: "hard", label: "hard" },
  // Day 7 shipped the adaptive adversary, so `evasive` is a real tier and is
  // enabled -- UIUX v2 §6.12's v2 text lists all four with no caveat.
  { value: "evasive", label: "evasive" },
];

const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

// Day 9 Plan Phase 3 -- the demo-controls group renders only when this is set.
// The backend /v1/demo/* routes are independently gated by TOLLGATE_DEMO_CONTROLS.
const DEMO_CONTROLS = import.meta.env.VITE_TOLLGATE_DEMO_CONTROLS === "1";

// Remediation plan FIX-023 (AUDIT-022) -- App Flow §8's voice: say what
// happened and what to do, never a status code on its own.
const ERROR_COPY = {
  401: "API key rejected — check VITE_TOLLGATE_API_KEY",
  403: "API key rejected — check VITE_TOLLGATE_API_KEY",
  409: "A replay is already running",
  503: "Scorer unavailable",
};
// Statuses where our copy names the thing to change and the server's does not.
const ACTIONABLE_STATUSES = new Set([401, 403]);
const NETWORK_ERROR = "Cannot reach the scorer";
const ERROR_CLEAR_MS = 8000;

const controlBase = {
  border: "1px solid var(--tg-hairline-firm)",
  borderRadius: "var(--tg-radius-sm)",
  padding: "6px 12px",
  font: "inherit",
  lineHeight: "20px",
};

const selectStyle = {
  ...controlBase,
  background: "var(--tg-surface-3)",
  color: "var(--tg-text)",
  appearance: "none",
  paddingRight: 28,
  backgroundImage:
    "linear-gradient(45deg, transparent 50%, var(--tg-text-2) 50%), linear-gradient(135deg, var(--tg-text-2) 50%, transparent 50%)",
  backgroundPosition: "calc(100% - 15px) 9px, calc(100% - 10px) 9px",
  backgroundSize: "5px 5px, 5px 5px",
  backgroundRepeat: "no-repeat",
};

function buttonStyle(kind, disabled) {
  const primary = kind === "primary";
  return {
    ...controlBase,
    padding: "6px 16px",
    background: primary ? "var(--tg-primary)" : "transparent",
    color: primary ? "var(--tg-on-primary)" : "var(--tg-text-2)",
    border: primary ? "1px solid var(--tg-primary)" : "1px solid var(--tg-hairline-firm)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
  };
}

export default function DemoControlStrip({ replayStatus, onReplayStatus }) {
  const [tier, setTier] = useState("easy");
  const [speed, setSpeed] = useState(60);
  const [paceFromEpisode, setPaceFromEpisode] = useState(true);
  const [actionError, setActionError] = useState(null);
  const [clearedNote, setClearedNote] = useState(null);
  const [inFlight, setInFlight] = useState(false);
  const [flooding, setFlooding] = useState(false);
  const [faulting, setFaulting] = useState(false);
  const errorTimer = useRef(null);

  const terminal = isTerminal(replayStatus);
  const state = replayStatus ? replayStatus.state : "idle";
  const disabled = !terminal || inFlight;

  // Reconcile the selectors with the authoritative status. Local edits apply
  // only while the run is terminal; once a run owns the driver, the strip
  // displays what the BACKEND is replaying (AUDIT-013).
  useEffect(() => {
    if (!replayStatus) return;
    if (replayStatus.tier && !terminal) setTier(replayStatus.tier);
    if (typeof replayStatus.speed === "number" && !terminal) setSpeed(replayStatus.speed);
  }, [replayStatus, terminal]);

  useEffect(() => () => {
    if (errorTimer.current != null) clearTimeout(errorTimer.current);
  }, []);

  function raise(message) {
    setActionError(message);
    if (errorTimer.current != null) clearTimeout(errorTimer.current);
    errorTimer.current = setTimeout(() => setActionError(null), ERROR_CLEAR_MS);
  }

  async function callReplay(path, body) {
    setInFlight(true);
    try {
      const resp = await fetch(`/v1/replay/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tollgate-Key": API_KEY },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        // Prefer the server's own explanation, EXCEPT where the operator needs
        // to be told where to fix it: the scorer's 401 detail is "invalid or
        // missing API key", which is accurate and useless — it does not name
        // VITE_TOLLGATE_API_KEY. Never `JSON.stringify(null)`, which renders as
        // the literal string "null" (that was AUDIT-022's `HTTP 500: NULL`).
        const detail = data && typeof data.detail === "string" ? data.detail : null;
        const mapped = ERROR_COPY[resp.status];
        const message =
          mapped && ACTIONABLE_STATUSES.has(resp.status)
            ? mapped
            : detail || mapped || "The scorer rejected the request";
        raise(`${message} (HTTP ${resp.status})`);
        return;
      }
      setActionError(null);
      if (errorTimer.current != null) clearTimeout(errorTimer.current);

      // Surface a degraded reset honestly rather than reporting plain success:
      // "Reset completed" while Redis was never cleared is exactly the kind of
      // confident-but-wrong feedback this remediation exists to remove.
      if (data && data.degraded) {
        const failed = Object.entries(data.cleared || {})
          .filter(([key, value]) => value === false && !key.endsWith("_error"))
          .map(([key]) => key);
        setClearedNote(
          failed.length
            ? `Reset completed — not cleared: ${failed.join(", ")}`
            : "Reset completed with warnings"
        );
      } else if (data && data.cleared) {
        setClearedNote(null);
      }
      if (data && onReplayStatus) onReplayStatus(data);
    } catch (err) {
      raise(NETWORK_ERROR);
    } finally {
      setInFlight(false);
    }
  }

  // Day 9 Plan Phase 3 -- flip a real demo control. Same error handling as
  // callReplay (never JSON.stringify(null); server `detail` preferred).
  async function callDemo(path, want) {
    setInFlight(true);
    try {
      const resp = await fetch(`/v1/demo/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tollgate-Key": API_KEY },
        body: JSON.stringify({ enabled: want }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = data && typeof data.detail === "string" ? data.detail : null;
        const mapped = ERROR_COPY[resp.status];
        const message =
          mapped && ACTIONABLE_STATUSES.has(resp.status)
            ? mapped
            : detail || mapped || "The scorer rejected the request";
        raise(`${message} (HTTP ${resp.status})`);
        return false;
      }
      setActionError(null);
      if (errorTimer.current != null) clearTimeout(errorTimer.current);
      return true;
    } catch (err) {
      raise(NETWORK_ERROR);
      return false;
    } finally {
      setInFlight(false);
    }
  }

  const progress =
    replayStatus && replayStatus.total ? ` (${replayStatus.sent}/${replayStatus.total})` : "";
  const reason =
    replayStatus && replayStatus.error
      ? ` · ${replayStatus.error}`
      : replayStatus && replayStatus.stop_reason && state === "stopped"
      ? ` · ${replayStatus.stop_reason}`
      : "";

  return (
    <div
      className="tg-label"
      style={{
        position: "sticky",
        bottom: 0,
        display: "flex",
        alignItems: "center",
        gap: 12,
        minHeight: 56,
        padding: "0 24px",
        background: "var(--tg-surface-2)",
        borderTop: "1px solid var(--tg-hairline-firm)",
        color: "var(--tg-text-2)",
        flexWrap: "wrap",
      }}
    >
      <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        tier
        <select
          value={tier}
          onChange={(e) => setTier(e.target.value)}
          disabled={disabled}
          style={selectStyle}
          aria-label="attack tier"
        >
          {TIER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>
      <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        speed
        <select
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          disabled={disabled}
          style={selectStyle}
          aria-label="replay speed"
        >
          <option value={0}>0</option>
          <option value={1}>1</option>
          <option value={60}>60</option>
        </select>
      </label>
      <label
        style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: disabled ? "default" : "pointer" }}
        title="Score the pre-attack hours at full tilt and start pacing ~20 s of event time before the episode. Same events, same order, same decisions."
      >
        <input
          type="checkbox"
          checked={paceFromEpisode}
          onChange={(e) => setPaceFromEpisode(e.target.checked)}
          disabled={disabled}
        />
        pace from episode
      </label>
      <button
        onClick={() =>
          callReplay("start", {
            tier,
            seed: 42,
            speed,
            epoch_ms: 0,
            pace_from: paceFromEpisode ? "episode" : null,
          })
        }
        disabled={disabled}
        style={buttonStyle("primary", disabled)}
      >
        Launch
      </button>
      <button
        onClick={() => callReplay("stop")}
        disabled={terminal || inFlight}
        style={buttonStyle("secondary", terminal || inFlight)}
      >
        Stop
      </button>
      <button
        onClick={() => callReplay("reset")}
        disabled={inFlight}
        style={buttonStyle("secondary", inFlight)}
      >
        Reset
      </button>
      <span style={{ color: "var(--tg-text-mute)" }}>
        replay: {state}{progress}{reason}
      </span>
      <span className="tg-mono-caption" style={{ marginLeft: "auto", color: "var(--tg-text-mute)" }}>
        &times;60 VIRTUAL CLOCK &middot; WINDOWS PRESERVED &middot; TTD IN EVENT TIME
      </span>
      {clearedNote && (
        <span className="tg-mono-caption" style={{ color: "var(--tg-elevated)" }}>{clearedNote}</span>
      )}
      {actionError && (
        <span role="alert" style={{ color: "var(--tg-attack)" }}>{actionError}</span>
      )}

      {DEMO_CONTROLS && (
        <span
          data-testid="demo-controls"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            paddingLeft: 12,
            marginLeft: 4,
            borderLeft: "1px solid var(--tg-hairline-firm)",
          }}
        >
          <span className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
            DEMO
          </span>
          <button
            type="button"
            onClick={async () => {
              const want = !flooding;
              if (await callDemo("flood", want)) setFlooding(want);
            }}
            disabled={inFlight}
            aria-pressed={flooding}
            title="Start a real concurrent /v1/score load. Drains the merchant token bucket -> the rules-only shed rung."
            style={buttonStyle(flooding ? "primary" : "secondary", inFlight)}
          >
            {flooding ? "Flood: ON" : "Flood"}
          </button>
          <button
            type="button"
            onClick={async () => {
              const want = !faulting;
              if (await callDemo("fault", want)) setFaulting(want);
            }}
            disabled={inFlight}
            aria-pressed={faulting}
            title="Flip the in-scorer fault injector. /v1/score then fails OPEN (allow) for real."
            style={buttonStyle(faulting ? "primary" : "secondary", inFlight)}
          >
            {faulting ? "Kill scorer: ON" : "Kill scorer"}
          </button>
        </span>
      )}
    </div>
  );
}
