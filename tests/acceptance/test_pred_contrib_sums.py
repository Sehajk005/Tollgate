"""
Source: Day-5 Plan §7 test 6 -- AC 5 / TRD §6.9. LightGBM `pred_contrib=True`
returns 25 values (24 features + bias) that must sum to the raw margin. This
is what makes `attempt_score.top_contributors` a faithful decomposition of
the score, not a heuristic. Checked over >= 100 real corpus rows.
"""

from __future__ import annotations

from pathlib import Path

from eval.corpus import load_feature_corpus
from packages.detect.model import FEATURE_ORDER, Layer1Model
from packages.storage.db import connect

MIN_ROWS = 100


class TestPredContribSums:
    def test_contributions_sum_to_the_margin(self, day5_corpus, day5_model):
        model = Layer1Model.load(Path(day5_model))
        conn = connect(day5_corpus)
        try:
            corpus = load_feature_corpus(conn)
        finally:
            conn.close()
        rows = list(corpus.values())[: max(MIN_ROWS, 250)]
        assert len(rows) >= MIN_ROWS, "corpus has too few rows for this test"

        for fr in rows:
            margin, contribs = model.score_one(fr.x)
            assert len(contribs) == len(FEATURE_ORDER) + 1, (
                f"expected {len(FEATURE_ORDER) + 1} contributions (features + bias), got {len(contribs)}"
            )
            assert abs(sum(contribs) - margin) < 1e-6, (
                f"sum(contributions)={sum(contribs)} != margin={margin}"
            )
