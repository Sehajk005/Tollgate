"""
Source: Day-2 Plan §F "Baseline model" -- BaselineTrafficModel. Draws
exclusively from sub-streams labelled "baseline:*", independent of which
attack tier (if any) is generated alongside it (Decision 31; A4).

Decline vocabulary: Backend Schema v2 §3.2 declares `decline_code` a
"closed vocabulary, 9 values" but does not enumerate them; TRD v2 names
`invalid_cvv_share_ip_5m` as a feature, implying `invalid_cvv` is one
member. The 9 values below are a Day-2 authored placeholder (like the
attack-tier numeric parameters) pending a normative Day-7 definition --
Day 2 does not consume gateway_status/decline_code anywhere (Decision 32:
/v1/outcome is Day 7), so nothing is load-bearing on the exact strings.
`gateway_status` itself follows the schema's own DDL comment
("authorized|declined|error"), not the plan's illustrative "approved"
example, since the DDL is the more authoritative source.
"""

from __future__ import annotations

from packages.simulator.identity import FICTIONAL_BIN_POOL, opaque_card_hash, pick_bin
from packages.simulator.profile import rescale_to_store_aov
from packages.simulator.rng import SubStream, cumulative_sum
from packages.simulator.stream import RawItem

MS_PER_HOUR = 3_600_000
HOURS_PER_WEEK = 168
GUARANTEED_EVENTS_PER_EPISODE_WINDOW = 5
CUSTOMERS_PER_EVENT_RATIO = 5  # average repeat-order count per synthetic customer

DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "invalid_cvv", "expired_card",
    "invalid_card", "lost_or_stolen", "limit_exceeded", "issuer_unavailable",
    "suspected_fraud",
]


def generate_baseline_events(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
    episode_windows: tuple = (),
) -> list:
    """
    Returns list[RawItem]. `episode_windows` (start_ms, end_ms) pairs get a
    small guaranteed minimum of baseline traffic layered on top of the
    naturalistic hour-of-week-weighted background rate -- Eval Protocol v2
    §4/V4 presupposes concurrent legitimate traffic, and leaving that to
    pure chance at low hourly volume risks an accidentally-quiet episode
    (Day-2 Plan §F anti-leakage checklist: "baseline continues throughout
    every episode; asserted" -- A7).
    """
    arrivals_rng = SubStream(seed, "baseline:arrivals")
    amount_rng = SubStream(seed, "baseline:amount")
    customer_rng = SubStream(seed, "baseline:customer")
    ip_rng = SubStream(seed, "baseline:ip")
    decline_rng = SubStream(seed, "baseline:decline")
    session_rng = SubStream(seed, "baseline:session")
    guarantee_rng = SubStream(seed, "baseline:guarantee")

    rate_per_hour = store_profile["baseline_attempts_per_hour"]
    total_events = max(0, rate_per_hour * hours)

    hour_weights = baseline_profile["hour_of_week_weights"]
    slot_weights = [hour_weights[h % HOURS_PER_WEEK] + 1 for h in range(max(hours, 1))]
    slot_cumulative = cumulative_sum(slot_weights)

    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    decline_rate_per_mille = store_profile["decline_rate_per_mille"]
    cgnat_share_per_mille = store_profile["cgnat_share_per_mille"]

    n_customers = max(1, total_events // CUSTOMERS_PER_EVENT_RATIO) if total_events else 1
    n_ips = max(1, n_customers - (n_customers * cgnat_share_per_mille) // 1000)
    customer_cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    customer_bins = [pick_bin(customer_rng, FICTIONAL_BIN_POOL) for _ in range(n_customers)]
    ip_pool = [f"203.0.113.{ip_rng.below(254) + 1}" for _ in range(n_ips)]  # RFC 5737 TEST-NET-3
    customer_ip = [ip_pool[c % n_ips] for c in range(n_customers)]

    def _make_item(t_ms: int) -> RawItem:
        customer = customer_rng.below(n_customers)
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        declined = decline_rng.below(1000) < decline_rate_per_mille
        return RawItem(
            t_ms=t_ms, ip=customer_ip[customer], card_hash=customer_cards[customer],
            bin=customer_bins[customer], amount_minor=amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}",
            is_attack=False, episode_id=None,
            gateway_status="declined" if declined else "authorized",
            decline_code=DECLINE_CODES[decline_rng.below(len(DECLINE_CODES))] if declined else None,
        )

    items = []
    for _ in range(total_events):
        slot = arrivals_rng.pick_index(slot_cumulative)
        t_ms = slot * MS_PER_HOUR + arrivals_rng.below(MS_PER_HOUR)
        items.append(_make_item(t_ms))

    for start_ms, end_ms in episode_windows:
        span = max(1, end_ms - start_ms)
        for _ in range(GUARANTEED_EVENTS_PER_EPISODE_WINDOW):
            items.append(_make_item(start_ms + guarantee_rng.below(span)))

    return items
