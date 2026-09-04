import { useEffect } from "react";

// Day 8, Step 8 -- S7 Throttle notice. A STATE of S2, not a route (App Flow
// SS2): "One moment…", a few seconds of friction, then back to S2 to retry.

export default function S7Throttle({ onReturn }) {
  useEffect(() => {
    const t = setTimeout(onReturn, 2500);
    return () => clearTimeout(t);
  }, [onReturn]);

  return (
    <div style={{ maxWidth: 420, margin: "0 auto", padding: "140px 24px", textAlign: "center" }}>
      <h1 style={{ fontSize: 20, fontWeight: 400 }}>One moment…</h1>
      <p style={{ color: "var(--st-ink-2)" }}>
        We are finishing a quick check. Your order has not been placed yet — this page will
        return you to checkout shortly.
      </p>
      <button
        onClick={onReturn}
        style={{ marginTop: 12, background: "transparent", border: "1px solid var(--st-hairline)", borderRadius: 6, padding: "8px 18px", cursor: "pointer" }}
      >
        Back to checkout
      </button>
    </div>
  );
}
