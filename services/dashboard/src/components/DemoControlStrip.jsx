import { useState } from "react";

// Day 8, Step 3 -- the demo control strip (UIUX v2 SS6.12), pinned bottom,
// 1px top hairline. The Day-2 subset only (Decisions.md decision 36): tier
// selector (all four shown; `evasive` disabled), Launch / Stop / Reset, a
// speed selector, and the permanent virtual-clock chip. The negative-control
// selector and flood / kill-scorer toggles remain omitted (Day 9).
//
// Behaviour is UNCHANGED from Day 2's App.jsx -- `callReplay` and the control
// block moved here verbatim; only the styling is new.

const TIER_OPTIONS = [
  { value: "easy", label: "easy", enabled: true, note: null },
  { value: "medium", label: "medium", enabled: true, note: null },
  { value: "hard", label: "hard", enabled: true, note: null },
  { value: "evasive", label: "evasive", enabled: false, note: "Day 7" },
];

const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

export default function DemoControlStrip({ replayStatus, onReplayStatus }) {
  const [tier, setTier] = useState("easy");
  const [speed, setSpeed] = useState(60);
  const [actionError, setActionError] = useState(null);

  const isRunning = replayStatus && replayStatus.state === "running";

  async function callReplay(path, body) {
    setActionError(null);
    try {
      const resp = await fetch(`/v1/replay/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tollgate-Key": API_KEY },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        setActionError(`HTTP ${resp.status}: ${JSON.stringify(data)}`);
        return;
      }
      if (data && onReplayStatus) onReplayStatus(data);
    } catch (err) {
      setActionError(String(err));
    }
  }

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
      <label>
        tier{" "}
        <select value={tier} onChange={(e) => setTier(e.target.value)} disabled={isRunning}>
          {TIER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value} disabled={!o.enabled}>
              {o.label}{o.note ? ` (${o.note})` : ""}
            </option>
          ))}
        </select>
      </label>
      <label>
        speed{" "}
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} disabled={isRunning}>
          <option value={0}>0</option>
          <option value={1}>1</option>
          <option value={60}>60</option>
        </select>
      </label>
      <button
        onClick={() => callReplay("start", { tier, seed: 42, speed, epoch_ms: 0 })}
        disabled={isRunning}
        style={{
          background: "var(--tg-primary)",
          color: "var(--tg-on-primary)",
          border: "none",
          borderRadius: "var(--tg-radius-sm)",
          padding: "6px 16px",
          cursor: isRunning ? "default" : "pointer",
        }}
      >
        Launch
      </button>
      <button onClick={() => callReplay("stop")}>Stop</button>
      <button onClick={() => callReplay("reset")}>Reset</button>
      <span style={{ color: "var(--tg-text-mute)" }}>
        replay: {replayStatus ? replayStatus.state : "idle"}
        {replayStatus && replayStatus.total ? ` (${replayStatus.sent}/${replayStatus.total})` : ""}
      </span>
      <span className="tg-mono-caption" style={{ marginLeft: "auto", color: "var(--tg-text-mute)" }}>
        &times;60 VIRTUAL CLOCK &middot; WINDOWS PRESERVED &middot; TTD IN EVENT TIME
      </span>
      {actionError && <span style={{ color: "var(--tg-attack)" }}>{actionError}</span>}
    </div>
  );
}
