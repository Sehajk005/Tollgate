import { useEffect, useState } from "react";

// Day 1 walking skeleton dashboard: a bare event ticker over SSE.
// Source: Implementation Plan v2.1 Day 1 -- "D1 event ticker over SSE" with
// the explicit exclusion list (no Tailwind, no tokens, no router, no
// component library, no state-management framework, no animation).
export default function App() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource("/v1/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      setEvents((prev) => [data, ...prev].slice(0, 100));
    };
    return () => source.close();
  }, []);

  return (
    <div style={{ fontFamily: "monospace", padding: "1rem" }}>
      <h1>Tollgate -- Day 1 Ticker</h1>
      <p>SSE: {connected ? "connected" : "disconnected"}</p>
      <ul>
        {events.map((e, i) => (
          <li key={i}>
            {new Date(e.ingest_time).toISOString()} - {e.ip} - bin {e.bin} -{" "}
            <strong>{e.decision}</strong> ({e.attempt_uid})
          </li>
        ))}
      </ul>
    </div>
  );
}
