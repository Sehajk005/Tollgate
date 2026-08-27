"""
Source: Day-4 Plan (rev. 2) §6 tests 7-8 -- "Temporal split: purge +
embargo" and "Holdout is two-class on both sides."
"""

from __future__ import annotations

import pytest

from eval.dataset import (
    MAX_FEATURE_HORIZON_MS,
    SingleClassSplitError,
    attack_shape_holdout,
    build_dataset,
    temporal_split,
)
from packages.simulator.generate import build_stream


BLOCK_HOURS = 3
N_BLOCKS_PER_TIER = 4


def _multi_tier_dataset(block_hours=BLOCK_HOURS, n_blocks_per_tier=N_BLOCKS_PER_TIER):
    # A single build_stream() run has exactly ONE attack episode at a fixed
    # spot in its window -- no boundary placement could ever give a
    # temporal split attack representation on both sides. Multiple
    # non-overlapping, sequentially-epoched blocks per tier spread several
    # episodes across a longer combined timeline instead.
    runs = []
    block_i = 0
    for _ in range(n_blocks_per_tier):
        for tier in ("easy", "medium", "hard"):
            epoch_ms = block_i * block_hours * 3_600_000
            result = build_stream(seed=42 + block_i, tier=tier, hours=block_hours, epoch_ms=epoch_ms)
            runs.append((tier, result))
            block_i += 1
    return build_dataset(runs)


class TestTemporalSplitPurgeEmbargo:
    def test_embargo_gap_is_at_least_the_configured_horizon(self):
        samples = _multi_tier_dataset()
        train, test = temporal_split(samples, train_fraction=0.7)
        assert train.samples and test.samples
        gap = min(s.t_ms for s in test.samples) - max(s.t_ms for s in train.samples)
        assert gap >= MAX_FEATURE_HORIZON_MS

    def test_no_episode_id_appears_in_both_splits(self):
        samples = _multi_tier_dataset()
        train, test = temporal_split(samples, train_fraction=0.7)
        train_episodes = {s.episode_id for s in train.samples if s.episode_id is not None}
        test_episodes = {s.episode_id for s in test.samples if s.episode_id is not None}
        assert not (train_episodes & test_episodes)

    def test_no_episode_in_either_split_straddles_the_boundary(self):
        samples = _multi_tier_dataset()
        train, test = temporal_split(samples, train_fraction=0.7)
        boundary = max(s.t_ms for s in train.samples)
        embargo_end = boundary + MAX_FEATURE_HORIZON_MS

        episodes = {}
        for s in samples:
            if s.episode_id is None:
                continue
            lo, hi = episodes.get(s.episode_id, (s.t_ms, s.t_ms))
            episodes[s.episode_id] = (min(lo, s.t_ms), max(hi, s.t_ms))

        train_episode_ids = {s.episode_id for s in train.samples if s.episode_id is not None}
        test_episode_ids = {s.episode_id for s in test.samples if s.episode_id is not None}
        for eid in train_episode_ids | test_episode_ids:
            lo, hi = episodes[eid]
            assert not (lo <= boundary < hi or lo <= embargo_end < hi), (
                f"episode {eid} straddles the boundary/embargo band: [{lo}, {hi}]"
            )

    def test_a_planted_straddling_episode_is_dropped_from_both_sides(self):
        from eval.dataset import Sample

        base = _multi_tier_dataset(block_hours=1)
        # Mirror temporal_split()'s own boundary formula exactly (rather
        # than inferring it from a probe run's max(train.t_ms), which can
        # sit well below the true boundary in a sparse region and make the
        # planted points miss the embargo band entirely).
        sorted_base = sorted(base, key=lambda s: s.t_ms)
        t_min, t_max = sorted_base[0].t_ms, sorted_base[-1].t_ms
        boundary = t_min + int((t_max - t_min) * 0.5)

        planted_episode_id = "ep-planted-straddler"
        planted = [
            Sample(
                event_id=f"planted-{i}", t_ms=t_ms, is_attack=True, stream_tier="easy",
                episode_tier="easy", episode_id=planted_episode_id, kind="attack", scenario=None,
                entity_overlap=False, outcome_visible_ms=t_ms + 340, ip="9.9.9.9", bin="999000",
                card_hash="deadbeef", amount_minor=1000, gateway_status="authorized", decline_code=None,
            )
            for i, t_ms in enumerate([boundary - 1000, boundary + 1000])
        ]

        train, test = temporal_split(base + planted, train_fraction=0.5)
        train_episodes = {s.episode_id for s in train.samples}
        test_episodes = {s.episode_id for s in test.samples}
        assert planted_episode_id not in train_episodes
        assert planted_episode_id not in test_episodes

    def test_raises_on_empty_input(self):
        with pytest.raises(ValueError):
            temporal_split([], train_fraction=0.7)


class TestAttackShapeHoldoutTwoClass:
    def test_both_sides_are_two_class(self):
        samples = _multi_tier_dataset()
        train, test = attack_shape_holdout(samples)
        assert 0 < train.prevalence < 1
        assert 0 < test.prevalence < 1

    def test_no_hard_tier_in_train_and_test_is_exactly_hard(self):
        samples = _multi_tier_dataset()
        train, test = attack_shape_holdout(samples)
        assert all(s.stream_tier != "hard" for s in train.samples)
        assert all(s.stream_tier == "hard" for s in test.samples)

    def test_name_carries_authored_parameter_family_wording(self):
        samples = _multi_tier_dataset()
        train, test = attack_shape_holdout(samples)
        assert "authored parameter family" in train.name
        assert "authored parameter family" in test.name

    def test_a_perfect_scorer_scores_1_0_on_the_test_split(self):
        from eval.metrics import roc_auc
        from eval.scorers import PerfectScorer

        samples = _multi_tier_dataset()
        _, test = attack_shape_holdout(samples)
        scorer = PerfectScorer()
        scores = [scorer(s) for s in test.samples]
        labels = [s.is_attack for s in test.samples]
        assert roc_auc(scores, labels) == 1.0

    def test_single_class_input_raises(self):
        from eval.dataset import Sample

        all_hard = [
            Sample(
                event_id=f"e-{i}", t_ms=i * 1000, is_attack=True, stream_tier="hard",
                episode_tier="hard", episode_id="ep-1", kind="attack", scenario=None,
                entity_overlap=False, outcome_visible_ms=i * 1000 + 340, ip="1.1.1.1",
                bin="999000", card_hash="c1", amount_minor=100, gateway_status="authorized",
                decline_code=None,
            )
            for i in range(5)
        ]
        with pytest.raises(SingleClassSplitError):
            attack_shape_holdout(all_hard)
