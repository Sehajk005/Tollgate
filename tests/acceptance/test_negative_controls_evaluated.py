"""
Source: Day-4 Plan (rev. 2) §6 test 10 -- "Negative controls are actually
evaluated." The F13 fix. Each of the seven eval splits is non-empty and
contains >=1 sample of its scenario; AlwaysPositiveScorer's FP count ==
n_legitimate exactly, an analytically known non-zero number. A split that
never arrived cannot report 0 FPs and pass.
"""

from __future__ import annotations

from eval.dataset import build_dataset, negative_control_splits
from eval.scorers import AlwaysPositiveScorer
from packages.simulator.generate import build_negative_stream
from packages.simulator.negative import SCENARIOS


def _all_negative_control_samples():
    runs = [(None, build_negative_stream(seed=42, scenario=s, hours=3)) for s in SCENARIOS]
    return build_dataset(runs)


class TestNegativeControlsAreActuallyEvaluated:
    def test_each_scenario_split_is_non_empty_and_contains_its_own_scenario(self):
        samples = _all_negative_control_samples()
        splits = negative_control_splits(samples)
        assert set(splits) == set(SCENARIOS)
        for scenario, split in splits.items():
            assert split.n > 0, f"{scenario}: split is empty"
            assert all(s.scenario == scenario for s in split.samples)

    def test_always_positive_scorer_fp_count_equals_n_legitimate_exactly(self):
        samples = _all_negative_control_samples()
        splits = negative_control_splits(samples)
        scorer = AlwaysPositiveScorer()

        for scenario, split in splits.items():
            n_legitimate = sum(1 for s in split.samples if not s.is_attack)
            fp_count = sum(1 for s in split.samples if not s.is_attack and scorer(s) >= 0.5)
            assert fp_count == n_legitimate, (
                f"{scenario}: AlwaysPositiveScorer FP count {fp_count} != "
                f"n_legitimate {n_legitimate} -- a split that never arrived "
                f"cannot report 0 FPs and silently pass"
            )
            assert n_legitimate > 0, f"{scenario}: no legitimate samples -- test is vacuous"
