"""
Source: Day-8 Plan Step 4 (G10) -- the committed D6 evaluation artifact.

  * `eval/outputs/d6.json` exists,
  * it is NOT git-ignored (`git check-ignore` returns non-zero -- Risk R5: if
    the .gitignore exception is forgotten, D6 renders on a dev machine and is
    empty on a clean clone),
  * every one of the six blocks plus `provenance` is present and non-empty.

The artifact is committed; this test reads the committed file, it does not
regenerate it (regeneration needs the model + corpus and is a separate,
slower path -- `test_d6_cost_gap.py` covers the numbers).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"

_SIX_BLOCKS = (
    "block1_per_tier",
    "block2_negative_controls",
    "block3_audit",
    "block4_cost",
    "block5_calibration",
    "block6_baselines",
)


@pytest.fixture(scope="module")
def artifact() -> dict:
    assert ARTIFACT.exists(), (
        f"{ARTIFACT} is missing -- run "
        "`python -m eval.harness --split all --seed 42 "
        "--corpus-db data/corpus/tollgate.db --model-dir models` and commit it"
    )
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


class TestD6Artifact:
    def test_artifact_is_committed_not_gitignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "eval/outputs/d6.json"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            "eval/outputs/d6.json is git-ignored -- the `!eval/outputs/d6.json` "
            f".gitignore exception is missing (git check-ignore said: {result.stdout!r})"
        )

    def test_all_six_blocks_and_provenance_present_and_non_empty(self, artifact):
        # Source: plan §8 / §26.1 -- the committed artifact is schema v2 (v1 -> v2
        # is additive; both are supported by consumers).
        from eval.d6_schema import SUPPORTED_SCHEMA_VERSIONS

        assert artifact.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS
        assert artifact.get("schema_version") == 2, (
            "the committed artifact should be regenerated at schema_version 2"
        )

        prov = artifact.get("provenance")
        assert isinstance(prov, dict) and prov, "provenance missing/empty"
        for field in (
            "build_hash", "config_hash", "model_version", "calibrator_version",
            "policy_version", "eval_prevalence", "fixture_sha256", "seed",
        ):
            assert prov.get(field) not in (None, ""), f"provenance.{field} missing"

        for block in _SIX_BLOCKS:
            v = artifact.get(block)
            assert isinstance(v, dict) and len(v) > 0, f"{block} missing or empty"

    def test_committed_artifact_passes_full_schema_validation(self, artifact):
        # Leaf validation (types, nullability, required fields, unknown keys) is
        # delegated to eval/d6_schema.py -- see test_d6_schema.py for the
        # rejection cases (plan §24.4).
        from eval.d6_schema import validate

        errors = validate(artifact)
        assert errors == [], "committed d6.json failed schema validation:\n  - " + "\n  - ".join(errors)

    def test_provenance_v2_completeness(self, artifact):
        # Source: plan §17.2 / M-029 -- the freshness model.
        from datetime import datetime

        prov = artifact["provenance"]
        for field in (
            "generated_at", "generation_command", "head_at_generation",
            "tree_dirty_at_generation", "model_files_sha256",
        ):
            assert field in prov, f"provenance.{field} missing at schema v2"
        datetime.strptime(prov["generated_at"], "%Y-%m-%dT%H:%M:%SZ")  # ISO-8601 UTC
        assert isinstance(prov["model_files_sha256"], dict) and prov["model_files_sha256"], (
            "model_files_sha256 should be populated when regenerated with --model-dir"
        )

    def test_block2_has_rows_for_negative_control_scenarios(self, artifact):
        b2 = artifact["block2_negative_controls"]
        # at least one scenario carries real per-scorer FP rows
        assert any(len(rows) > 0 for rows in b2.values()), b2
        for scenario, rows in b2.items():
            for row in rows:
                assert set(row) >= {"scorer", "episode_fp", "episodes", "attempt_fp", "attempts"}

    def test_block3_audit_carries_the_univariate_auc_table(self, artifact):
        b3 = artifact["block3_audit"]
        assert b3.get("max_univariate_auc") is not None
        assert isinstance(b3.get("features"), dict) and b3["features"]

    def test_tier_e_block_present(self, artifact):
        te = artifact.get("tier_e")
        assert isinstance(te, dict) and te
