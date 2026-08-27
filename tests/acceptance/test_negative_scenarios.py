"""
Source: Day-4 Plan (rev. 2) §6 test 14 -- "Seven controls, canonical
names." All seven generate non-empty streams; names match schema.sql's
CHECK list exactly (F17); nri_traffic BINs subset FOREIGN_BIN_POOL,
disjoint from FICTIONAL_BIN_POOL; shared_ip_legit yields >=1 legitimate
sample on the attacker's IP with entity_overlap == True.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from packages.simulator.generate import build_negative_stream
from packages.simulator.identity import FICTIONAL_BIN_POOL, FOREIGN_BIN_POOL
from packages.simulator.negative import SCENARIOS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


def _schema_check_scenario_names() -> set:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(r"scenario\s+TEXT\s+CHECK.*?IN\s*\((.*?)\)\s*\)", text, re.DOTALL)
    assert match, "could not find episode_truth.scenario CHECK constraint in schema.sql"
    names = re.findall(r"'([a-z_]+)'", match.group(1))
    return set(names)


class TestSevenNegativeControlsCanonicalNames:
    def test_names_match_schema_check_list_exactly(self):
        assert set(SCENARIOS) == _schema_check_scenario_names()

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_scenario_generates_a_non_empty_stream(self, scenario):
        result = build_negative_stream(seed=42, scenario=scenario, hours=1)
        assert result.events, f"{scenario} produced no events"
        assert len(result.episodes) == 1
        episode = result.episodes[0]
        assert episode.kind == "negative_control"
        assert episode.tier is None
        assert episode.scenario == scenario

    def test_schema_sql_accepts_every_canonical_name_and_rejects_a_bogus_one(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        for i, name in enumerate(SCENARIOS):
            conn.execute(
                "INSERT INTO episode_truth (episode_id, kind, tier, scenario, started_at, "
                "ended_at, attempt_count, distinct_cards, generator_seed) "
                "VALUES (?, 'negative_control', NULL, ?, '2026-01-01T00:00:00', "
                "'2026-01-01T00:01:00', 1, 1, 42)",
                (f"ep-{i}", name),
            )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO episode_truth (episode_id, kind, tier, scenario, started_at, "
                "ended_at, attempt_count, distinct_cards, generator_seed) "
                "VALUES ('ep-bogus', 'negative_control', NULL, 'not_a_real_scenario', "
                "'2026-01-01T00:00:00', '2026-01-01T00:01:00', 1, 1, 42)"
            )
        conn.close()

    def test_nri_traffic_bins_subset_foreign_pool_disjoint_from_fictional_pool(self):
        result = build_negative_stream(seed=42, scenario="nri_traffic", hours=1)
        bins_used = {e.bin for e in result.events}
        assert bins_used, "nri_traffic produced no BINs"
        assert bins_used <= set(FOREIGN_BIN_POOL)
        assert not (bins_used & set(FICTIONAL_BIN_POOL))

    def test_shared_ip_legit_has_a_legit_sample_on_attacker_ip_with_entity_overlap(self):
        from eval.dataset import build_dataset, compute_entity_overlap

        result = build_negative_stream(seed=42, scenario="shared_ip_legit", hours=1)
        samples = compute_entity_overlap(build_dataset([("shared_ip_legit", result)]))

        attack_ips = {s.ip for s in samples if s.is_attack}
        legit_on_attacker_ip = [
            s for s in samples if not s.is_attack and s.ip in attack_ips
        ]
        assert legit_on_attacker_ip, "no legitimate sample found on the attacker's own IP"
        assert any(s.entity_overlap for s in legit_on_attacker_ip), (
            "expected at least one legitimate sample on the attacker's IP with entity_overlap=True"
        )
