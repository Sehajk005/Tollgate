"""
Source: Day-4 Plan (rev. 2) Step 3 -- seven negative-control scenarios,
schema-canonical names (Backend Schema v2 §3.2's spelling, resolving the
six-vs-seven scenario-vocabulary fork, F17). Each scenario function returns
`(list[RawItem], Episode)` with `kind="negative_control"`, `tier=None`,
`scenario=<name>`. Sub-streams are labelled "negative:<scenario>:*",
disjoint from "baseline:*" and "attack:<tier>:*" (Decision 31).

`shared_ip_legit` is the one scenario that embeds genuinely fraudulent
sub-traffic (`is_attack=True`) alongside a legitimate customer sharing the
attacker's IP: it is deliberately self-contained (its own small attack-
shaped burst, not a call into `generate_attack_episode`) so that all of its
items share ONE episode_id under the ONE `Episode` this module's contract
returns -- entity-key contamination is then detectable purely from the
returned samples' own `is_attack`/`t_ms` fields (eval/dataset.py Step 4),
with no second Episode/foreign-key to reconcile. It is the sole source of
`entity_overlap=True` among the seven controls.

`nri_traffic` draws BINs from `FOREIGN_BIN_POOL` and is marked inert on Day
4 (F11): foreign BINs appear only here, negative controls never train, and
`attack.py` emits none, so `bin_is_foreign_issued` has zero variance in the
measured population today.
"""

from __future__ import annotations

from typing import List, Tuple

from packages.simulator.identity import (
    FICTIONAL_BIN_POOL,
    FOREIGN_BIN_POOL,
    opaque_card_hash,
    pick_bin,
)
from packages.simulator.profile import rescale_to_store_aov
from packages.simulator.rng import SubStream
from packages.simulator.stream import Episode, RawItem

MS_PER_HOUR = 3_600_000
# Source: generate.py's EPISODE_START_NUMERATOR/DENOMINATOR convention --
# every bounded-window scenario places its burst 1/3 into the run, leaving
# calm before and after, mirrored here for consistency.
WINDOW_START_NUMERATOR = 1
WINDOW_START_DENOMINATOR = 3

SCENARIOS: Tuple[str, ...] = (
    "flash_sale",
    "corporate_nat",
    "cgnat",
    "retry_storm",
    "subscription_batch",
    "nri_traffic",
    "shared_ip_legit",
)


def _episode_id(scenario: str, seed: int, start_ms: int) -> str:
    return f"neg-{scenario}-{seed}-{start_ms}"


def _make_episode(
    *, scenario: str, seed: int, items: List[RawItem], episode_id: str,
) -> Episode:
    t_values = [item.t_ms for item in items]
    started_at = min(t_values) if t_values else 0
    ended_at = max(t_values) if t_values else 0
    distinct_cards = len({item.card_hash for item in items})
    return Episode(
        episode_id=episode_id, kind="negative_control", tier=None, scenario=scenario,
        started_at=started_at, ended_at=ended_at, attempt_count=len(items),
        distinct_cards=distinct_cards, generator_seed=seed, evasion_params=None,
    )


def _window_start_ms(hours: int) -> int:
    total_ms = hours * MS_PER_HOUR
    return (total_ms * WINDOW_START_NUMERATOR) // WINDOW_START_DENOMINATOR


def _legit_item(
    *, t_ms: int, ip: str, card_hash: str, bin_value: str, amount_minor: int,
    currency: str, session_id: str, episode_id: str,
) -> RawItem:
    return RawItem(
        t_ms=t_ms, ip=ip, card_hash=card_hash, bin=bin_value, amount_minor=amount_minor,
        currency=currency, session_id=session_id, is_attack=False, episode_id=episode_id,
        gateway_status="authorized", decline_code=None,
    )


def _flash_sale(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """Baseline generator shape at 20x rate, bounded to a 30-min window (Day-4 Plan Step 3)."""
    scenario = "flash_sale"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")

    window_ms = 30 * 60_000
    start_ms = _window_start_ms(hours)
    surge_multiplier = 20
    n_events = max(1, (store_profile["baseline_attempts_per_hour"] * surge_multiplier * window_ms) // MS_PER_HOUR)
    n_customers = max(1, n_events // 5)

    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, start_ms)
    customer_cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    customer_bins = [pick_bin(customer_rng, FICTIONAL_BIN_POOL) for _ in range(n_customers)]
    ip_pool = [f"203.0.113.{ip_rng.below(254) + 1}" for _ in range(max(1, n_customers // 5))]

    items = []
    for _ in range(n_events):
        t_ms = start_ms + arrivals_rng.below(window_ms)
        customer = customer_rng.below(n_customers)
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        items.append(_legit_item(
            t_ms=t_ms, ip=ip_pool[customer % len(ip_pool)], card_hash=customer_cards[customer],
            bin_value=customer_bins[customer], amount_minor=amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _corporate_nat(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """~300 distinct customers/cards sharing ONE IP (Day-4 Plan Step 3)."""
    scenario = "corporate_nat"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")

    n_customers = 300
    total_ms = max(1, hours * MS_PER_HOUR)
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, 0)
    shared_ip = f"203.0.113.{ip_rng.below(254) + 1}"
    cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    bins_ = [pick_bin(customer_rng, FICTIONAL_BIN_POOL) for _ in range(n_customers)]

    items = []
    for i in range(n_customers):
        t_ms = arrivals_rng.below(total_ms)
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        items.append(_legit_item(
            t_ms=t_ms, ip=shared_ip, card_hash=cards[i], bin_value=bins_[i],
            amount_minor=amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _cgnat(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """Large customer set over a small carrier IP pool, sustained (Day-4 Plan Step 3)."""
    scenario = "cgnat"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")

    n_customers = 500
    ip_pool_size = 5
    total_ms = max(1, hours * MS_PER_HOUR)
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, 0)
    ip_pool = [f"203.0.113.{ip_rng.below(254) + 1}" for _ in range(ip_pool_size)]
    cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    bins_ = [pick_bin(customer_rng, FICTIONAL_BIN_POOL) for _ in range(n_customers)]
    customer_ip = [ip_pool[c % ip_pool_size] for c in range(n_customers)]

    items = []
    for i in range(n_customers):
        t_ms = arrivals_rng.below(total_ms)
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        items.append(_legit_item(
            t_ms=t_ms, ip=customer_ip[i], card_hash=cards[i], bin_value=bins_[i],
            amount_minor=amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _retry_storm(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """One customer, one card, 4-5 attempts in ~2 min, decline_code=expired_card (Day-4 Plan Step 3)."""
    scenario = "retry_storm"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")
    count_rng = SubStream(seed, f"negative:{scenario}:count")

    window_ms = 120_000
    start_ms = _window_start_ms(hours)
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, start_ms)
    ip = f"203.0.113.{ip_rng.below(254) + 1}"
    card = opaque_card_hash(customer_rng)
    bin_value = pick_bin(customer_rng, FICTIONAL_BIN_POOL)
    amount_minor = rescale_to_store_aov(
        quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
    )
    session_id = f"s-{session_rng.getrandbits(48):012x}"
    n_attempts = 4 + count_rng.below(2)  # 4 or 5

    items = []
    for i in range(n_attempts):
        t_ms = start_ms + (window_ms * i) // n_attempts + arrivals_rng.below(max(1, window_ms // n_attempts))
        items.append(RawItem(
            t_ms=t_ms, ip=ip, card_hash=card, bin=bin_value, amount_minor=amount_minor,
            currency=currency, session_id=session_id, is_attack=False, episode_id=episode_id,
            gateway_status="declined", decline_code="expired_card",
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _subscription_batch(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """Many customers, identical amount_minor, tight burst (Day-4 Plan Step 3)."""
    scenario = "subscription_batch"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")
    amount_pick_rng = SubStream(seed, f"negative:{scenario}:amount_pick")

    n_customers = 200
    window_ms = 5 * 60_000
    start_ms = _window_start_ms(hours)
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, start_ms)
    shared_amount_minor = rescale_to_store_aov(
        quantiles[amount_pick_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
    )
    cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    bins_ = [pick_bin(customer_rng, FICTIONAL_BIN_POOL) for _ in range(n_customers)]
    ips = [f"203.0.113.{ip_rng.below(254) + 1}" for _ in range(n_customers)]

    items = []
    for i in range(n_customers):
        t_ms = start_ms + arrivals_rng.below(window_ms)
        items.append(_legit_item(
            t_ms=t_ms, ip=ips[i], card_hash=cards[i], bin_value=bins_[i],
            amount_minor=shared_amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _nri_traffic(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """Legitimate baseline traffic drawing from FOREIGN_BIN_POOL (Day-4 Plan Step 3, F11 inert)."""
    scenario = "nri_traffic"
    arrivals_rng = SubStream(seed, f"negative:{scenario}:arrivals")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    customer_rng = SubStream(seed, f"negative:{scenario}:customer")
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    session_rng = SubStream(seed, f"negative:{scenario}:session")

    total_ms = max(1, hours * MS_PER_HOUR)
    rate_per_hour = store_profile["baseline_attempts_per_hour"]
    n_events = max(1, rate_per_hour * hours)
    n_customers = max(1, n_events // 5)

    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, 0)
    customer_cards = [opaque_card_hash(customer_rng) for _ in range(n_customers)]
    customer_bins = [pick_bin(customer_rng, FOREIGN_BIN_POOL) for _ in range(n_customers)]
    ip_pool = [f"203.0.113.{ip_rng.below(254) + 1}" for _ in range(max(1, n_customers // 5))]

    items = []
    for _ in range(n_events):
        t_ms = arrivals_rng.below(total_ms)
        customer = customer_rng.below(n_customers)
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        items.append(_legit_item(
            t_ms=t_ms, ip=ip_pool[customer % len(ip_pool)], card_hash=customer_cards[customer],
            bin_value=customer_bins[customer], amount_minor=amount_minor, currency=currency,
            session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
        ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


def _shared_ip_legit(
    *, seed: int, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    """
    An easy-shaped attack burst PLUS a legitimate customer on the
    attacker's own IP -- the sole source of entity_overlap=True (Day-4
    Plan Step 3). Self-contained: all items share ONE episode_id so no
    second Episode/foreign-key is needed (module docstring).
    """
    scenario = "shared_ip_legit"
    ip_rng = SubStream(seed, f"negative:{scenario}:ip")
    card_rng = SubStream(seed, f"negative:{scenario}:card")
    timing_rng = SubStream(seed, f"negative:{scenario}:timing")
    amount_rng = SubStream(seed, f"negative:{scenario}:amount")
    bin_rng = SubStream(seed, f"negative:{scenario}:bin")
    session_rng = SubStream(seed, f"negative:{scenario}:session")
    decline_rng = SubStream(seed, f"negative:{scenario}:decline")
    legit_rng = SubStream(seed, f"negative:{scenario}:legit")

    window_ms = 300_000
    start_ms = _window_start_ms(hours)
    aov_minor = store_profile["aov_minor"]
    currency = store_profile["currency"]
    quantiles = baseline_profile["order_value_quantiles_minor_gbp"]
    mean_gbp_minor = baseline_profile["mean_order_value_gbp_minor"]

    episode_id = _episode_id(scenario, seed, start_ms)

    ip_pool_size = 2
    n_cards = 50
    total_attempts = 60
    ips = [f"198.51.100.{ip_rng.below(254) + 1}" for _ in range(ip_pool_size)]
    cards = [opaque_card_hash(card_rng) for _ in range(n_cards)]
    bins_ = FICTIONAL_BIN_POOL[:4]
    base_gap_ms = max(1, window_ms // total_attempts)

    items = []
    for i in range(total_attempts):
        t_ms = start_ms + i * base_gap_ms + timing_rng.below(base_gap_ms)
        ip = ips[ip_rng.below(len(ips))]
        card = cards[card_rng.below(len(cards))]
        bin_value = bins_[bin_rng.below(len(bins_))]
        amount_minor = rescale_to_store_aov(
            quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
        )
        declined = decline_rng.below(1000) < 950
        items.append(RawItem(
            t_ms=t_ms, ip=ip, card_hash=card, bin=bin_value, amount_minor=amount_minor,
            currency=currency, session_id=f"s-{session_rng.getrandbits(48):012x}",
            is_attack=True, episode_id=episode_id,
            gateway_status="declined" if declined else "authorized",
            decline_code="invalid_card" if declined else None,
        ))

    # The legitimate customer: same IP as the attacker's pool, own fresh
    # card/bin, timed inside the burst window -- entity-key contamination
    # by construction.
    legit_card = opaque_card_hash(legit_rng)
    legit_bin = pick_bin(legit_rng, FICTIONAL_BIN_POOL)
    legit_amount = rescale_to_store_aov(
        quantiles[amount_rng.below(len(quantiles))], aov_minor, mean_gbp_minor,
    )
    legit_t_ms = start_ms + legit_rng.below(window_ms)
    items.append(_legit_item(
        t_ms=legit_t_ms, ip=ips[0], card_hash=legit_card, bin_value=legit_bin,
        amount_minor=legit_amount, currency=currency,
        session_id=f"s-{session_rng.getrandbits(48):012x}", episode_id=episode_id,
    ))

    return items, _make_episode(scenario=scenario, seed=seed, items=items, episode_id=episode_id)


_BUILDERS = {
    "flash_sale": _flash_sale,
    "corporate_nat": _corporate_nat,
    "cgnat": _cgnat,
    "retry_storm": _retry_storm,
    "subscription_batch": _subscription_batch,
    "nri_traffic": _nri_traffic,
    "shared_ip_legit": _shared_ip_legit,
}


def generate_negative_episode(
    *, seed: int, scenario: str, hours: int, store_profile: dict, baseline_profile: dict,
) -> Tuple[List[RawItem], Episode]:
    if scenario not in _BUILDERS:
        raise ValueError(f"unknown negative-control scenario: {scenario!r}, must be one of {SCENARIOS}")
    return _BUILDERS[scenario](
        seed=seed, hours=hours, store_profile=store_profile, baseline_profile=baseline_profile,
    )
