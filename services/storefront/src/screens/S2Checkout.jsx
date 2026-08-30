import { useState } from "react";
import { resolveClientOutcome, screenForOutcome } from "../lib/outcome.js";

// Day 8, Step 8 -- S2 Checkout. Standard card form. This screen owns the
// routing: POST /v1/score -> resolveClientOutcome(status, headers, body, error)
// -> screenForOutcome -> the next screen. S2 is the checkout/routing STATE,
// preserved (not one of the five new screens, but they are unreachable
// without it).
//
// `?demo=1` additions (App Flow SS5 S2): a live /v1/score latency readout and
// a tier badge that INCLUDES `shed` and `fail_open` -- the two states a judge
// asks about. Both demo-gated; the default checkout shows neither.

const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

export default function S2Checkout({ demo, onRoute }) {
  const [submitting, setSubmitting] = useState(false);
  const [latencyMs, setLatencyMs] = useState(null);
  const [outcome, setOutcome] = useState(null);

  async function pay() {
    setSubmitting(true);
    setOutcome(null);
    const started = performance.now();
    let statusCode = null;
    let headers = null;
    let body = null;
    let error = null;
    try {
      const resp = await fetch("/v1/score", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tollgate-Key": API_KEY },
        body: JSON.stringify({
          event_id: `evt-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          card_hash: `card-${Math.random().toString(36).slice(2)}`,
          bin: "999001",
          amount_minor: 120000,
          currency: "INR",
        }),
      });
      statusCode = resp.status;
      headers = resp.headers;
      body = await resp.json().catch(() => null);
    } catch (err) {
      error = err;
    }
    setLatencyMs(Math.round(performance.now() - started));
    const co = resolveClientOutcome({ statusCode, headers, body, error });
    setOutcome(co);
    setSubmitting(false);
    onRoute(screenForOutcome(co), co);
  }

  return (
    <div style={{ maxWidth: 460, margin: "0 auto", padding: "80px 24px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 400, marginBottom: 4 }}>Checkout</h1>
      <p style={{ color: "var(--st-ink-mute)", fontSize: 13, marginTop: 0 }}>
        Kesar &amp; Co. · Saffron Kurta · ₹1,200
      </p>

      <label style={{ display: "block", fontSize: 13, color: "var(--st-ink-2)", marginTop: 20 }}>
        Card number
        <input
          defaultValue="9990 0100 0000 0000"
          style={{ display: "block", width: "100%", padding: 10, marginTop: 4, border: "1px solid var(--st-hairline)", borderRadius: 6 }}
        />
      </label>
      <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
        <label style={{ flex: 1, fontSize: 13, color: "var(--st-ink-2)" }}>
          Expiry
          <input defaultValue="04 / 28" style={{ display: "block", width: "100%", padding: 10, marginTop: 4, border: "1px solid var(--st-hairline)", borderRadius: 6 }} />
        </label>
        <label style={{ flex: 1, fontSize: 13, color: "var(--st-ink-2)" }}>
          CVV
          <input defaultValue="123" style={{ display: "block", width: "100%", padding: 10, marginTop: 4, border: "1px solid var(--st-hairline)", borderRadius: 6 }} />
        </label>
      </div>

      <button
        onClick={pay}
        disabled={submitting}
        style={{
          marginTop: 20,
          width: "100%",
          background: "var(--st-accent)",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: 12,
          fontSize: 15,
          cursor: submitting ? "default" : "pointer",
        }}
      >
        {submitting ? "Processing…" : "Pay ₹1,200"}
      </button>

      {demo && (
        <div style={{ marginTop: 16, fontSize: 12, color: "var(--st-ink-mute)", fontFamily: "ui-monospace, monospace" }}>
          <span>/v1/score latency: {latencyMs == null ? "—" : `${latencyMs} ms`}</span>
          {" · "}
          <span>tier: {outcome || "—"}</span>
        </div>
      )}
    </div>
  );
}
