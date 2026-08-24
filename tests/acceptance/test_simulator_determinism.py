"""
Source: Day-2 Plan §I acceptance tests A1-A4 -- simulator determinism.

Every test here invokes `python -m packages.simulator.generate` as a fresh
subprocess (never imports simulator internals), so a hidden entropy source
(wall time, id(), set iteration order, an unseeded RNG helper) cannot hide
behind an in-process import cache. `packages/simulator` does not exist yet;
these tests are expected to fail with ImportError/ModuleNotFoundError until
Day-2 Step 4 lands.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate(
    out_path: Path,
    *,
    seed: int,
    tier: str,
    hours: int = 3,
    epoch_ms: int = 0,
    labels_path: "Path | None" = None,
    episodes_path: "Path | None" = None,
    python_exe: "list[str] | None" = None,
) -> subprocess.CompletedProcess:
    cmd = list(python_exe) if python_exe else [sys.executable]
    cmd += [
        "-m", "packages.simulator.generate",
        "--seed", str(seed), "--tier", tier, "--hours", str(hours),
        "--epoch-ms", str(epoch_ms), "--out", str(out_path),
    ]
    if labels_path is not None:
        cmd += ["--labels", str(labels_path)]
    if episodes_path is not None:
        cmd += ["--episodes", str(episodes_path)]
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"generator failed (rc={result.returncode}):\ncmd={cmd}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestA1SameSeedByteIdentical:
    # Source: Day-2 Plan §I A1 -- "identical config + seed => byte-identical
    # stream" (TRD v2 §7). Two independent subprocesses, not two calls in one
    # process, so nothing an interpreter caches can leak between them.
    def test_same_seed_two_fresh_subprocesses_produce_byte_identical_files(self, tmp_path):
        out_a = tmp_path / "a.jsonl"
        out_b = tmp_path / "b.jsonl"
        _generate(out_a, seed=42, tier="easy")
        _generate(out_b, seed=42, tier="easy")
        assert out_a.read_bytes() == out_b.read_bytes()
        assert _sha256(out_a) == _sha256(out_b)


class TestA2DifferentSeedDifferentBytes:
    # Source: Day-2 Plan §I A2 -- forced by A1: a generator that accepts
    # --seed and ignores it would also pass A1, so this must be a separate
    # assertion.
    def test_different_seed_same_tier_produces_different_bytes(self, tmp_path):
        out_a = tmp_path / "a.jsonl"
        out_c = tmp_path / "c.jsonl"
        _generate(out_a, seed=42, tier="easy")
        _generate(out_c, seed=43, tier="easy")
        assert out_a.read_bytes() != out_c.read_bytes()
        assert _sha256(out_a) != _sha256(out_c)


class TestA3CrossInterpreterDeterminism:
    # Source: Day-2 Plan §I A3 (new for Day 2) -- forced by Decision 30
    # (getrandbits-only sampling, no float(), no numpy): if that discipline
    # holds, the seeded Mersenne Twister bitstream -- and therefore the
    # generated file -- must be identical across CPython 3.12 and 3.13.
    @pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
    def test_same_seed_identical_sha_across_python_3_12_and_3_13(self, tmp_path):
        def _uv_python(version: str) -> list:
            # --isolated: this spawns from *inside* the outer `uv run pytest`
            # process, which already holds the project's own .venv. Without
            # --isolated, `uv run --python <other-version>` rebuilds that
            # shared .venv in place to match the requested interpreter,
            # racing the outer process and corrupting it mid-run. --isolated
            # gives this call its own throwaway environment instead.
            return ["uv", "run", "--isolated", "--python", version, "--with", "pyyaml", "python"]

        def _interpreter_version(version: str) -> tuple:
            result = subprocess.run(
                _uv_python(version) + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, result.stderr
            major, minor = result.stdout.split()
            return (int(major), int(minor))

        v312 = _interpreter_version("3.12")
        v313 = _interpreter_version("3.13")
        # Prove the two invocations really ran different interpreters --
        # otherwise this test would vacuously pass by pinning both to one.
        assert v312 != v313, f"expected distinct interpreters, both reported {v312}"

        out_312 = tmp_path / "p312.jsonl"
        out_313 = tmp_path / "p313.jsonl"
        _generate(out_312, seed=42, tier="easy", python_exe=_uv_python("3.12"))
        _generate(out_313, seed=42, tier="easy", python_exe=_uv_python("3.13"))

        assert _sha256(out_312) == _sha256(out_313), (
            "generated stream differs across Python versions -- a float repr, "
            "dict-ordering, or version-unstable RNG helper has leaked in"
        )


class TestA4BaselineIndependentOfTier:
    # Source: Day-2 Plan §I A4 -- Eval Protocol v2 §4 ("the attack half stays
    # authored") + Decision 31 (baseline and attack draw from disjoint,
    # independently seeded RNG sub-streams). `event_id`/`seq` encode the
    # merged-stream position (anti-leakage checklist, Day-2 Plan §F) and so
    # legitimately differ between an easy-tier and a hard-tier run at the
    # same seed -- different attack event counts interleave differently.
    # What must NOT differ is the *content and relative order* of the
    # baseline events themselves.
    def test_baseline_subsequence_identical_regardless_of_attack_tier(self, tmp_path):
        out_easy = tmp_path / "easy.jsonl"
        labels_easy = tmp_path / "easy.labels.jsonl"
        out_hard = tmp_path / "hard.jsonl"
        labels_hard = tmp_path / "hard.labels.jsonl"

        _generate(out_easy, seed=42, tier="easy", labels_path=labels_easy)
        _generate(out_hard, seed=42, tier="hard", labels_path=labels_hard)

        def _baseline_subsequence(events_path: Path, labels_path: Path) -> list:
            events_by_id = {e["event_id"]: e for e in _read_jsonl(events_path)}
            labels = _read_jsonl(labels_path)
            baseline_ids_in_order = [
                lbl["event_id"] for lbl in sorted(labels, key=lambda l: l["seq"])
                if not lbl["is_attack"]
            ]
            content = []
            for event_id in baseline_ids_in_order:
                event = dict(events_by_id[event_id])
                del event["event_id"]
                del event["seq"]
                content.append(event)
            return content

        baseline_easy = _baseline_subsequence(out_easy, labels_easy)
        baseline_hard = _baseline_subsequence(out_hard, labels_hard)

        assert baseline_easy, "no baseline events found in the easy-tier run"
        assert baseline_easy == baseline_hard, (
            "baseline traffic content/order changed when only the attack tier "
            "changed -- the RNG sub-streams are not independent (Decision 31)"
        )
