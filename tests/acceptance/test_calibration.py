"""
Source: Day-5 Plan §7 test 5 -- AC 4 / Eval Protocol §3, §11/R5. On
`temporal_test`, evaluated with the Platt calibrator fit on the held-out
`calib` slice:
  * Platt improves Brier at the serving prior pi0 (the regime Day-5's live
    path always runs in -- `in_control`), and on the calib slice unweighted.
  * Prior correction reduces ECE at pi1 (the well-conditioned criterion --
    the reweighting at pi0 is extreme, §11/R5).
  * Every calibrated output lies in [0, 1], including fuzzed extreme margins.
  * Reliability observed-rate is non-decreasing across non-empty bins at both
    regimes.
"""

from __future__ import annotations

import random
from pathlib import Path

from eval.corpus import build_runs, load_feature_corpus
from eval.cost import load_cost_model
from eval.dataset import (
    build_dataset,
    compute_entity_overlap,
    exclude_negative_controls,
    temporal_split,
)
from eval.metrics import brier, ece, prevalence_weights, reliability_bins
from packages.detect.calibrate import Calibrator, prior_correct, sigmoid
from packages.detect.model import Layer1Model
from packages.storage.db import connect
from scripts.train_l1 import three_way_temporal_slice

SEED = 42


def _margins_labels(samples, model, features):
    pairs = [
        (features[(s.run_index, s.event_id)], s.is_attack)
        for s in samples
        if (s.run_index, s.event_id) in features
    ]
    return [model.margin(fr.x) for fr, _ in pairs], [bool(lbl) for _, lbl in pairs]


class TestCalibration:
    def _load(self, day5_corpus, day5_model):
        model = Layer1Model.load(Path(day5_model))
        calib = Calibrator.load(Path(day5_model) / "platt-v1.json")
        runs = build_runs(SEED)
        conn = connect(day5_corpus)
        try:
            features = load_feature_corpus(conn)
        finally:
            conn.close()
        samples = compute_entity_overlap(build_dataset([(r.stream_tier, r.output) for r in runs]))
        temporal_train, temporal_test = temporal_split(samples, train_fraction=0.7)
        train = [
            s for s in exclude_negative_controls(temporal_train).samples
            if s.stream_tier in ("easy", "medium")
        ]
        _, _, calib_split = three_way_temporal_slice(train)
        return model, calib, features, temporal_test, calib_split

    def test_platt_improves_brier_at_the_serving_prior_and_on_calib(self, day5_corpus, day5_model):
        model, calib, features, temporal_test, calib_split = self._load(day5_corpus, day5_model)
        cm = load_cost_model()

        m_te, y_te = _margins_labels(temporal_test.samples, model, features)
        raw = [sigmoid(x) for x in m_te]
        platt = [sigmoid(calib.a * x + calib.b) for x in m_te]
        w0 = prevalence_weights(y_te, cm.prior_steady_state)
        assert brier(platt, y_te, weights=w0) < brier(raw, y_te, weights=w0), (
            "Platt did not improve Brier at pi0 (the in_control serving regime) on temporal_test"
        )

        m_c, y_c = _margins_labels(calib_split.samples, model, features)
        raw_c = [sigmoid(x) for x in m_c]
        platt_c = [sigmoid(calib.a * x + calib.b) for x in m_c]
        assert brier(platt_c, y_c) < brier(raw_c, y_c), (
            "Platt's Brier on its own held-out calib slice is not below raw's"
        )

    def test_prior_correction_reduces_ece_at_pi1(self, day5_corpus, day5_model):
        model, calib, features, temporal_test, _ = self._load(day5_corpus, day5_model)
        cm = load_cost_model()
        m_te, y_te = _margins_labels(temporal_test.samples, model, features)
        platt = [sigmoid(calib.a * x + calib.b) for x in m_te]
        platt_pc = [prior_correct(p, calib.pi_t, cm.prior_under_attack) for p in platt]
        w1 = prevalence_weights(y_te, cm.prior_under_attack)
        assert ece(platt_pc, y_te, n_bins=calib.ece_bins, weights=w1) < ece(
            platt, y_te, n_bins=calib.ece_bins, weights=w1
        ), "prior-corrected ECE at pi1 is not below uncorrected ECE at pi1"

    def test_all_calibrated_outputs_are_in_the_unit_interval_including_extremes(self, day5_model):
        calib = Calibrator.load(Path(day5_model) / "platt-v1.json")
        cm = load_cost_model()
        rng = random.Random(SEED)
        margins = [-1e9, -1e6, -1e3, -50.0, -1.0, 0.0, 1.0, 50.0, 1e3, 1e6, 1e9]
        margins += [rng.uniform(-200.0, 200.0) for _ in range(2000)]
        for mg in margins:
            for pi_s in (cm.prior_steady_state, cm.prior_under_attack, 0.5):
                p = calib.apply(mg, pi_s)
                assert 0.0 <= p <= 1.0, f"calibrator.apply({mg}, {pi_s}) = {p} outside [0,1]"
            assert 0.0 <= sigmoid(calib.a * mg + calib.b) <= 1.0

    def test_reliability_observed_rate_is_non_decreasing_at_both_regimes(self, day5_corpus, day5_model):
        model, calib, features, temporal_test, _ = self._load(day5_corpus, day5_model)
        cm = load_cost_model()
        m_te, y_te = _margins_labels(temporal_test.samples, model, features)
        platt = [sigmoid(calib.a * x + calib.b) for x in m_te]
        for pi_s in (cm.prior_steady_state, cm.prior_under_attack):
            pc = [prior_correct(p, calib.pi_t, pi_s) for p in platt]
            w = prevalence_weights(y_te, pi_s)
            bins = [
                b for b in reliability_bins(pc, y_te, n_bins=calib.ece_bins, weights=w)
                if b.weight > 1e-6
            ]
            obs = [b.observed_rate for b in bins]
            assert all(obs[i] <= obs[i + 1] + 1e-6 for i in range(len(obs) - 1)), (
                f"reliability observed-rate not non-decreasing at pi_s={pi_s}: {obs}"
            )


# ---------------------------------------------------------------------------
# Source: METRICS-REMEDIATION-PLAN-2026-09-02.md FIX-BE-04 / §24.4 -- raw ECE
# completes Eval Protocol §3.4's {raw, Platt, Platt+prior} triple. The metric
# itself (`eval/metrics.py::ece`) is unchanged; these pin the new artifact
# fields and give `ece()` a hand-computable anchor.
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

import pytest  # noqa: E402

_ARTIFACT = _Path(__file__).resolve().parents[2] / "eval" / "outputs" / "d6.json"


def test_ece_hand_computed_on_a_four_sample_example():
    # 2 bins. bin A preds 0.1,0.3 labels 0,0 -> mean 0.2, obs 0.0, |gap| 0.2, w 2.
    #         bin B preds 0.6,0.9 labels 1,0 -> mean 0.75, obs 0.5, |gap| 0.25, w 2.
    # ECE = (2/4)*0.2 + (2/4)*0.25 = 0.225
    assert ece([0.1, 0.3, 0.6, 0.9], [False, False, True, False], n_bins=2) == pytest.approx(
        0.225, abs=1e-12
    )


def test_committed_artifact_carries_ece_raw_at_both_regimes():
    b5 = _json.loads(_ARTIFACT.read_text(encoding="utf-8"))["block5_calibration"]
    for regime in ("pi0", "pi1"):
        r = b5[regime]
        assert isinstance(r["ece_raw"], float) and 0.0 <= r["ece_raw"] <= 1.0, regime
        assert r["ece_gap_platt_prior_vs_platt"] == pytest.approx(
            r["ece_platt"] - r["ece_platt_prior"], abs=1e-12
        ), regime


def test_prior_correction_verdict_agrees_with_the_pi1_ece_comparison():
    b5 = _json.loads(_ARTIFACT.read_text(encoding="utf-8"))["block5_calibration"]
    r1 = b5["pi1"]
    assert b5["prior_correction_helped_at_pi1"] == (r1["ece_platt"] > r1["ece_platt_prior"])
    assert b5["prior_correction_helped_at_pi1"] is True


def test_the_four_pre_existing_calibration_numbers_are_unchanged():
    b5 = _json.loads(_ARTIFACT.read_text(encoding="utf-8"))["block5_calibration"]
    assert b5["pi0"]["ece_platt"] == pytest.approx(0.07031799883085593, abs=1e-15)
    assert b5["pi0"]["ece_platt_prior"] == pytest.approx(0.0007305349387266664, abs=1e-15)
    assert b5["pi1"]["ece_platt"] == pytest.approx(0.39547724058805567, abs=1e-15)
    assert b5["pi1"]["ece_platt_prior"] == pytest.approx(0.2806765620747161, abs=1e-15)
