// Day 8, Step 8 -- S5 Order confirmed. The terminal screen for allow /
// monitor / shed / fail_open (invisible to the shopper) and for a passed
// challenge or step-up.

export default function S5Confirmed({ onDone }) {
  return (
    <div style={{ maxWidth: 460, margin: "0 auto", padding: "120px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 32, color: "var(--st-accent)" }}>✓</div>
      <h1 style={{ fontSize: 24, fontWeight: 400 }}>Order confirmed</h1>
      <p style={{ color: "var(--st-ink-2)" }}>
        Thank you. Your Saffron Kurta is on its way. A receipt has been emailed to you.
      </p>
      <button
        onClick={onDone}
        style={{ marginTop: 16, background: "transparent", border: "1px solid var(--st-hairline)", borderRadius: 6, padding: "10px 20px", cursor: "pointer" }}
      >
        Back to shop
      </button>
    </div>
  );
}
