"""
Source: Day-6 Plan §4 / TRD §6.5 -- "h is tuned on NEGATIVE CONTROLS ONLY".

  * the tuner's provenance names ONLY the negative-control merchants
  * no episode_truth row with kind='attack' is in the read set
  * an AST + source scan on scripts/tune_cusum.py: it never references the
    attack-tier / stream construction
"""

from __future__ import annotations

import ast
from pathlib import Path

from packages.storage.db import connect
from scripts.tune_cusum import tune

REPO_ROOT = Path(__file__).resolve().parents[2]
TUNER_SRC = REPO_ROOT / "scripts" / "tune_cusum.py"
NEGATIVE_CONTROL_MERCHANTS = {f"m-eval-{i:02d}" for i in range(12, 19)}

_FORBIDDEN_SUBSTRINGS = ("build_stream", "build_negative_stream", "generate_attack", "attack_tiers")
_FORBIDDEN_LITERALS = {"attack", "easy", "medium", "hard"}


class TestCusumTuningIsolation:
    def test_provenance_names_only_negative_control_merchants(self, day5_corpus):
        tuned_h, prov, thresholds = tune(day5_corpus)
        assert tuned_h > 5.0, "tuner did not move cusum_h off its 5.0 placeholder"
        assert set(prov.merchant_ids_read) == NEGATIVE_CONTROL_MERCHANTS
        assert set(prov.scenarios) == {
            "flash_sale", "corporate_nat", "cgnat", "retry_storm",
            "subscription_batch", "nri_traffic", "shared_ip_legit",
        }
        assert prov.false_alarms_at_tuned_h == 0
        assert thresholds["throttle"] == prov.tau_flag

    def test_no_kind_attack_row_is_reachable_from_the_read_merchants(self, day5_corpus):
        _, prov, _ = tune(day5_corpus)
        conn = connect(day5_corpus)
        try:
            placeholders = ",".join("?" for _ in prov.merchant_ids_read)
            rows = conn.execute(
                f"""
                SELECT DISTINCT e.kind
                FROM auth_attempt a
                JOIN attempt_label l ON a.attempt_uid = l.attempt_uid
                JOIN episode_truth e ON l.episode_id = e.episode_id
                WHERE a.merchant_id IN ({placeholders})
                """,
                tuple(prov.merchant_ids_read),
            ).fetchall()
        finally:
            conn.close()
        assert {r["kind"] for r in rows} == {"negative_control"}

    def test_the_tuner_source_never_references_attack_tier_construction(self):
        src = TUNER_SRC.read_text(encoding="utf-8")
        for token in _FORBIDDEN_SUBSTRINGS:
            assert token not in src, f"tune_cusum.py references {token!r}"

        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                assert "simulator" not in mod, f"tune_cusum.py imports {mod}"
                assert not any("simulator" in n for n in names)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in _FORBIDDEN_LITERALS, (
                    f"tune_cusum.py contains the literal {node.value!r}"
                )
