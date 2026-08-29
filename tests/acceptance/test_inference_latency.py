"""
Source: Day-5 Plan §7 test 7 -- AC 6 / Impl Plan Day 5. The Layer-1 serving
step (score_one -> calibrator.apply -> prior_correct) must fit inside the
score-path latency budget: p99 < 5 ms over 1,000 single-row calls at
num_threads=1. Marked `slow` (1,000 real LightGBM predictions).
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter_ns

import pytest

from eval.corpus import load_feature_corpus
from eval.cost import load_cost_model
from packages.detect.calibrate import Calibrator, prior_correct
from packages.detect.model import Layer1Model
from packages.storage.db import connect

pytestmark = pytest.mark.slow

N_CALLS = 1000
P99_BUDGET_MS = 5.0


class TestInferenceLatency:
    def test_p99_single_call_latency_is_under_5ms(self, day5_corpus, day5_model):
        model = Layer1Model.load(Path(day5_model))
        calib = Calibrator.load(Path(day5_model) / "platt-v1.json")
        cm = load_cost_model()
        conn = connect(day5_corpus)
        try:
            corpus = load_feature_corpus(conn)
        finally:
            conn.close()
        vectors = [fr.x for fr in list(corpus.values())[:N_CALLS]]
        i = 0
        while len(vectors) < N_CALLS:
            vectors.append(vectors[i % max(1, len(vectors))])
            i += 1

        for x in vectors[:20]:  # warm-up (first predict pays one-time setup)
            margin, _ = model.score_one(x)
            prior_correct(calib.apply(margin, cm.prior_steady_state), calib.pi_t, cm.prior_steady_state)

        samples_ms = []
        for x in vectors[:N_CALLS]:
            t0 = perf_counter_ns()
            margin, _contribs = model.score_one(x)
            p = calib.apply(margin, cm.prior_steady_state)
            _ = prior_correct(p, calib.pi_t, cm.prior_steady_state)
            samples_ms.append((perf_counter_ns() - t0) / 1e6)

        samples_ms.sort()
        p99 = samples_ms[int(0.99 * len(samples_ms)) - 1]
        assert p99 < P99_BUDGET_MS, (
            f"p99 single-call latency {p99:.3f} ms exceeds the {P99_BUDGET_MS} ms budget "
            f"(median {samples_ms[len(samples_ms) // 2]:.3f} ms, max {samples_ms[-1]:.3f} ms)"
        )
