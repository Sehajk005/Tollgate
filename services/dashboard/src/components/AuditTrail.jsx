// Day 8, Step 7 -- the audit trail (UIUX v2 SS6.6 / App Flow SS5 D3 §4).
// Every tier transition with timestamp, trigger, and the PINNED policy
// version. Plain text, mono-data.

function fmt(ms) {
  return ms == null ? "—" : new Date(ms).toISOString().slice(11, 23);
}

export default function AuditTrail({ timeline = [], pinnedPolicyVersion, resolution, resolvedBy }) {
  return (
    <div>
      <ul className="tg-mono-data" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {timeline.map((t, i) => (
          <li key={i} style={{ padding: "3px 0", borderBottom: "1px solid var(--tg-hairline)", color: "var(--tg-text-2)" }}>
            <span className="tg-num" style={{ color: "var(--tg-text-mute)" }}>{fmt(t.at)}</span>{"  "}
            {(t.from_tier || "—")} → <strong style={{ color: "var(--tg-text)" }}>{t.to_tier}</strong>
            {"  ·  "}{t.trigger}
            {"  ·  policy v"}{pinnedPolicyVersion}
          </li>
        ))}
      </ul>
      {resolution && (
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", marginTop: 6 }}>
          Resolved {resolution} by {resolvedBy || "operator"}.
        </p>
      )}
    </div>
  );
}
