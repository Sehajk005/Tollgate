"""
Source: Day-4 Plan (rev. 2) Step 4 -- Sample construction, splits, views,
and leakage guarantees. This is the F1/F2/F10/F13 fix set from rev. 1.

`stream_tier` vs `episode_tier` (F1): `stream_tier` is the tier of the
STREAM RUN a sample came from (easy|medium|hard|None -- None for
negative-control runs); `episode_tier` is the tier of the EPISODE the
sample belongs to (None for legitimate/baseline/negative-control samples).
Conflating these put every negative control into a holdout's train side
and made the "hard" test split single-class at pi=1.0.

`Split.validate()` raises on a single-class split, but is only called by
the two PARTITIONING constructors (`temporal_split`, `attack_shape_holdout`)
that are meant to produce two-class train/test halves of the labelled
corpus -- a single-class result there is a bug (F1's exact failure mode).
`negative_control_splits()` deliberately returns single-class (100%
legitimate) evaluation splits by design -- that IS the point of a negative
control (test 10 / F13) -- so it does not call `.validate()`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

from packages.features.compute import WINDOW_30M_MS
from packages.simulator.negative import SCENARIOS
from packages.simulator.stream import SimulatorOutput

MAX_FEATURE_HORIZON_MS = WINDOW_30M_MS  # 1_800_000 -- the widest reported window
GATEWAY_LATENCY_MS = 340                # TRD §4 -- outcomes arrive at ingest + gateway latency


class SingleClassSplitError(Exception):
    pass


@dataclass(frozen=True)
class Sample:
    event_id: str
    t_ms: int
    is_attack: bool
    stream_tier: Optional[str]      # tier of the STREAM RUN this came from -- easy|medium|hard|None
    episode_tier: Optional[str]     # tier of the EPISODE it belongs to -- None for legitimate
    episode_id: Optional[str]
    kind: str                       # "baseline" | "attack" | "negative_control"
    scenario: Optional[str]
    entity_overlap: bool
    outcome_visible_ms: int         # t_ms + GATEWAY_LATENCY_MS
    ip: str
    bin: str
    card_hash: str
    amount_minor: int
    gateway_status: str
    decline_code: Optional[str]
    # Source: Day-5 Plan Step 3 (seam S3) -- which run in `build_runs()` order
    # produced this sample. `event_id` is only unique WITHIN a run
    # (packages/simulator/stream.py::merge_and_number restarts at "e-0000000"
    # per run), so (run_index, event_id) is the join key to the Day-5 feature
    # corpus. Defaulted so every existing Sample(...) construction and the
    # dataclasses.replace() in compute_entity_overlap keep working unchanged.
    run_index: int = -1


@dataclass(frozen=True)
class Split:
    name: str
    samples: Tuple[Sample, ...]

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def n_positive(self) -> int:
        return sum(1 for s in self.samples if s.is_attack)

    @property
    def prevalence(self) -> float:
        if not self.samples:
            return 0.0
        return self.n_positive / self.n

    def validate(self) -> "Split":
        if self.n > 0 and self.prevalence in (0.0, 1.0):
            raise SingleClassSplitError(
                f"split {self.name!r} is single-class: prevalence={self.prevalence} n={self.n}"
            )
        return self


def build_dataset(runs: Sequence[Tuple[Optional[str], SimulatorOutput]]) -> List[Sample]:
    """
    The dataset is a union of per-tier stream runs, each containing both
    baseline and attack traffic. `runs` is `(stream_tier, SimulatorOutput)`
    pairs; pass `stream_tier=None` for negative-control / scenario runs
    (they have no attack-tier stream_tier of their own).
    """
    samples: List[Sample] = []
    for run_index, (stream_tier, output) in enumerate(runs):
        episodes_by_id = {ep.episode_id: ep for ep in output.episodes}
        for event in output.events:
            label = next(lbl for lbl in output.labels if lbl.event_id == event.event_id)
            episode = episodes_by_id.get(label.episode_id) if label.episode_id else None
            kind = episode.kind if episode is not None else "baseline"
            scenario = episode.scenario if episode is not None else None
            episode_tier = episode.tier if episode is not None else None
            samples.append(Sample(
                event_id=event.event_id, t_ms=event.t_ms, is_attack=label.is_attack,
                stream_tier=stream_tier, episode_tier=episode_tier, episode_id=label.episode_id,
                kind=kind, scenario=scenario, entity_overlap=False,
                outcome_visible_ms=event.t_ms + GATEWAY_LATENCY_MS,
                ip=event.ip, bin=event.bin, card_hash=event.card_hash,
                amount_minor=event.amount_minor, gateway_status=label.gateway_status,
                decline_code=label.decline_code,
                # Source: Day-5 Plan Step 3 -- run_index is the position of this
                # run in the `runs` sequence, which build_runs()/replay_corpus()
                # keep aligned with merchant_id f"m-eval-{run_index:02d}".
                run_index=run_index,
            ))
    return samples


def compute_entity_overlap(samples: List[Sample]) -> List[Sample]:
    """
    Keys are `ip` and `card_hash` only -- BIN is excluded (F10, test 16
    measures why). Predicate: an attack episode's contamination window is
    derived from its own is_attack=True samples' timestamps (lo=min t_ms,
    hi=max t_ms), extended to `hi + MAX_FEATURE_HORIZON_MS` -- contamination
    does not stop at the episode boundary. A legitimate sample sharing `ip`
    or `card_hash` with that episode, timed inside the window, is flagged.
    """
    windows_by_episode: Dict[str, Tuple[int, int, Set[str], Set[str]]] = {}
    for s in samples:
        if not s.is_attack or s.episode_id is None:
            continue
        lo, hi, ips, cards = windows_by_episode.get(s.episode_id, (s.t_ms, s.t_ms, set(), set()))
        lo = min(lo, s.t_ms)
        hi = max(hi, s.t_ms)
        ips = ips | {s.ip}
        cards = cards | {s.card_hash}
        windows_by_episode[s.episode_id] = (lo, hi, ips, cards)

    windows = [
        (lo, hi + MAX_FEATURE_HORIZON_MS, ips, cards)
        for lo, hi, ips, cards in windows_by_episode.values()
    ]

    result: List[Sample] = []
    for s in samples:
        if s.is_attack:
            result.append(s)
            continue
        overlap = any(
            lo <= s.t_ms <= hi and (s.ip in ips or s.card_hash in cards)
            for lo, hi, ips, cards in windows
        )
        result.append(s if overlap == s.entity_overlap else replace(s, entity_overlap=overlap))
    return result


def temporal_split(
    samples: Sequence[Sample], train_fraction: float, embargo_ms: int = MAX_FEATURE_HORIZON_MS,
) -> Tuple[Split, Split]:
    """
    Purged and embargoed (F2): cut at a t_ms boundary, drop every sample in
    the embargo band (boundary, boundary + embargo_ms] from the test side
    (its features would be computed partly over training-period events),
    then group-purge: any episode whose samples land on both sides of the
    boundary, or inside the embargo band, is dropped from BOTH sides so no
    episode_id appears in both splits.
    """
    if not samples:
        raise ValueError("cannot split an empty sample set")
    sorted_samples = sorted(samples, key=lambda s: s.t_ms)
    t_min = sorted_samples[0].t_ms
    t_max = sorted_samples[-1].t_ms
    boundary_t_ms = t_min + int((t_max - t_min) * train_fraction)
    embargo_end_ms = boundary_t_ms + embargo_ms

    straddling_episodes: Set[str] = set()
    episode_sides: Dict[str, Set[str]] = {}
    for s in sorted_samples:
        if s.episode_id is None:
            continue
        if boundary_t_ms < s.t_ms <= embargo_end_ms:
            straddling_episodes.add(s.episode_id)
        side = "train" if s.t_ms <= boundary_t_ms else "test"
        episode_sides.setdefault(s.episode_id, set()).add(side)
    for episode_id, sides in episode_sides.items():
        if len(sides) > 1:
            straddling_episodes.add(episode_id)

    train_samples = tuple(
        s for s in sorted_samples
        if s.t_ms <= boundary_t_ms and s.episode_id not in straddling_episodes
    )
    test_samples = tuple(
        s for s in sorted_samples
        if s.t_ms > embargo_end_ms and s.episode_id not in straddling_episodes
    )

    train_split = Split(name="temporal_train", samples=train_samples).validate()
    test_split = Split(name="temporal_test", samples=test_samples).validate()
    return train_split, test_split


ATTACK_SHAPE_HOLDOUT_NAME = "attack_shape_holdout (held-out attack shape within the authored parameter family)"


def attack_shape_holdout(samples: Sequence[Sample]) -> Tuple[Split, Split]:
    """
    Train = stream_tier in {easy, medium}; test = stream_tier == hard. Both
    sides carry their own baseline traffic (every stream run unions
    baseline + attack), so both are two-class.
    """
    train_samples = tuple(s for s in samples if s.stream_tier in ("easy", "medium"))
    test_samples = tuple(s for s in samples if s.stream_tier == "hard")

    train_split = Split(name=f"{ATTACK_SHAPE_HOLDOUT_NAME} -- train", samples=train_samples).validate()
    test_split = Split(name=f"{ATTACK_SHAPE_HOLDOUT_NAME} -- test", samples=test_samples).validate()
    return train_split, test_split


def exclude_negative_controls(split: Split) -> Split:
    """
    Applied to the TRAIN side only (caller's responsibility) -- applying it
    to both sides would filter negative controls out of evaluation too and
    produce a permanent, perfect-looking 0-FP report (F13).
    """
    filtered = tuple(s for s in split.samples if s.kind != "negative_control")
    return Split(name=f"{split.name} (negative controls excluded)", samples=filtered)


def negative_control_splits(samples: Sequence[Sample]) -> Dict[str, Split]:
    """One dedicated eval split per scenario -- this is where the controls are actually measured (F13)."""
    result: Dict[str, Split] = {}
    for scenario in SCENARIOS:
        scenario_samples = tuple(
            s for s in samples if s.kind == "negative_control" and s.scenario == scenario
        )
        result[scenario] = Split(name=f"negative_control:{scenario}", samples=scenario_samples)
    return result


def clean_view(split: Split) -> Split:
    """A view: legitimate samples with entity_overlap=False, plus all attack samples. Never trains."""
    filtered = tuple(s for s in split.samples if s.is_attack or not s.entity_overlap)
    return Split(name=f"{split.name} (clean view)", samples=filtered)
