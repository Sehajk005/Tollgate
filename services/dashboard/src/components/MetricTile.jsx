// Day 8, Step 3 -- metric tile (UIUX v2 SS6.2). --tg-surface-1, 8px radius,
// 20px padding. The delta/caption line is the point: an absolute number
// without its baseline comparison tells the operator nothing.
//
// Day-2 empty-state rule (UIUX v2 SS6.2): a tile whose real data source does
// not exist yet renders `—` (its caption naming why), NEVER a bare `0`.

export default function MetricTile({ label, value, caption, system = false }) {
  return (
    <div
      style={{
        background: "var(--tg-surface-1)",
        border: "1px solid var(--tg-hairline)",
        borderRadius: "var(--tg-radius-md)",
        padding: 20,
        minWidth: 160,
      }}
    >
      <div className="tg-label" style={{ color: "var(--tg-text-mute)" }}>{label}</div>
      <div
        className="tg-mono-metric tg-num"
        style={{ margin: "6px 0 2px", color: "var(--tg-text)" }}
      >
        {value}
      </div>
      <div
        className="tg-caption"
        style={{ color: system ? "var(--tg-system-text)" : "var(--tg-text-mute)" }}
      >
        {caption}
      </div>
    </div>
  );
}
