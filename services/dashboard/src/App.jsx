import { useEffect, useState } from "react";

// Day 2: D1 threat band + four counters + DC control strip.
// Source: Day-2 Plan §H -- "still one file, still no Tailwind / tokens /
// router / component library" (UIUX v2 §10 Day-2 row: "unstyled").
//
// The threat band renders `event.threat_state` verbatim -- it is never
// derived locally (Day-2 Plan §H failure mode: "Deriving the band locally
// instead of rendering event.threat_state"). Colour discipline: semantic
// colour is threat state only; replay chip and SSE-health copy stay
// monochrome; Launch is the single interactive accent; calm is grey, never
// green (Day-2 Plan §H).

const THREAT_LABELS = { calm: "CALM", elevated: "ELEVATED", under_attack: "UNDER ATTACK", resolved: "RESOLVED" };
const THREAT_COLORS = { calm: "#8a8a8a", elevated: "#c98a1f", under_attack: "#c23b3b", resolved: "#4a7fb5" };

function ThreatIcon({ state }) {
  const color = THREAT_COLORS[state] || THREAT_COLORS.calm;
  const base = { width: 26, height: 26, borderRadius: "50%", display: "inline-block", verticalAlign: "middle" };
  // Text label + shape, never colour alone (UIUX v2 §2.1 accessibility floor).
  if (state === "elevated") {
    return <span style={{ ...base, border: `3px solid ${color}`, background: `linear-gradient(90deg, ${color} 50%, transparent 50%)` }} />;
  }
  if (state === "under_attack") {
    return <span style={{ ...base, background: color, border: `3px solid ${color}` }} />;
  }
  if (state === "resolved") {
    return (
      <span style={{ ...base, background: color, border: `3px solid ${color}`, textAlign: "center", lineHeight: "20px", color: "#fff", fontSize: 13 }}>
        {"✓"}
      </span>
    );
  }
  return <span style={{ ...base, border: `3px solid ${color}` }} />; // calm: hollow ring
}

function Tile({ label, value, caption }) {
  return (
    <div style={{ border: "1px solid #ccc", padding: "0.6rem 0.8rem", minWidth: 140 }}>
      <div style={{ fontSize: "0.7rem", opacity: 0.65, letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: "0.65rem", opacity: 0.55 }}>{caption}</div>
    </div>
  );
}

const TIER_OPTIONS = [
  { value: "easy", label: "easy", enabled: true, note: null },
  { value: "hard", label: "hard", enabled: true, note: null },
  { value: "medium", label: "medium", enabled: true, note: null },
  { value: "evasive", label: "evasive", enabled: false, note: "Day 7" },
];

const FIVE_MIN_MS = 5 * 60 * 1000;
const IDLE_REPLAY = { state: "idle", tier: null, seed: null, speed: null, sent: 0, total: 0, episode_id: null, virtual_time_ms: 0 };
const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

export default function App() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [tier, setTier] = useState("easy");
  const [speed, setSpeed] = useState(60);
  const [replayStatus, setReplayStatus] = useState(IDLE_REPLAY);
  const [actionError, setActionError] = useState(null);

  useEffect(() => {
    const source = new EventSource("/v1/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      setEvents((prev) => [data, ...prev].slice(0, 100));
      if (data.replay) setReplayStatus(data.replay);
    };
    return () => source.close();
  }, []);

  const latest = events[0];
  const threatState = latest?.threat_state || "calm";
  const regime = latest?.regime || "in_control";

  const latestIngestTime = latest?.ingest_time;
  const attemptsIn5Min = latestIngestTime == null
    ? 0
    : events.filter((e) => latestIngestTime - e.ingest_time <= FIVE_MIN_MS).length;

  const cardsPerIpTop = events.length === 0
    ? null
    : events.reduce((max, e) => {
        const v = e.feature_snapshot?.distinct_cards_per_ip_5m;
        return typeof v === "number" && v > max ? v : max;
      }, 0);

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
      if (data) setReplayStatus(data);
    } catch (err) {
      setActionError(String(err));
    }
  }

  const isRunning = replayStatus.state === "running";

  return (
    <div style={{ fontFamily: "monospace", display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      {/* D1 threat band -- full width, top. Renders event.threat_state verbatim. */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "0.9rem 1rem", background: "#111", color: "#eee" }}>
        <ThreatIcon state={threatState} />
        <strong style={{ fontSize: "1.15rem", letterSpacing: "0.04em" }}>
          {THREAT_LABELS[threatState] || threatState.toUpperCase()}
        </strong>
        <span style={{ marginLeft: "1rem", opacity: 0.6 }}>regime: {regime}</span>
        <span style={{ marginLeft: "auto", opacity: 0.6 }}>SSE: {connected ? "connected" : "disconnected"}</span>
      </div>

      <div style={{ padding: "1rem", flex: 1 }}>
        <h1 style={{ fontSize: "1rem", margin: "0 0 0.75rem" }}>Tollgate -- Day 2</h1>

        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
          <Tile label="ATTEMPTS &middot; 5 MIN" value={attemptsIn5Min} caption="live" />
          <Tile label="DECLINE RATE" value="—" caption="needs /v1/outcome &middot; Day 7" />
          <Tile label="CARDS PER IP &middot; TOP" value={cardsPerIpTop == null ? "—" : cardsPerIpTop} caption="store-relative quantile &middot; Day 5" />
          <Tile label="ENFORCEMENT" value="— / 10" caption="blast-radius cap &middot; Day 6" />
        </div>

        <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "0.82rem" }}>
          {events.map((e, i) => (
            <li key={i} style={{ padding: "0.25rem 0", borderBottom: "1px solid #ddd" }}>
              <span style={{ opacity: 0.55 }}>[{e.replay?.tier ? e.replay.tier.toUpperCase() : "--"}]</span>{" "}
              {new Date(e.ingest_time).toISOString()} - {e.ip} - bin {e.bin} -{" "}
              <strong>{e.decision}</strong> ({(e.attempt_uid || "").slice(0, 8)})
              {e.rules_fired && e.rules_fired.length > 0 && (
                <span style={{ opacity: 0.6 }}> -- rules: {e.rules_fired.join(", ")}</span>
              )}
            </li>
          ))}
        </ul>
      </div>

      {/* DC strip -- pinned bottom; never hides, never dims (Day-2 Plan §H). */}
      <div style={{
        position: "sticky", bottom: 0, display: "flex", alignItems: "center", gap: "0.75rem",
        padding: "0.6rem 1rem", background: "#111", color: "#eee", flexWrap: "wrap",
      }}>
        <label>
          tier:{" "}
          <select value={tier} onChange={(evt) => setTier(evt.target.value)} disabled={isRunning}>
            {TIER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value} disabled={!opt.enabled} title={opt.note || undefined}>
                {opt.label}{opt.note ? ` (${opt.note})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          speed:{" "}
          <select value={speed} onChange={(evt) => setSpeed(Number(evt.target.value))} disabled={isRunning}>
            <option value={0}>0 (full tilt)</option>
            <option value={1}>1</option>
            <option value={60}>60</option>
          </select>
        </label>
        <button
          onClick={() => callReplay("start", { tier, seed: 42, speed, epoch_ms: 0 })}
          disabled={isRunning}
          style={{ background: "#2f6fed", color: "#fff", border: "none", padding: "0.4rem 0.9rem", cursor: isRunning ? "default" : "pointer" }}
        >
          Launch
        </button>
        <button onClick={() => callReplay("stop")}>Stop</button>
        <button onClick={() => callReplay("reset")}>Reset</button>
        <span style={{ opacity: 0.6 }}>
          replay: {replayStatus.state}
          {replayStatus.total ? ` (${replayStatus.sent}/${replayStatus.total})` : ""}
        </span>
        <span style={{ marginLeft: "auto", opacity: 0.65 }}>
          &times;60 VIRTUAL CLOCK &middot; WINDOWS PRESERVED &middot; TTD IN EVENT TIME
        </span>
        {actionError && <span style={{ color: "#e08080" }}>{actionError}</span>}
      </div>
    </div>
  );
}
