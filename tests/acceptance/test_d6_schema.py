"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §18 / §24.3 -- the D6 artifact
schema contract.

`eval/d6_schema.py::validate()` must (a) accept the committed `eval/outputs/d6.json`
with zero errors, (b) reject each deliberately-malformed mutation of it with a
named, path-anchored error, and (c) have a spec entry for every leaf the real
artifact carries (no silently-unvalidated field -- an unknown key is an error).

Mutations are applied to an in-memory deep copy; `eval/outputs/d6.json` is never
edited (asserted: its SHA-256 is unchanged after this module runs).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from eval.d6_schema import (
    SUPPORTED_SCHEMA_VERSIONS,
    validate,
    validate_or_raise,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"

_SHA_AT_IMPORT = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


class TestSchemaAcceptsRealArtifact:
    def test_committed_artifact_validates_clean(self, committed):
        errors = validate(committed)
        assert errors == [], "\n  - ".join(["committed d6.json failed validation:"] + errors)

    def test_validate_or_raise_does_not_raise(self, committed):
        validate_or_raise(committed)  # must not raise

    def test_schema_version_is_supported(self, committed):
        assert committed["schema_version"] in SUPPORTED_SCHEMA_VERSIONS


class TestSchemaRejectsMalformed:
    """Every mutation must produce at least one error whose text names the
    offending path (plan §18.5)."""

    def _expect_named(self, committed, mutate, *needles):
        a = copy.deepcopy(committed)
        mutate(a)
        errors = validate(a)
        assert errors, f"expected a validation error for mutation {needles}"
        joined = "\n".join(errors)
        for needle in needles:
            assert needle in joined, f"error list does not name {needle!r}:\n{joined}"

    def test_missing_provenance(self, committed):
        self._expect_named(committed, lambda a: a.pop("provenance"), "provenance")

    def test_missing_block(self, committed):
        self._expect_named(committed, lambda a: a.pop("block3_audit"), "block3_audit")

    def test_malformed_curve_is_empty(self, committed):
        self._expect_named(
            committed,
            lambda a: a["block4_cost"].__setitem__("curve_pi0", []),
            "block4_cost.curve_pi0",
        )

    def test_wrong_schema_version(self, committed):
        self._expect_named(
            committed, lambda a: a.__setitem__("schema_version", 99),
            "schema_version", "99",
        )

    def test_wrong_scalar_type(self, committed):
        self._expect_named(
            committed,
            lambda a: a["block1_per_tier"]["l1-lgbm-v1"]["easy"].__setitem__("ap_raw", "lots"),
            "block1_per_tier.l1-lgbm-v1.easy.ap_raw",
        )

    def test_disallowed_null(self, committed):
        self._expect_named(
            committed,
            lambda a: a["block1_per_tier"]["l1-lgbm-v1"]["easy"]["recall_at_target_fpr"]
            .__setitem__("resolvable", None),
            "recall_at_target_fpr.resolvable",
        )

    def test_unknown_key(self, committed):
        self._expect_named(
            committed, lambda a: a["block4_cost"].__setitem__("surprise_field", 1),
            "block4_cost.surprise_field", "unknown key",
        )

    def test_int_field_given_a_float(self, committed):
        self._expect_named(
            committed, lambda a: a["block5_calibration"].__setitem__("n_bins", 10.5),
            "block5_calibration.n_bins",
        )

    def test_bool_field_given_a_string(self, committed):
        self._expect_named(
            committed,
            lambda a: a["block4_cost"].__setitem__("optima_coincident", "yes"),
            "block4_cost.optima_coincident",
        )

    def test_direction_enum_violation(self, committed):
        feat = next(iter(committed["block3_audit"]["features"]))
        self._expect_named(
            committed,
            lambda a: a["block3_audit"]["features"][feat].__setitem__("direction", "sideways"),
            f"block3_audit.features.{feat}.direction",
        )


def test_source_file_is_not_edited_by_this_module():
    # A test must never mutate the committed artifact on disk.
    assert hashlib.sha256(ARTIFACT.read_bytes()).hexdigest() == _SHA_AT_IMPORT
