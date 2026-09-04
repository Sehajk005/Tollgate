import { TIER_TOKENS } from "../lib/labels.js";

// Day 8, Step 3 -- the live event ticker (UIUX v2 SS6.4). Single 28px rows,
// `mono-data` throughout, `tnum` on every column, a left 2px tier stripe.
//
// Motion is CSS-ONLY: new rows enter with a 120ms fade (@keyframes below),
// NO slide -- at attack volume, sliding rows induce motion sickness. Because
// the fade is a CSS animation, base.css's `prefers-reduced-motion` media
// block neutralises it with zero JS (pinned by test_ui_reduced_motion.py).
//
// SS6.4 rules: pseudonym first then a truncated real value; an unscored row
// (`shed` / `fail_open`) shows `—`, never a score; identifiers truncate to
// 8 chars; no PAN/email/phone ever.

function fmtTime(ms) {
  if (!ms && ms !== 0) return "--:--:--";
  const d = new Date(ms);
  return d.toISOString().slice(11, 23);
}

function trunc(v, n = 8) {
  if (v == null) return "—";
  const s = String(v);
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function Row({ e }) {
  const a = e.availability || {};
  const unscored = a.shed || a.fail_open;
  const tierToken = unscored ? "--tg-text-mute" : TIER_TOKENS[e.decision] || "--tg-calm";
  const pseudo = e.incident && e.incident.pseudonym ? e.incident.pseudonym : "—";
  const label = a.fail_open ? "FAIL-OPEN" : a.shed ? "SHED" : String(e.decision || "").toUpperCase();
  return (
    <li
      className="tg-ticker-row tg-mono-data tg-num"
      style={{
        display: "grid",
        gridTemplateColumns: "96px 12px 160px 72px 152px",
        alignItems: "center",
        gap: 8,
        height: 28,
        padding: "0 8px",
        borderLeft: `2px solid var(${tierToken})`,
        borderBottom: "1px solid var(--tg-hairline)",
        color: "var(--tg-text-2)",
      }}
    >
      <span>{fmtTime(e.ingest_time)}</span>
      <span aria-hidden="true" style={{ color: `var(${tierToken})` }}>▏</span>
      <span>
        {pseudo} &middot; {trunc(e.ip)}
      </span>
      <span>{trunc(e.bin, 6)}</span>
      {/* Remediation plan FIX-020 (AUDIT-023): the separate score column
          rendered an empty string for every scored row -- a permanently blank
          64px column that reads as missing data. Its width is folded in here,
          and the unscored dash moves into this cell so `shed` / `fail_open`
          still read as unscored, which is SS6.4's actual requirement. */}
      <span style={{ color: unscored ? "var(--tg-text-mute)" : "var(--tg-text)" }}>
        {unscored ? `— ${label}` : label}
      </span>
    </li>
  );
}

export default function EventTicker({ events = [], limit = 40 }) {
  return (
    <div>
      <style>{`
        @keyframes tg-fade-in { from { opacity: 0; } to { opacity: 1; } }
        .tg-ticker-row { animation: tg-fade-in 120ms ease-out; }
        .tg-ticker-row:hover { background: var(--tg-surface-3); }
      `}</style>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {events.slice(0, limit).map((e, i) => (
          <Row key={e.attempt_uid || i} e={e} />
        ))}
      </ul>
    </div>
  );
}
