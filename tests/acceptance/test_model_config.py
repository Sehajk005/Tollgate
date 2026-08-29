"""
Source: Day-5 Plan §7 test 8 -- AC 7 / TRD §6.9. The trained artifact must
record the mandated LightGBM configuration verbatim: `scale_pos_weight =
n_neg/n_pos` of the `fit` slice (no resampling), `num_boost_round == 200`,
`max_depth == 6`.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.corpus import build_runs, load_feature_corpus
from eval.dataset import (
    build_dataset,
    compute_entity_overlap,
    exclude_negative_controls,
    temporal_split,
)
from packages.storage.db import connect
from scripts.train_l1 import _matrix, load_features_config, three_way_temporal_slice

SEED = 42


class TestModelConfig:
    def test_scale_pos_weight_num_boost_round_and_max_depth(self, day5_corpus, day5_model):
        artifact = json.loads((Path(day5_model) / "l1-lgbm-v1.json").read_text(encoding="utf-8"))
        params = artifact["params"]

        assert "scale_pos_weight" in params, "params has no scale_pos_weight"
        assert params["scale_pos_weight"] > 0, "scale_pos_weight must be positive"
        assert params["num_boost_round"] == 200, f"num_boost_round={params['num_boost_round']} != 200"
        assert params["max_depth"] == 6, f"max_depth={params['max_depth']} != 6"

        cfg = load_features_config()
        excluded = tuple(sorted(cfg["excluded"].keys()))
        runs = build_runs(SEED)
        conn = connect(day5_corpus)
        try:
            features = load_feature_corpus(conn)
        finally:
            conn.close()
        samples = compute_entity_overlap(build_dataset([(r.stream_tier, r.output) for r in runs]))
        temporal_train, _ = temporal_split(samples, train_fraction=0.7)
        train = [
            s for s in exclude_negative_controls(temporal_train).samples
            if s.stream_tier in ("easy", "medium")
        ]
        fit_split, _, _ = three_way_temporal_slice(train)
        _, y_fit = _matrix(fit_split.samples, features, excluded)
        n_pos = int(y_fit.sum())
        n_neg = int(y_fit.size - n_pos)
        expected = n_neg / n_pos
        assert abs(params["scale_pos_weight"] - expected) < 1e-9, (
            f"scale_pos_weight {params['scale_pos_weight']} != n_neg/n_pos of the fit slice "
            f"({n_neg}/{n_pos} = {expected})"
        )
        assert artifact["n_train"] == int(y_fit.size)
        assert artifact["n_train_pos"] == n_pos
