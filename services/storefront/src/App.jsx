import { useState } from "react";

// Day 1 ugly S2 checkout. Proves the pipe works; no polish (Impl Plan Day 1 /
// UIUX section 10 v2.1 explicit exclusion list).
export default function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function submitCheckout() {
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch("/v1/score", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tollgate-Key": import.meta.env.VITE_TOLLGATE_API_KEY || "",
        },
        body: JSON.stringify({
          event_id: `evt-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          card_hash: `card-${Math.random().toString(36).slice(2)}`,
          bin: "411111",
          amount_minor: 100,
          currency: "INR",
        }),
      });
      const body = await resp.json();
      if (!resp.ok) {
        setError(`HTTP ${resp.status}: ${JSON.stringify(body)}`);
      } else {
        setResult(body);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: 480 }}>
      <h1>Kesar &amp; Co. -- Checkout (Day 1)</h1>
      <p>One product. One button. This is the walking skeleton.</p>
      <button onClick={submitCheckout} disabled={submitting}>
        {submitting ? "Submitting..." : "Pay Rs. 1.00"}
      </button>
      {result && (
        <pre style={{ background: "#eee", padding: "1rem", marginTop: "1rem" }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
