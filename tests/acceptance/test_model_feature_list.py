"""
Source: Day-5 Plan §7 test 10 -- Threat Model §2/TB-1. §2's footer: "Test:
tests/acceptance/test_trust_boundary.py asserts the trained model's feature
list intersected with the C-class field set is empty." Until Day 5 there was
no trained model, so that test could only assert it against FEATURE_NAMES.
This file makes the assertion §2 actually asks for -- against the TRAINED
ARTIFACT's `feature_names`. `test_trust_boundary.py` is reused (its
C_CLASS_FIELDS), not edited.
"""

from __future__ import annotations

import json
from pathlib import Path

from packages.features.compute import FEATURE_NAMES
from tests.acceptance.test_trust_boundary import C_CLASS_FIELDS


class TestModelFeatureList:
    def test_trained_artifact_feature_names_equal_the_documented_24(self, day5_model):
        artifact = json.loads((Path(day5_model) / "l1-lgbm-v1.json").read_text(encoding="utf-8"))
        assert tuple(artifact["feature_names"]) == tuple(FEATURE_NAMES), (
            "the trained artifact's feature_names is not the 24-name FEATURE_NAMES contract, in order"
        )

    def test_trained_artifact_feature_names_never_intersect_c_class(self, day5_model):
        artifact = json.loads((Path(day5_model) / "l1-lgbm-v1.json").read_text(encoding="utf-8"))
        overlap = set(artifact["feature_names"]) & C_CLASS_FIELDS
        assert not overlap, f"C-class fields leaked into the trained model's feature list: {overlap}"
