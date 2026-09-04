"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md FIX-BE-06 / M-029 / §24.3 --
provenance completeness and the freshness model (config + corpus + model
identity + generation metadata). `build_hash` divergence ALONE is not staleness.

Reads the committed `eval/outputs/d6.json` (schema v2).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"
CORPUS_DB = REPO_ROOT / "data" / "corpus" / "tollgate.db"

_EVAL9 = ("seed", "config_hash", "model_version", "policy_version", "eval_prevalence")


@pytest.fixture(scope="module")
def artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prov(artifact) -> dict:
    return artifact["provenance"]


def test_the_five_header_eval9_attributes_are_present_and_real(prov):
    for field in _EVAL9:
        assert prov.get(field) not in (None, ""), field
    assert prov["seed"] == 42
    assert prov["policy_version"] == 1
    assert 0.0 < prov["eval_prevalence"] < 1.0
    assert re.fullmatch(r"[0-9a-f]{64}", prov["config_hash"])


def test_split_name_is_reachable_per_block(artifact):
    assert artifact["block4_cost"]["split"] == "temporal_test"
    assert artifact["block6_baselines"]["b0"]["split"] == "temporal_test"
    for mv, tiers in artifact["block1_per_tier"].items():
        for tier, tm in tiers.items():
            if tm is None:
                continue
            assert tm["split"], f"{mv}.{tier} has no split label"
    assert artifact["block1_per_tier"]["l1-lgbm-v1"]["evasive"]["split"] == "tier_e"
    assert artifact["block1_per_tier"]["l1-lgbm-v1"]["easy"]["split"] == "temporal_test"


def test_seeds_used_is_surfaced(prov):
    assert prov["seeds_used"] == 1


def test_generated_at_parses_as_iso8601_utc(prov):
    dt = datetime.strptime(prov["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert dt.year >= 2026


def test_generation_command_records_the_argv(prov):
    assert "eval" in prov["generation_command"]
    assert "harness" in prov["generation_command"]


def test_corpus_identity_is_recorded_and_matches_the_real_corpus(prov):
    assert re.fullmatch(r"[0-9a-f]{64}", prov["corpus_db_sha256"])
    if CORPUS_DB.exists():
        direct = hashlib.sha256(CORPUS_DB.read_bytes()).hexdigest()
        assert prov["corpus_db_sha256"] == direct


def test_model_identity_is_recorded_for_every_model_file(prov):
    m = prov["model_files_sha256"]
    assert isinstance(m, dict) and m
    for name in ("audit.json", "l1-lgbm-v1.json", "l1-lgbm-v1.txt", "platt-v1.json"):
        assert name in m, name
        assert re.fullmatch(r"[0-9a-f]{64}", m[name])
    assert m["audit.json"] == hashlib.sha256(
        (REPO_ROOT / "models" / "audit.json").read_bytes()
    ).hexdigest()


def test_head_and_dirty_flag_present_but_not_used_as_a_staleness_alarm(prov):
    assert re.fullmatch(r"[0-9a-f]{7,40}", prov["head_at_generation"])
    assert isinstance(prov["tree_dirty_at_generation"], bool)
