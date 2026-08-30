"""
Source: Day-7 Plan §4 Step 7 / §6, acceptance row 14 (Impl Plan §Day 7 / Eval
§5). The Tier-E search:

  * terminates within its hard bounds (`budget` OR `patience`),
  * is deterministic -- the same `(seed, budget)` reproduces the same vector
    and the same trace,
  * searches ONLY the six parameters `generate_attack_episode` consumes,
  * `episode_truth.evasion_params` is non-NULL for the Tier-E episode after
    `load_truth`.

Uses a pure STUB objective -- no scorer, no network -- so it is fast and
hermetic. `scripts/search_evasive.py` supplies the real detector callback.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.load import load_truth
from packages.simulator.evade import (
    SEARCH_FIELDS,
    EpisodeOutcome,
    SearchSpace,
    render_evasive_yaml_text,
    search,
)
from packages.simulator.generate import build_stream
from packages.storage.db import connect, initialize_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def _stub_evaluate(params: dict) -> EpisodeOutcome:
    """Deterministic function of the candidate -- feasible for some, not all."""
    mean_score = (params["attempts_per_hour"] % 100) / 500.0          # 0.000 .. 0.198
    incident = params["ip_pool_size"] < 4                              # a real constraint
    cvph = params["distinct_cards"] / 10.0
    return EpisodeOutcome(
        mean_score_calibrated=mean_score,
        incident_opened=incident,
        cards_validated_per_hour=cvph,
        attempts_total=int(params["attempts_per_hour"]),
    )


class TestEvadeSearch:
    def test_search_terminates_within_budget(self):
        result = search(
            seed=42, budget=20, patience=100, theta_challenge=0.3,
            evaluate_fn=_stub_evaluate, space=SearchSpace(),
        )
        assert result.n_evaluated <= 20
        assert result.stopped_reason in ("budget", "patience")

    def test_search_terminates_on_patience(self):
        result = search(
            seed=7, budget=10_000, patience=15, theta_challenge=0.3,
            evaluate_fn=_stub_evaluate, space=SearchSpace(),
        )
        assert result.stopped_reason == "patience"
        assert result.n_evaluated < 10_000

    def test_search_is_deterministic_at_one_seed(self):
        a = search(seed=42, budget=25, patience=100, theta_challenge=0.3,
                   evaluate_fn=_stub_evaluate, space=SearchSpace())
        b = search(seed=42, budget=25, patience=100, theta_challenge=0.3,
                   evaluate_fn=_stub_evaluate, space=SearchSpace())
        assert a.best_params == b.best_params
        assert a.best_objective == b.best_objective
        assert [t["params"] for t in a.trace] == [t["params"] for t in b.trace]

    def test_only_the_six_consumed_parameters_are_searched(self):
        result = search(seed=1, budget=5, patience=100, theta_challenge=1.0,
                        evaluate_fn=_stub_evaluate, space=SearchSpace())
        assert result.best_params is not None
        assert set(result.best_params) == {
            "attempts_per_hour", "ip_pool_size", "distinct_cards",
            "bin_pool_size", "amount_quantile_band", "episode_duration_s",
        }
        assert set(result.best_params["amount_quantile_band"]) == {"min", "max"}
        assert result.best_params["amount_quantile_band"]["min"] < result.best_params["amount_quantile_band"]["max"]
        assert set(SEARCH_FIELDS) == {
            "attempts_per_hour", "ip_pool_size", "distinct_cards", "bin_pool_size",
            "amount_band_min", "amount_band_max", "episode_duration_s",
        }

    def test_yaml_block_is_parseable_and_a10_clean(self):
        import re

        import yaml

        params = {
            "attempts_per_hour": 866, "ip_pool_size": 77, "distinct_cards": 286,
            "bin_pool_size": 19, "amount_quantile_band": {"min": 0, "max": 26},
            "episode_duration_s": 704,
        }
        text = render_evasive_yaml_text(params, seed=42, budget=200)
        block = yaml.safe_load(text)["evasive"]
        assert "pending" not in block
        banned = re.compile(r"\b(synthetic|made[- ]up|arbitrary|placeholder|guess(ed)?|n/a|unknown|tbd|todo)\b", re.I)
        shape = re.compile(r"(§\s?\d|Decision\s+\d+|doi:\s?10\.|\bv2\.?1?\b.*§)", re.I)
        for name, leaf in block.items():
            if isinstance(leaf, dict) and "value" in leaf:
                src = leaf["source"]
                assert len(src) >= 12 and not banned.search(src) and shape.search(src), (name, src)

    def test_evasion_params_persisted_after_load_truth(self, tmp_path):
        db = tmp_path / "te.db"
        initialize_schema(db, SCHEMA_PATH)
        merchant_id = "m-te"
        conn = connect(db)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
                "api_key_hash, outcome_hmac_key_hash, created_at) "
                "VALUES (?, 'te', 'INR', 'Asia/Kolkata', 'k', 'k', 0)",
                (merchant_id,),
            )
            conn.commit()
        finally:
            conn.close()

        output = build_stream(seed=42, tier="evasive", hours=3)
        assert output.episodes[0].evasion_params is not None

        conn = connect(db)
        try:
            load_truth(conn, merchant_id, [("evasive", output)])
            row = conn.execute(
                "SELECT evasion_params FROM episode_truth WHERE tier = 'evasive'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["evasion_params"] is not None
        parsed = json.loads(row["evasion_params"])
        assert set(parsed) == {
            "attempts_per_hour", "ip_pool_size", "distinct_cards",
            "bin_pool_size", "amount_quantile_band", "episode_duration_s",
        }
