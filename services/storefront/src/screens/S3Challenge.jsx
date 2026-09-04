import { useState } from "react";

// Day 8, Step 8 -- S3 Challenge interlude. A Turnstile-style checkbox. This
// is the AUTOMATIC CEILING (Threat Model SS4/P1), so it is the tier the demo
// actually exercises: a legitimate customer ticks one box and continues; a
// script does not. Passed -> S5, failed -> S6.

export default function S3Challenge({ onPass, onFail }) {
  const [checked, setChecked] = useState(false);
  return (
    <div style={{ maxWidth: 420, margin: "0 auto", padding: "120px 24px", textAlign: "center" }}>
      <h1 style={{ fontSize: 20, fontWeight: 400 }}>Quick check</h1>
      <p style={{ color: "var(--st-ink-2)", fontSize: 14 }}>
        Confirm you are a person to finish your order.
      </p>
      <label
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          border: "1px solid var(--st-hairline)",
          borderRadius: 8,
          padding: "14px 20px",
          margin: "16px 0",
          cursor: "pointer",
        }}
      >
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <span style={{ fontSize: 14 }}>I am not a robot</span>
      </label>
      <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
        <button
          onClick={onPass}
          disabled={!checked}
          style={{
            background: "var(--st-accent)",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "10px 20px",
            cursor: checked ? "pointer" : "default",
            opacity: checked ? 1 : 0.5,
          }}
        >
          Continue
        </button>
        <button
          onClick={onFail}
          style={{ background: "transparent", border: "1px solid var(--st-hairline)", borderRadius: 6, padding: "10px 20px", cursor: "pointer" }}
        >
          Check failed
        </button>
      </div>
    </div>
  );
}
