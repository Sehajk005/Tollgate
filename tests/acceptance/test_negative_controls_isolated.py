"""
Source: Day-4 Plan (rev. 2) §6 test 9 -- "Negative controls never train."
Every constructor x all seven scenarios: zero kind=="negative_control" in
any TRAIN split; planted-control test proves non-vacuity.
"""

from __future__ import annotations

from eval.dataset import (
    attack_shape_holdout,
    build_dataset,
    exclude_negative_controls,
    temporal_split,
)
from packages.simulator.generate import build_negative_stream, build_stream
from packages.simulator.negative import SCENARIOS


BLOCK_HOURS = 3
N_BLOCKS_PER_TIER = 4


def _mixed_dataset():
    # A single build_stream() run has exactly ONE attack episode at a fixed
    # spot in its window -- multiple non-overlapping, sequentially-epoched
    # blocks per tier spread several episodes across a longer timeline so a
    # temporal split can put attack representation on both sides.
    runs = []
    block_i = 0
    for _ in range(N_BLOCKS_PER_TIER):
        for tier in ("easy", "medium", "hard"):
            epoch_ms = block_i * BLOCK_HOURS * 3_600_000
            result = build_stream(seed=42 + block_i, tier=tier, hours=BLOCK_HOURS, epoch_ms=epoch_ms)
            runs.append((tier, result))
            block_i += 1
    runs += [(None, build_negative_stream(seed=42, scenario=s, hours=3)) for s in SCENARIOS]
    return build_dataset(runs)


class TestNegativeControlsNeverTrain:
    def test_temporal_train_has_zero_negative_controls_after_exclusion(self):
        samples = _mixed_dataset()
        train, _test = temporal_split(samples, train_fraction=0.7)
        train = exclude_negative_controls(train)
        assert all(s.kind != "negative_control" for s in train.samples)

    def test_attack_shape_holdout_train_has_zero_negative_controls_after_exclusion(self):
        samples = _mixed_dataset()
        train, _test = attack_shape_holdout(samples)
        train = exclude_negative_controls(train)
        assert all(s.kind != "negative_control" for s in train.samples)

    def test_exclusion_is_not_vacuous_negative_controls_were_actually_present(self):
        samples = _mixed_dataset()
        train, _test = temporal_split(samples, train_fraction=0.7)
        # Before exclusion, negative controls ARE present in the raw split
        # (proving the exclusion step actually does something).
        assert any(s.kind == "negative_control" for s in train.samples), (
            "planted-control non-vacuity check failed: no negative controls "
            "were present in the raw split before exclusion"
        )
        excluded = exclude_negative_controls(train)
        assert len(excluded.samples) < len(train.samples)
