// Day 8, Step 3 -- the system-state banner (UIUX v2 SS6.10). Full width,
// directly under the Stream Rail, only when active. MONOCHROME by design
// (--tg-system-bg / --tg-system-edge, no wash, no state colour, no glyph
// fill) -- a horizontal `⌁` mark in --tg-text-mute. Colour on this dashboard
// makes exactly one claim: how worried to be about the STORE. Never about
// Tollgate's own health (UIUX v2 SS2.1).
//
// Three variants, copy VERBATIM from SS6.10's table. Stacks BELOW the threat
// band, never above -- the store's threat level outranks Tollgate's health,
// always. Dismissible only by the condition clearing.

const GLYPH = "⌁"; // ⌁

function bannerRow(text) {
  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 24px",
        background: "var(--tg-system-bg)",
        borderBottom: "1px solid var(--tg-system-edge)",
        color: "var(--tg-system-text)",
      }}
      className="tg-body"
    >
      <span aria-hidden="true" style={{ color: "var(--tg-text-mute)" }}>{GLYPH}</span>
      <span>{text}</span>
    </div>
  );
}

/**
 * @param enforcement  {active,k_max,advisory_mode} from the SSE event
 * @param shedInLast60 count of shed events seen in the last 60 s (rules-only)
 * @param failOpenAgoS elapsed seconds since a fail_open event was last seen
 *                     within 60 s, or null
 */
export default function SystemBanner({ enforcement, shedInLast60 = 0, failOpenAgoS = null }) {
  const rows = [];

  if (enforcement && enforcement.advisory_mode) {
    const k = enforcement.k_max ?? 10;
    const a = enforcement.active ?? k;
    rows.push(
      <div key="advisory">
        {bannerRow(
          `Enforcement paused — blast-radius cap reached (${a} / ${k}). ` +
            "Scoring continues. Resolve incidents to resume."
        )}
      </div>
    );
  }

  if (shedInLast60 > 0) {
    rows.push(
      <div key="rules-only">
        {bannerRow(
          `Rules-only scoring — request rate above budget. ` +
            `${shedInLast60.toLocaleString()} attempts scored on rules in the last minute.`
        )}
      </div>
    );
  }

  if (failOpenAgoS != null) {
    rows.push(
      <div key="fail-open">
        {bannerRow(
          `Scorer unreachable for ${failOpenAgoS}s. Checkout is unaffected — ` +
            "attempts are passing through unscored. Check the service on port 8080."
        )}
      </div>
    );
  }

  return rows.length ? <div>{rows}</div> : null;
}
