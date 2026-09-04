import MetricTile from "../components/MetricTile.jsx";
import EventTicker from "../components/EventTicker.jsx";

// Day 8, Step 3 -- D1 Live Monitor (App Flow SS5 D1). The Day-2 markup, moved
// out of App.jsx UNCHANGED IN BEHAVIOUR; only the styling is new. The threat
// band and the DC strip now live in the shell (App.jsx), so this screen is
// the four counters + the live ticker.
//
// Micro-fix (Day-8 Plan Step 3): the DECLINE RATE tile caption changes from
// the now-stale `needs /v1/outcome · Day 7` to `outcome-keyed windows not
// fed` -- a copy fix only. No decline-rate computation is added.
//
// Remediation plan FIX-016 (AUDIT-017) -- the ATTEMPTS tile now renders a
// server number. It used to count `events` -- the dashboard's 200-entry SSE
// buffer -- filtered to the last 5 minutes of event time. That is capped at 200
// by construction, so during the exact burst the tile exists to show it stopped
// counting and started under-reporting, and it was non-monotonic as the window
// slid. `feature_snapshot.attempts_per_merchant_5m` is a merchant-scoped
// 5-minute window computed inside the same one-round-trip Lua call, so the tile
// has a named backend source and no frontend buffer limit can silently decide
// what a displayed metric means.

export default function D1Live({ events = [], enforcement = null, latest: latestProp = null }) {
  const latest = latestProp || events[0];

  const attemptsIn5Min =
    latest && latest.feature_snapshot &&
    typeof latest.feature_snapshot.attempts_per_merchant_5m === "number"
      ? latest.feature_snapshot.attempts_per_merchant_5m
      : null;

  const cardsPerIpTop =
    events.length === 0
      ? null
      : events.reduce((max, e) => {
          const v = e.feature_snapshot && e.feature_snapshot.distinct_cards_per_ip_5m;
          return typeof v === "number" && v > max ? v : max;
        }, 0);

  const atCap =
    enforcement && enforcement.k_max > 0 && enforcement.active >= enforcement.k_max;

  return (
    <div style={{ padding: 24 }}>
      <h1 className="tg-display-md" style={{ margin: "0 0 16px" }}>Live Monitor</h1>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
        <MetricTile
          label="Attempts · 5 min"
          value={attemptsIn5Min == null ? "—" : attemptsIn5Min}
          caption="merchant window · event time"
        />
        <MetricTile label="Decline rate" value="—" caption="outcome-keyed windows not fed" />
        <MetricTile
          label="Cards per IP · top"
          value={cardsPerIpTop == null ? "—" : cardsPerIpTop}
          caption="store-relative quantile · Day 5"
        />
        <MetricTile
          label="Enforcement"
          value={enforcement ? `${enforcement.active} / ${enforcement.k_max}` : "—"}
          caption={atCap ? "blast-radius cap reached" : "blast-radius cap"}
          system={atCap}
        />
      </div>

      <EventTicker events={events} />
      {events.length === 0 && (
        <p className="tg-body" style={{ color: "var(--tg-text-mute)", marginTop: 16 }}>
          No incidents. Rules-only detection active while the baseline forms.
        </p>
      )}
    </div>
  );
}
