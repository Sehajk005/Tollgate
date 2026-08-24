"""
Source: Day-2 Plan §F "Attack model" -- AttackModel (easy | hard on Day 2).
Sub-streams are labelled "attack:<tier>:*" -- disjoint from baseline
(Decision 31) and from each other tier, so an easy vs hard run at one seed
produces independent attack content; only the baseline subsequence is
required to match (A4).

Amounts are drawn from the SAME empirical quantile table as the baseline
(baseline_profile), restricted to `amount_quantile_band`'s low-index range
-- Eval Protocol v2 §4/V2's anti-circularity requirement, verbatim: "the
attacker's amounts are drawn from the store's own empirical distribution's
low tail rather than a fixed constant" (A9).

Timing uses jittered-even spacing rather than pure uniform-random
placement across the episode window: this keeps the *measured*
attempts/hour (recomputed from t_ms by A8) tightly clustered around the
configured attempts_per_hour rather than subject to edge-clustering
variance, without weakening determinism (still fully seeded).
"""

from __future__ import annotations

from packages.simulator.identity import FICTIONAL_BIN_POOL, opaque_card_hash
from packages.simulator.profile import rescale_to_store_aov
from packages.simulator.rng import SubStream
from packages.simulator.stream import RawItem

# Day-2 authored placeholder (see baseline.py's DECLINE_CODES docstring
# note): card-testing traffic mostly fails; not consumed anywhere on Day 2.
DECLINE_RATE_PER_MILLE = 950
DECLINE_CODE = "invalid_card"


def generate_attack_episode(
    *, seed: int, tier: str, tier_config: dict, episode_start_ms: int,
    baseline_profile: dict, aov_minor: int, currency: str,
) -> tuple:
    """
    Returns (items: list[RawItem], episode_id: str, ended_at_ms: int).

    Detection is never informed by truth (Day-2 Plan §G): this function has
    no access to score_attempt or the rules layer -- it only ever produces
    ScoreRequest-shaped content and an out-of-band ip, exactly like the
    baseline model.
    """
    ip_rng = SubStream(seed, f"attack:{tier}:ip")
    card_rng = SubStream(seed, f"attack:{tier}:card")
    timing_rng = SubStream(seed, f"attack:{tier}:timing")
    amount_rng = SubStream(seed, f"attack:{tier}:amount")
    bin_rng = SubStream(seed, f"attack:{tier}:bin")
    session_rng = SubStream(seed, f"attack:{tier}:session")
    decline_rng = SubStream(seed, f"attack:{tier}:decline")

    duration_s = tier_config["episode_duration_s"]["value"]
    duration_ms = duration_s * 1000
    attempts_per_hour = tier_config["attempts_per_hour"]["value"]
    total_attempts = max(1, (attempts_per_hour * duration_s) // 3600)

    ip_pool_size = tier_config["ip_pool_size"]["value"]
    ips = [f"198.51.100.{ip_rng.below(254) + 1}" for _ in range(ip_pool_size)]  # RFC 5737 TEST-NET-2

    n_cards = tier_config["distinct_cards"]["value"]
    cards = [opaque_card_hash(card_rng) for _ in range(n_cards)]

    bin_pool_size = tier_config["bin_pool_size"]["value"]
    bins = FICTIONAL_BIN_POOL[:bin_pool_size]

    band = tier_config["amount_quantile_band"]
    lo_idx, hi_idx = band["min"], band["max"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    base_gap_ms = max(1, duration_ms // total_attempts)
    episode_id = f"ep-{tier}-{seed}-{episode_start_ms}"

    items = []
    for i in range(total_attempts):
        t_ms = episode_start_ms + i * base_gap_ms + timing_rng.below(base_gap_ms)
        ip = ips[ip_rng.below(len(ips))]
        card = cards[card_rng.below(len(cards))]
        bin_value = bins[bin_rng.below(len(bins))]
        q_index = lo_idx + amount_rng.below(hi_idx - lo_idx + 1)
        amount_minor = rescale_to_store_aov(quantiles[q_index], aov_minor, mean_gbp_minor)
        declined = decline_rng.below(1000) < DECLINE_RATE_PER_MILLE
        items.append(RawItem(
            t_ms=t_ms, ip=ip, card_hash=card, bin=bin_value, amount_minor=amount_minor,
            currency=currency, session_id=f"s-{session_rng.getrandbits(48):012x}",
            is_attack=True, episode_id=episode_id,
            gateway_status="declined" if declined else "authorized",
            decline_code=DECLINE_CODE if declined else None,
        ))

    ended_at_ms = episode_start_ms + duration_ms
    return items, episode_id, ended_at_ms
