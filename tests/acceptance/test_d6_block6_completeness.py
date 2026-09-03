"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md FIX-BE-03 / §24.3 -- "Baseline
comparison" must have a subject (the model row), a B3 sanity floor with reasons,
and a per-tier matrix whose confusion counts sum exactly to the overall counts
(the guard against a re-run-per-tier bitemporal bug).

Reads the committed `eval/outputs/d6.json` (schema v2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"

_CONF = ("tp", "fp", "tn", "fn")


@pytest.fixture(scope="module")
def block6() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["block6_baselines"]


def test_model_b0_b1_b2_all_present(block6):
    for key in ("model", "b0", "b1", "b2"):
        assert block6.get(key) is not None, key


def test_model_row_has_real_numbers(block6):
    m = block6["model"]
    assert m["split"] == "temporal_test"
    assert isinstance(m["ap_raw"], float) and 0.0 <= m["ap_raw"] <= 1.0
    assert isinstance(m["roc_auc"], float)
    assert m["recall_at_target_fpr"]["resolvable"] is False  # n_neg 758 < 1000


def test_b3_sanity_floor_present_on_b1_and_b2_with_a_reason_on_the_null(block6):
    for anchor in ("b1_sanity_floor", "b2_sanity_floor"):
        floor = block6[anchor]
        assert set(floor) == {"perfect", "random", "inverted", "always_positive"}, anchor
        ap = floor["always_positive"]
        assert ap["value"] is None
        assert ap["available"] is False
        assert isinstance(ap["reason"], str) and "unreachable" in ap["reason"].lower()
        assert floor["perfect"]["value"] is not None
        assert floor["perfect"]["available"] is True


def test_per_tier_has_all_four_tiers(block6):
    assert sorted(block6["per_tier"]) == ["easy", "evasive", "hard", "medium"]


def test_per_tier_has_four_series_each(block6):
    for tier, row in block6["per_tier"].items():
        assert set(row) == {"model", "b0", "b1", "b2"}, tier


def test_per_tier_b1_confusion_counts_sum_to_overall(block6):
    overall = block6["b1"]
    for k in _CONF:
        s = sum(block6["per_tier"][t]["b1"][k] for t in ("easy", "medium", "hard"))
        assert s == overall[k], f"b1 {k}: per-tier sum {s} != overall {overall[k]}"


def test_per_tier_b2_confusion_counts_sum_to_overall(block6):
    overall = block6["b2"]
    for k in _CONF:
        s = sum(block6["per_tier"][t]["b2"][k] for t in ("easy", "medium", "hard"))
        assert s == overall[k], f"b2 {k}: per-tier sum {s} != overall {overall[k]}"


def test_per_tier_row_totals_match_the_tier_sample_counts(block6):
    expected = {"easy": 821, "medium": 701, "hard": 603, "evasive": 390}
    for tier, n in expected.items():
        b1 = block6["per_tier"][tier]["b1"]
        assert sum(b1[k] for k in _CONF) == n, tier


def test_legacy_sanity_recall_paths_retained_for_compatibility(block6):
    assert "sanity_recall_at_b1_fpr" in block6
    assert "sanity_recall_at_b2_fpr" in block6
