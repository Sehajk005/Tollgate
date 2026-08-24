"""
Source: Day-2 Plan §I acceptance tests A8-A10 -- attack tier configuration
and anti-circularity. `config/attack_tiers.yaml` does not exist yet (Day-2
Plan §A item 1); A10 fails with FileNotFoundError until Step 2, A8/A9 fail
with ModuleNotFoundError until Step 4.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ATTACK_TIERS_PATH = REPO_ROOT / "config" / "attack_tiers.yaml"

# Source: Day-2 Plan §J test-gaming review -- "put source: 'synthetic' on
# every parameter" must be caught. A parameter-value word appearing in its
# own justification is the signature of a fabricated citation.
BANNED_SOURCE_VOCAB = re.compile(
    r"\b(synthetic|made[- ]up|arbitrary|placeholder|guess(ed)?|n/a|unknown|tbd|todo)\b",
    re.IGNORECASE,
)
# A real citation names a spec document/section, a Decisions.md entry, or a
# DOI -- not a bare adjective.
SOURCE_SHAPE_RE = re.compile(r"(§\s?\d|Decision\s+\d+|doi:\s?10\.|\bv2\.?1?\b.*§)", re.IGNORECASE)
MIN_SOURCE_LEN = 12
MIN_DISTINCT_SOURCES = 4


def _generate(out_path: Path, labels_path: Path, episodes_path: Path, *, seed: int, tier: str, hours: int):
    cmd = [
        sys.executable, "-m", "packages.simulator.generate",
        "--seed", str(seed), "--tier", tier, "--hours", str(hours),
        "--out", str(out_path), "--labels", str(labels_path), "--episodes", str(episodes_path),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"generator failed:\nstdout={result.stdout}\nstderr={result.stderr}"


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _load_attack_tiers() -> dict:
    assert ATTACK_TIERS_PATH.exists(), f"missing {ATTACK_TIERS_PATH}"
    return yaml.safe_load(ATTACK_TIERS_PATH.read_text(encoding="utf-8"))


def _mann_whitney_auc(sample_a: list, sample_b: list) -> float:
    """
    Independent implementation (Day-2 Plan §I A9: 'the threshold is stated
    in the spec, not chosen here') of the AUC-equivalent of the Mann-Whitney
    U statistic: P(a random sample_a value > a random sample_b value), with
    ties broken via average-rank handling. Pure stdlib -- no numpy/scipy.
    This is test code computing a statistic, not the simulator's own
    sampling, so ordinary floats are fine here (Decision 30 constrains the
    simulator's serialized output, not test arithmetic).
    """
    combined = sorted(sample_a + sample_b)
    ranks = {}
    i = 0
    n = len(combined)
    while i < n:
        j = i
        while j < n and combined[j] == combined[i]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0  # 1-indexed average rank over the tie block
        for k in range(i, j):
            ranks[combined[k]] = avg_rank
        i = j

    rank_sum_a = sum(ranks[v] for v in sample_a)
    n1, n2 = len(sample_a), len(sample_b)
    u1 = rank_sum_a - n1 * (n1 + 1) / 2.0
    return u1 / (n1 * n2)


class TestA8HardTierRateWithinConfiguredBand:
    # Source: Day-2 Plan §I A8 -- Impl Plan v2.1 Day 2 (the attack_tiers.yaml
    # "configured band"). Rate is recomputed independently from the
    # generated events' own t_ms, not read back from the generator's
    # internal state -- a generator that mislabels an easy attack as "hard"
    # must still fail this.
    def test_hard_tier_attempt_rate_matches_its_own_configured_band(self, tmp_path):
        tiers = _load_attack_tiers()
        band = tiers["hard"]["attempts_per_hour_band"]

        events_path = tmp_path / "events.jsonl"
        labels_path = tmp_path / "labels.jsonl"
        episodes_path = tmp_path / "episodes.jsonl"
        _generate(events_path, labels_path, episodes_path, seed=42, tier="hard", hours=3)

        events = _read_jsonl(events_path)
        labels = _read_jsonl(labels_path)
        t_ms_by_id = {e["event_id"]: e["t_ms"] for e in events}
        attack_t_ms = sorted(t_ms_by_id[lbl["event_id"]] for lbl in labels if lbl["is_attack"])
        assert attack_t_ms, "hard tier produced no attack events"

        span_hours = (attack_t_ms[-1] - attack_t_ms[0]) / 3_600_000.0
        assert span_hours > 0, "attack episode has zero duration"
        rate_per_hour = len(attack_t_ms) / span_hours

        assert band["min"] <= rate_per_hour <= band["max"], (
            f"hard-tier attempts/hour recomputed from timestamps = {rate_per_hour:.1f}, "
            f"outside configured band [{band['min']}, {band['max']}]"
        )


class TestA9AmountDistributionAntiCircularity:
    # Source: Day-2 Plan §I A9 -- Eval Protocol v2 §4/V2, quoted verbatim in
    # the plan: "the attacker's amounts are drawn from the store's own
    # empirical distribution's low tail rather than a fixed constant." AUC
    # here is the univariate separability of amount_minor alone; > 0.95
    # means amount is (almost) a perfect discriminator, i.e. a generator
    # artifact rather than a modelled attacker behaviour.
    def test_amount_minor_auc_attack_vs_baseline_is_not_a_perfect_discriminator(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        labels_path = tmp_path / "labels.jsonl"
        episodes_path = tmp_path / "episodes.jsonl"
        _generate(events_path, labels_path, episodes_path, seed=42, tier="easy", hours=3)

        events = _read_jsonl(events_path)
        labels = _read_jsonl(labels_path)
        amount_by_id = {e["event_id"]: e["amount_minor"] for e in events}
        is_attack_by_id = {lbl["event_id"]: lbl["is_attack"] for lbl in labels}

        attack_amounts = [amount_by_id[eid] for eid, atk in is_attack_by_id.items() if atk]
        baseline_amounts = [amount_by_id[eid] for eid, atk in is_attack_by_id.items() if not atk]
        assert attack_amounts and baseline_amounts, "need both attack and baseline amounts to compute AUC"

        auc = _mann_whitney_auc(attack_amounts, baseline_amounts)
        # Symmetric statistic: report on whichever side is more separable.
        auc = max(auc, 1.0 - auc)
        assert auc <= 0.95, (
            f"amount_minor AUC (attack vs baseline) = {auc:.4f} > 0.95 -- amounts are "
            f"an almost-perfect discriminator, a generator artifact per Eval Protocol §4/V2"
        )

    def test_auc_helper_detects_a_planted_perfect_discriminator(self):
        # Proves the AUC statistic isn't vacuously passing.
        low = list(range(0, 100))
        high = list(range(1000, 1100))
        auc = _mann_whitney_auc(high, low)
        assert auc > 0.99


class TestA10AttackTiersAntiCircularity:
    # Source: Day-2 Plan §I A10, quoted verbatim: "every attack_tiers.yaml
    # leaf with `value` has `source`; >=12 chars; not in the banned
    # vocabulary; matches a citation shape; >= N distinct sources across the
    # file." Also Decision 38.
    def _iter_value_leaves(self, node, path=""):
        if isinstance(node, dict):
            if "value" in node:
                yield path, node
            for key, child in node.items():
                yield from self._iter_value_leaves(child, f"{path}.{key}" if path else key)

    def test_every_populated_parameter_has_a_real_source(self):
        tiers = _load_attack_tiers()
        sources = []
        checked_any = False
        for path, leaf in self._iter_value_leaves(tiers):
            if leaf.get("pending"):
                continue  # Day-2 Plan §D Decision 38 / Step 2 failure modes.
            checked_any = True
            source = leaf.get("source")
            assert source, f"{path}: leaf has 'value' but no 'source'"
            assert len(source) >= MIN_SOURCE_LEN, f"{path}: source too short to be a real citation: {source!r}"
            assert not BANNED_SOURCE_VOCAB.search(source), f"{path}: source uses banned vocabulary: {source!r}"
            assert SOURCE_SHAPE_RE.search(source), f"{path}: source does not look like a citation: {source!r}"
            sources.append(source)
        assert checked_any, "no non-pending parameters found in attack_tiers.yaml"
        assert len(set(sources)) >= MIN_DISTINCT_SOURCES, (
            f"only {len(set(sources))} distinct sources across attack_tiers.yaml, "
            f"need >= {MIN_DISTINCT_SOURCES} (Day-2 Plan §J: one blanket citation is a gaming move)"
        )

    def test_pending_tiers_are_exempt_but_present(self):
        # Source: Day-2 Plan §C C3 -- Day 2 ships easy+hard; medium/evasive
        # exist as declared placeholders (Impl Plan §Day 2, Decision 38's
        # Step 2 elaboration), not silently absent.
        tiers = _load_attack_tiers()
        assert "medium" in tiers and "evasive" in tiers
        assert tiers["medium"].get("pending") == "Day 4"
        assert tiers["evasive"].get("pending") == "Day 7"

    def test_banned_vocabulary_regex_actually_catches_a_planted_fake_source(self):
        assert BANNED_SOURCE_VOCAB.search("synthetic, chosen for the demo")
        assert not BANNED_SOURCE_VOCAB.search("Threat Model v2 §6 -- Tier E pacing")
