"""
Source: Day-2 Plan §I characterization tests / Decision 37 -- "golden.jsonl
is still generated, so it is demoted to characterization duty only. The
determinism gates compare two fresh runs to each other, never to a
committed answer" (that comparison is A1-A4, tests/acceptance/
test_simulator_determinism.py). This file is the OTHER half: does
regenerating seed 42 still reproduce the committed golden fixture
byte-for-byte, and what do rules/decisions look like today. A change here
is a prompt to look, never a gate (pyproject.toml `characterization` marker).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.characterization


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_regenerating_seed_42_reproduces_golden_jsonl_byte_for_byte(tmp_path):
    out = tmp_path / "regenerated.jsonl"
    labels = tmp_path / "regenerated.labels.jsonl"
    episodes = tmp_path / "regenerated.episodes.jsonl"
    result = subprocess.run(
        [
            sys.executable, "-m", "packages.simulator.generate",
            "--seed", "42", "--tier", "easy", "--hours", "3", "--epoch-ms", "0",
            "--out", str(out), "--labels", str(labels), "--episodes", str(episodes),
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    golden = FIXTURES_DIR / "golden.jsonl"
    assert out.read_bytes() == golden.read_bytes(), (
        "regenerating seed 42 no longer reproduces the committed golden.jsonl byte-for-byte -- "
        "this is a prompt to regenerate the fixture (Decision 37), not a failed gate"
    )


def test_recorded_rule_and_decision_counts_for_the_easy_tier_at_seed_42():
    """Informational snapshot -- not an assertion of correctness, just today's recorded shape."""
    labels = _read_jsonl(FIXTURES_DIR / "golden.labels.jsonl")
    attack_count = sum(1 for lbl in labels if lbl["is_attack"])
    baseline_count = sum(1 for lbl in labels if not lbl["is_attack"])
    print(f"golden fixture (seed=42, tier=easy): {len(labels)} events, "
          f"{attack_count} attack, {baseline_count} baseline")
    assert attack_count > 0
    assert baseline_count > 0
