// Day 8, Step 7 -- the entity table (UIUX v2 SS6.8). Plex Mono throughout
// with `tnum`, 44px rows, 1px --tg-hairline dividers, header in `label`.
//
// PSEUDONYM column FIRST (this table is the narrative's decoder ring), then
// the truncated real key, then counts. `entity_type` is rendered EXPLICITLY
// (`ip` / `ip+ua` / `bin` / `card`) so an operator can see when enforcement
// is on a narrower key than a bare IP.

const TYPE_LABEL = { ip: "ip", ipua: "ip+ua", bin: "bin", card: "card" };

function fmt(ms) {
  return ms == null ? "—" : new Date(ms).toISOString().slice(11, 19);
}

export default function EntityTable({ entities = [] }) {
  return (
    <table className="tg-mono-data tg-num" style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr className="tg-label" style={{ color: "var(--tg-text-mute)" }}>
          <th style={{ textAlign: "left", padding: "0 12px", height: 32 }}>pseudonym</th>
          <th style={{ textAlign: "left", padding: "0 12px" }}>type</th>
          <th style={{ textAlign: "left", padding: "0 12px" }}>key</th>
          <th style={{ textAlign: "right", padding: "0 12px" }}>attempts</th>
          <th style={{ textAlign: "left", padding: "0 12px" }}>first seen</th>
          <th style={{ textAlign: "left", padding: "0 12px" }}>last seen</th>
        </tr>
      </thead>
      <tbody>
        {entities.map((e) => (
          <tr key={e.pseudonym} style={{ height: 44, borderTop: "1px solid var(--tg-hairline)" }}>
            <td style={{ padding: "0 12px", color: "var(--tg-text)" }}>{e.pseudonym}</td>
            <td style={{ padding: "0 12px", color: "var(--tg-text-2)" }}>{TYPE_LABEL[e.entity_type] || e.entity_type}</td>
            <td style={{ padding: "0 12px", color: "var(--tg-text-2)" }}>{e.entity_key_truncated}</td>
            <td style={{ padding: "0 12px", textAlign: "right" }}>{e.attempt_count}</td>
            <td style={{ padding: "0 12px", color: "var(--tg-text-mute)" }}>{fmt(e.first_seen)}</td>
            <td style={{ padding: "0 12px", color: "var(--tg-text-mute)" }}>{fmt(e.last_seen)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
