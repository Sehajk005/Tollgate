"""
Source: Day-2 Plan §I acceptance tests A5-A7 -- episode/label integrity.
`packages/simulator` and `data/streams/` do not exist yet; these tests are
expected to fail with ImportError/ModuleNotFoundError until Day-2 Step 4.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate(out_path: Path, labels_path: Path, episodes_path: Path, *, seed: int, tier: str, hours: int = 3):
    cmd = [
        sys.executable, "-m", "packages.simulator.generate",
        "--seed", str(seed), "--tier", tier, "--hours", str(hours),
        "--out", str(out_path), "--labels", str(labels_path), "--episodes", str(episodes_path),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"generator failed:\nstdout={result.stdout}\nstderr={result.stderr}"


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _generated(tmp_path: Path, seed: int = 42, tier: str = "easy"):
    events_path = tmp_path / "events.jsonl"
    labels_path = tmp_path / "labels.jsonl"
    episodes_path = tmp_path / "episodes.jsonl"
    _generate(events_path, labels_path, episodes_path, seed=seed, tier=tier)
    return _read_jsonl(events_path), _read_jsonl(labels_path), _read_jsonl(episodes_path)


class TestA5EpisodeCountsMatchRecount:
    # Source: Day-2 Plan §I A5 -- Impl Plan v2.1 Day 2; Backend Schema v2 §3.4
    # (episode_truth.attempt_count/distinct_cards are declared columns; their
    # semantics are forced by the DDL, so an episode record whose counts do
    # not match a recount from the labels it claims to summarize is corrupt
    # by the schema's own definition, independent of any Day-2-specific text).
    def test_every_attack_label_references_a_real_episode(self, tmp_path):
        _, labels, episodes = _generated(tmp_path)
        episode_ids = {ep["episode_id"] for ep in episodes}
        attack_labels = [lbl for lbl in labels if lbl["is_attack"]]
        assert attack_labels, "no attack-labelled events were generated"
        for lbl in attack_labels:
            assert lbl["episode_id"] is not None, f"attack label {lbl['event_id']} has no episode_id"
            assert lbl["episode_id"] in episode_ids, (
                f"label {lbl['event_id']} references unknown episode {lbl['episode_id']}"
            )

    def test_episode_counts_equal_an_independent_recount_from_labels(self, tmp_path):
        events, labels, episodes = _generated(tmp_path)
        card_by_event_id = {e["event_id"]: e["card_hash"] for e in events}
        assert episodes, "no episodes were generated"
        for ep in episodes:
            member_labels = [lbl for lbl in labels if lbl["episode_id"] == ep["episode_id"]]
            recounted_attempts = len(member_labels)
            recounted_distinct_cards = len({card_by_event_id[lbl["event_id"]] for lbl in member_labels})
            assert recounted_attempts == ep["attempt_count"], (
                f"episode {ep['episode_id']}: attempt_count={ep['attempt_count']} "
                f"but recount from labels={recounted_attempts}"
            )
            assert recounted_distinct_cards == ep["distinct_cards"], (
                f"episode {ep['episode_id']}: distinct_cards={ep['distinct_cards']} "
                f"but recount from labels={recounted_distinct_cards}"
            )


class TestA6EventsLabelsAreABijection:
    # Source: Day-2 Plan §I A6 -- Backend Schema v2 §9 step 4 (events.jsonl /
    # labels.jsonl are named as a pair); a bijection on event_id is the
    # minimal correctness property such a pairing implies -- forced, not
    # Day-2-invented.
    def test_every_event_has_exactly_one_label_and_vice_versa(self, tmp_path):
        events, labels, _ = _generated(tmp_path)
        event_ids = [e["event_id"] for e in events]
        label_ids = [lbl["event_id"] for lbl in labels]
        assert len(event_ids) == len(set(event_ids)), "duplicate event_id in events.jsonl"
        assert len(label_ids) == len(set(label_ids)), "duplicate event_id in labels.jsonl"
        assert set(event_ids) == set(label_ids), "events.jsonl and labels.jsonl are not a bijection on event_id"


class TestA7EpisodesCoexistWithBaselineTraffic:
    # Source: Day-2 Plan §I A7 -- Eval Protocol v2 §4/V4 (negative controls
    # presuppose concurrent legitimate traffic) and App Flow v2 §J6 step 6.
    # An episode that suppresses baseline traffic makes "was there any
    # traffic right now" a free discriminator of the attack, which would
    # make the whole anti-leakage design pointless.
    def test_no_attack_label_falls_outside_every_episode_window(self, tmp_path):
        events, labels, episodes = _generated(tmp_path)
        t_ms_by_event_id = {e["event_id"]: e["t_ms"] for e in events}
        windows = [(ep["started_at"], ep["ended_at"]) for ep in episodes]
        for lbl in labels:
            if not lbl["is_attack"]:
                continue
            t_ms = t_ms_by_event_id[lbl["event_id"]]
            assert any(start <= t_ms <= end for start, end in windows), (
                f"attack event {lbl['event_id']} at t_ms={t_ms} falls outside every episode window"
            )

    def test_baseline_traffic_exists_inside_every_episode_window(self, tmp_path):
        events, labels, episodes = _generated(tmp_path)
        t_ms_by_event_id = {e["event_id"]: e["t_ms"] for e in events}
        baseline_ids = {lbl["event_id"] for lbl in labels if not lbl["is_attack"]}
        assert episodes, "no episodes were generated"
        for ep in episodes:
            baseline_in_window = [
                event_id for event_id in baseline_ids
                if ep["started_at"] <= t_ms_by_event_id[event_id] <= ep["ended_at"]
            ]
            assert baseline_in_window, (
                f"episode {ep['episode_id']} ({ep['started_at']}-{ep['ended_at']}) "
                f"has no baseline traffic inside its window -- time-of-day would become "
                f"a free discriminator"
            )
