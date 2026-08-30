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

const FIVE_MIN_MS = 5 * 60 * 1000;

export default function D1Live({ events = [], enforcement = null }) {
  const latest = events[0];
  const latestIngest = latest ? latest.ingest_time : null;

  const attemptsIn5Min =
    latestIngest == null
      ? 0
      : events.filter((e) => latestIngest - e.ingest_time <= FIVE_MIN_MS).length;

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
        <MetricTile label="Attempts · 5 min" value={attemptsIn5Min} caption="live · event time" />
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
