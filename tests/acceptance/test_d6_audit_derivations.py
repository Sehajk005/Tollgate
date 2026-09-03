"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md FIX-BE-05 / §24.3 -- two-sided
discriminability is DERIVED downstream in `eval/d6.py::_augment_audit_block`,
never by retraining. `models/audit.json` must be byte-identical.

Reads the committed `eval/outputs/d6.json` (schema v2).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eval.d6 import _augment_audit_block

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "eval" / "outputs" / "d6.json"
AUDIT_JSON = REPO_ROOT / "models" / "audit.json"

# Recorded at Phase 1 start; see METRICS-IMPLEMENTATION-LOG.
_AUDIT_JSON_SHA = "ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c"


@pytest.fixture(scope="module")
def b3() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["block3_audit"]


def test_models_audit_json_is_untouched():
    assert hashlib.sha256(AUDIT_JSON.read_bytes()).hexdigest() == _AUDIT_JSON_SHA, (
        "models/audit.json changed -- separability must be derived downstream, not retrained"
    )


def test_separability_is_abs_auc_minus_half_for_every_feature(b3):
    feats = b3["features"]
    assert len(feats) == 24
    for name, f in feats.items():
        auc = f["univariate_auc"]
        if auc is None:
            assert f["separability"] is None
        else:
            assert f["separability"] == pytest.approx(abs(auc - 0.5), abs=1e-12), name


def test_direction_is_inverted_for_exactly_the_two_below_half_non_constant_features(b3):
    inverted = {name for name, f in b3["features"].items() if f["direction"] == "inverted"}
    assert inverted == {"bin_hhi_5m", "card_seen_24h"}, inverted


def test_constant_features_have_no_direction(b3):
    for name, f in b3["features"].items():
        if f["constant"]:
            assert f["direction"] is None, name


def test_card_seen_24h_keeps_its_raw_auc_and_gets_a_large_separability(b3):
    f = b3["features"]["card_seen_24h"]
    assert f["univariate_auc"] == pytest.approx(0.22475071225071225, abs=1e-12)
    assert f["separability"] == pytest.approx(0.27524928774928775, abs=1e-12)
    assert f["direction"] == "inverted"
    assert f["flagged_two_sided"] is False  # 0.275 < (0.95 - 0.5)


def test_observed_max_is_the_real_maximum_not_the_threshold(b3):
    assert b3["univariate_auc_threshold"] == 0.95
    assert b3["observed_max_univariate_auc"] == pytest.approx(0.9975874252835037, abs=1e-12)
    assert b3["observed_max_univariate_auc"] != b3["univariate_auc_threshold"]


def test_flagged_two_sided_is_a_subset_of_the_v1_flags_and_counts_six(b3):
    flagged = {n for n, f in b3["features"].items() if f["flagged_two_sided"]}
    also_flagged_v1 = {n for n, f in b3["features"].items() if f["flagged"]}
    assert flagged <= also_flagged_v1
    assert len(flagged) == 6


def test_boundary_at_exactly_0p95_is_flagged_two_sided():
    synthetic = {
        "max_univariate_auc": 0.95,
        "features": {
            "on_boundary": {"univariate_auc": 0.95, "constant": False,
                            "excluded": False, "flagged": True, "reason": None},
            "just_under": {"univariate_auc": 0.9499999, "constant": False,
                           "excluded": False, "flagged": False, "reason": None},
            "inverted_boundary": {"univariate_auc": 0.05, "constant": False,
                                  "excluded": False, "flagged": False, "reason": None},
        },
    }
    out = _augment_audit_block(synthetic)
    assert out["features"]["on_boundary"]["flagged_two_sided"] is True
    assert out["features"]["just_under"]["flagged_two_sided"] is False
    assert out["features"]["inverted_boundary"]["flagged_two_sided"] is True
    assert out["features"]["inverted_boundary"]["direction"] == "inverted"


def test_augment_does_not_mutate_its_input():
    src = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    before = json.dumps(src, sort_keys=True)
    _augment_audit_block(src)
    assert json.dumps(src, sort_keys=True) == before
