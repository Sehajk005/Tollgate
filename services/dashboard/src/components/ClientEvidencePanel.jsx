import { useState } from "react";

// Day 8, Step 7 -- the client-asserted evidence panel (UIUX v2 SS6.9).
// COLLAPSED by default, below the entity table. A 3px HATCHED left edge in
// --tg-unverified -- a texture no other panel uses, so the untrusted class is
// recognisable without reading.
//
// The header states all three things: unverified, client-asserted, unused in
// scoring. `user_agent` is truncated at 60 chars and rendered as INERT TEXT
// (never a link, never sortable). The verb carries the trust boundary
// (UIUX v2 SS8): "Client reported ...", not "Session lasted ...".

const HATCH =
  "repeating-linear-gradient(45deg, var(--tg-unverified) 0 2px, transparent 2px 4px)";

export default function ClientEvidencePanel({ clientEvidence }) {
  const [open, setOpen] = useState(false);
  const ua = String(clientEvidence?.user_agent || "").slice(0, 60);

  return (
    <div style={{ borderLeft: "3px solid transparent", borderImage: `${HATCH} 3`, paddingLeft: 12 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="tg-label"
        style={{ background: "transparent", border: "none", color: "var(--tg-text-mute)", cursor: "pointer", padding: "4px 0" }}
      >
        {open ? "▾" : "▸"} CLIENT-ASSERTED · UNVERIFIED · NOT USED IN SCORING
      </button>
      {open && (
        <div className="tg-mono-data" style={{ color: "var(--tg-text-2)", padding: "4px 0 8px" }}>
          <div>Client reported user agent: {ua || "—"}</div>
          {clientEvidence?.observed_at != null && (
            <div className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
              observed {new Date(clientEvidence.observed_at).toISOString().slice(0, 19)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
