"""
python -m packages.simulator.generate --seed 42 --tier easy [--hours 3]
    [--epoch-ms 0] --out PATH [--labels PATH] [--episodes PATH]

Source: Day-2 Plan §F generate.py -- "__main__ CLI". `build_stream()` is
also the in-process entry point Day-2 Plan §E's architecture names:
"stream = packages.simulator.generate.build_stream(seed, tier, cfg)",
called directly by services/scorer/replay.py (Step 7) -- never via a
subprocess for the live replay path (Decision 25: HTTP/subprocess replay
would run on SystemClock and reintroduce F6).

One attack episode is placed at a fixed fraction of the run (1/3 in),
leaving calm baseline before and after it -- Day-2 Plan §F step 7's "IPs"
note and the golden-fixture shape (Step 5: "~2 virtual hours of calm
baseline, one easy-tier episode, ~30 virtual minutes of recovery").
"""

from __future__ import annotations

import argparse
from pathlib import Path

from packages.simulator.attack import generate_attack_episode
from packages.simulator.baseline import generate_baseline_events
from packages.simulator.profile import load_attack_tiers, load_baseline_profile, load_store_profile
from packages.simulator.stream import Episode, Event, SimulatorOutput, canonical_line, merge_and_number, write_jsonl

DEFAULT_HOURS = 3
DEFAULT_EPOCH_MS = 0
MS_PER_HOUR = 3_600_000
EPISODE_START_NUMERATOR = 1
EPISODE_START_DENOMINATOR = 3
# Fixed, tier-independent guarantee window (Day-2 Plan §I A4 vs A7): using
# the tier's actual episode duration here would make the guaranteed-event
# RNG draws (and therefore their t_ms, and therefore the merged baseline
# ordering) diverge between easy (300s) and hard (900s) episodes, breaking
# A4. A fixed 60s window anchored at episode_start_ms is identical across
# tiers and is always a subset of both tiers' actual episode span, so A7
# ("baseline traffic exists inside every episode window") still holds.
GUARANTEE_WINDOW_MS = 60_000


def build_stream(
    *, seed: int, tier: str, hours: int = DEFAULT_HOURS, epoch_ms: int = DEFAULT_EPOCH_MS,
    store_profile: "dict | None" = None, baseline_profile: "dict | None" = None,
    attack_tiers: "dict | None" = None,
) -> SimulatorOutput:
    if store_profile is None:
        store_profile = load_store_profile()
    if baseline_profile is None:
        baseline_profile = load_baseline_profile()
    if attack_tiers is None:
        attack_tiers = load_attack_tiers()

    tier_config = attack_tiers[tier]
    if tier_config.get("pending"):
        raise ValueError(f"tier {tier!r} is not implemented yet (pending: {tier_config['pending']!r})")

    total_ms = hours * MS_PER_HOUR
    episode_start_ms = (total_ms * EPISODE_START_NUMERATOR) // EPISODE_START_DENOMINATOR

    attack_items, episode_id, ended_at_ms = generate_attack_episode(
        seed=seed, tier=tier, tier_config=tier_config, episode_start_ms=episode_start_ms,
        baseline_profile=baseline_profile, aov_minor=store_profile["aov_minor"],
        currency=store_profile["currency"],
    )

    baseline_items = generate_baseline_events(
        seed=seed, hours=hours, store_profile=store_profile, baseline_profile=baseline_profile,
        episode_windows=((episode_start_ms, episode_start_ms + GUARANTEE_WINDOW_MS),),
    )

    events, labels = merge_and_number(baseline_items, attack_items)

    episode_labels = [lbl for lbl in labels if lbl.episode_id == episode_id]
    episode_event_ids = {lbl.event_id for lbl in episode_labels}
    distinct_cards = len({e.card_hash for e in events if e.event_id in episode_event_ids})
    episode = Episode(
        episode_id=episode_id, kind="attack", tier=tier, scenario=None,
        started_at=episode_start_ms, ended_at=ended_at_ms,
        attempt_count=len(episode_labels), distinct_cards=distinct_cards,
        generator_seed=seed, evasion_params=None,
    )

    if epoch_ms:
        events = [
            Event(
                event_id=e.event_id, seq=e.seq, t_ms=e.t_ms + epoch_ms, ip=e.ip,
                card_hash=e.card_hash, bin=e.bin, amount_minor=e.amount_minor,
                currency=e.currency, session_id=e.session_id,
            )
            for e in events
        ]
        episode = Episode(
            episode_id=episode.episode_id, kind=episode.kind, tier=episode.tier,
            scenario=episode.scenario, started_at=episode.started_at + epoch_ms,
            ended_at=episode.ended_at + epoch_ms, attempt_count=episode.attempt_count,
            distinct_cards=episode.distinct_cards, generator_seed=episode.generator_seed,
            evasion_params=episode.evasion_params,
        )

    return SimulatorOutput(events=events, labels=labels, episodes=[episode])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--tier", choices=["easy", "hard"], required=True)
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    parser.add_argument("--epoch-ms", dest="epoch_ms", type=int, default=DEFAULT_EPOCH_MS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--episodes", type=Path, default=None)
    parser.add_argument(
        "--baseline", choices=["empirical", "generative"], default="empirical",
        help="empirical (default): UCI-distilled profile. generative: log-normal/Poisson "
             "fallback (Impl Plan v2.1 20:00 trigger) -- not implemented on Day 2.",
    )
    args = parser.parse_args()

    if args.baseline == "generative":
        raise NotImplementedError(
            "the generative fallback sampler is not implemented on Day 2 "
            "(Day-2 Plan §F: 'stays implemented behind the same interface... not the default')"
        )

    result = build_stream(seed=args.seed, tier=args.tier, hours=args.hours, epoch_ms=args.epoch_ms)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out, [canonical_line(e.to_dict()) for e in result.events])

    if args.labels:
        args.labels.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.labels, [canonical_line(lbl.to_dict()) for lbl in result.labels])

    if args.episodes:
        args.episodes.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.episodes, [canonical_line(ep.to_dict()) for ep in result.episodes])

    print(f"wrote {len(result.events)} events, {len(result.episodes)} episode(s) -> {args.out}")


if __name__ == "__main__":
    main()
