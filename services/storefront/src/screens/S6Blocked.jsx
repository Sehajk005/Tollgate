// Day 8, Step 8 -- S6 Payment blocked. Reached on a confirmed `block` or a
// failed challenge. Refusal + a support contact; plain and specific, never
// dramatic (UIUX v2 SS8).

export default function S6Blocked({ onRetry }) {
  return (
    <div style={{ maxWidth: 460, margin: "0 auto", padding: "120px 24px", textAlign: "center" }}>
      <h1 style={{ fontSize: 22, fontWeight: 400 }}>We could not complete this payment</h1>
      <p style={{ color: "var(--st-ink-2)" }}>
        This order was not charged. If you believe this is a mistake, contact us at
        {" "}
        <span style={{ color: "var(--st-accent)" }}>help@kesar.example</span> with your order details.
      </p>
      <button
        onClick={onRetry}
        style={{ marginTop: 16, background: "transparent", border: "1px solid var(--st-hairline)", borderRadius: 6, padding: "10px 20px", cursor: "pointer" }}
      >
        Return to shop
      </button>
    </div>
  );
}
