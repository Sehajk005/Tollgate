// Day 8, Step 8 -- S1 Product page (App Flow SS2). Minimal: one product, one
// button. Kesar & Co., a small Indian D2C brand -- ordinary, trustworthy,
// forgettable (UIUX v2 SS1). Light, airy, deep-green accent; no Plex.

export default function S1Product({ onBuy }) {
  return (
    <div style={{ maxWidth: 520, margin: "0 auto", padding: "96px 24px" }}>
      <p style={{ letterSpacing: "0.2em", fontSize: 12, color: "var(--st-ink-mute)", margin: 0 }}>
        KESAR &amp; CO.
      </p>
      <h1 style={{ fontSize: 30, fontWeight: 400, margin: "12px 0 8px" }}>Saffron Kurta</h1>
      <p style={{ color: "var(--st-ink-2)", lineHeight: 1.6 }}>
        Hand-block printed cotton. Made in small batches in Jaipur. One product, honestly
        photographed, no design ambition.
      </p>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, margin: "24px 0" }}>
        <span style={{ fontSize: 22 }}>₹1,200</span>
        <span style={{ color: "var(--st-ink-mute)", fontSize: 13 }}>incl. taxes</span>
      </div>
      <button
        onClick={onBuy}
        style={{
          background: "var(--st-accent)",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: "12px 24px",
          fontSize: 15,
          cursor: "pointer",
        }}
      >
        Buy now
      </button>
    </div>
  );
}
