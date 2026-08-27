"""
Source: Day-4 Plan (rev. 2) §6 test 12 -- "Provenance validates meaning."
Rejects model_version="v1" (not in vocabulary), config_hash="abc" (wrong
length), a hash that does not match a fresh recompute, eval_prevalence=0.0,
a policy_version absent from policy_config. Present-but-wrong must fail,
not just absent (F15).
"""

from __future__ import annotations

import pytest

from eval.provenance import ProvenanceError, RunProvenance, config_hash

VALID_HASH = config_hash()
AVAILABLE_VERSIONS = (1, 2)


def _valid() -> RunProvenance:
    return RunProvenance(
        model_version="none:perfect", config_hash=VALID_HASH, policy_version=1, eval_prevalence=0.01,
    )


class TestProvenanceValidatesMeaning:
    def test_a_valid_provenance_passes(self):
        _valid().validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_model_version_not_in_vocabulary(self):
        bad = RunProvenance(
            model_version="v1", config_hash=VALID_HASH, policy_version=1, eval_prevalence=0.01,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_config_hash_wrong_length(self):
        bad = RunProvenance(
            model_version="none:perfect", config_hash="abc", policy_version=1, eval_prevalence=0.01,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_config_hash_that_does_not_match_a_fresh_recompute(self):
        wrong_but_right_length = "0" * 64
        bad = RunProvenance(
            model_version="none:perfect", config_hash=wrong_but_right_length,
            policy_version=1, eval_prevalence=0.01,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_eval_prevalence_0_0(self):
        bad = RunProvenance(
            model_version="none:perfect", config_hash=VALID_HASH, policy_version=1, eval_prevalence=0.0,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_eval_prevalence_1_0(self):
        bad = RunProvenance(
            model_version="none:perfect", config_hash=VALID_HASH, policy_version=1, eval_prevalence=1.0,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_rejects_policy_version_absent_from_policy_config(self):
        bad = RunProvenance(
            model_version="none:perfect", config_hash=VALID_HASH, policy_version=999, eval_prevalence=0.01,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)

    def test_present_but_wrong_fails_not_just_absent(self):
        # A model_version that IS present (non-empty) but wrong-shaped
        # must still fail -- proves validate() checks meaning, not presence.
        bad = RunProvenance(
            model_version="totally-made-up-model", config_hash=VALID_HASH,
            policy_version=1, eval_prevalence=0.01,
        )
        with pytest.raises(ProvenanceError):
            bad.validate(policy_versions_available=AVAILABLE_VERSIONS)
