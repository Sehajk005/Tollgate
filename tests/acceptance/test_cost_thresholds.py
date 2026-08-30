"""
Source: Day-4 Plan (rev. 2) §6 test 1 -- "Tier ladder from YAML."
`round(theta, 3) == {0.065, 0.257, 0.509, 0.874}`; monotone; recomputed
from YAML, never hardcoded.
"""

from __future__ import annotations

import yaml

from eval.cost import TIER_ORDER, load_cost_model

EXPECTED_ROUNDED = {
    "throttle": 0.065,
    "challenge": 0.257,
    "step_up": 0.509,
    "block": 0.874,
}


class TestCostThresholds:
    def test_tier_ladder_matches_hand_computed_arithmetic(self):
        model = load_cost_model()
        ladder = model.tier_ladder()
        for tier in TIER_ORDER:
            assert round(ladder[tier], 3) == EXPECTED_ROUNDED[tier], (
                f"{tier}: theta={ladder[tier]!r} rounds to {round(ladder[tier], 3)}, "
                f"expected {EXPECTED_ROUNDED[tier]}"
            )

    def test_tier_ladder_is_monotone(self):
        model = load_cost_model()
        ladder = model.tier_ladder()
        values = [ladder[t] for t in TIER_ORDER]
        assert values == sorted(values), f"ladder not monotone: {values}"

    def test_ladder_is_recomputed_from_yaml_not_hardcoded(self, tmp_path):
        # A perturbed copy of the cost model must move the ladder -- proves
        # tier_ladder() is a live computation, not a cached/hardcoded table.
        from eval.cost import DEFAULT_COST_MODEL_PATH

        raw = yaml.safe_load(DEFAULT_COST_MODEL_PATH.read_text(encoding="utf-8"))
        raw["abandonment_by_tier"]["throttle"]["value"] = 0.5
        perturbed = tmp_path / "cost_model.yaml"
        perturbed.write_text(yaml.safe_dump(raw), encoding="utf-8")

        original = load_cost_model()
        moved = load_cost_model(perturbed)
        assert moved.tier_ladder()["throttle"] != original.tier_ladder()["throttle"]

    def test_aov_minor_matches_store_profile(self):
        from packages.simulator.profile import load_store_profile

        model = load_cost_model()
        store_profile = load_store_profile()
        assert model.aov_minor == store_profile["aov_minor"]

    def test_seeded_policy_config_thresholds_equal_the_analytic_ladder(self, day5_corpus):
        # Source: Day-6 Plan §4 -- close the loop between the derived table
        # and what the serving path actually reads. scripts/tune_cusum.py
        # writes thresholds = CostModel.tier_ladder() into a new
        # policy_config version; that JSON column must round to the same
        # analytic ladder this file's other tests derive from YAML.
        import json

        from packages.storage.db import connect

        conn = connect(day5_corpus)
        try:
            row = conn.execute(
                "SELECT thresholds FROM policy_config "
                "WHERE merchant_id = 'm-eval-12' AND thresholds != '{}' "
                "ORDER BY version DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "no tuned policy_config with a thresholds table -- run scripts.tune_cusum"
        seeded = {k: round(v, 3) for k, v in json.loads(row["thresholds"]).items()}
        assert seeded == EXPECTED_ROUNDED
