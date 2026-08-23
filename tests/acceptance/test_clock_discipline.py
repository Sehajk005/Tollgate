"""
Source: Implementation Plan v2.1 Day 1 acceptance tests 6-7 -- clock
invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from packages.clock.clock import VirtualClock
from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import WindowRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ["packages", "services", "scripts"]
ALLOWED_DIR = (REPO_ROOT / "packages" / "clock").resolve()

BANNED_CALLS = {
    ("time", "time"),
    ("time", "time_ns"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
}


def _iter_python_files():
    for dirname in SCANNED_DIRS:
        base = REPO_ROOT / dirname
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            resolved = path.resolve()
            if ALLOWED_DIR == resolved.parent or ALLOWED_DIR in resolved.parents:
                continue
            yield path


def _find_banned_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if (func.value.id, func.attr) in BANNED_CALLS:
                findings.append(f"{path}:{node.lineno}: {func.value.id}.{func.attr}()")
    return findings


class TestNoWallClockOutsidePackagesClock:
    # Source: Impl Plan Day 1 acceptance test 6
    def test_no_banned_wall_clock_calls_outside_clock_package(self):
        all_findings = []
        for path in _iter_python_files():
            all_findings.extend(_find_banned_calls(path))
        assert not all_findings, (
            "wall-clock calls found outside packages/clock:\n" + "\n".join(all_findings)
        )

    def test_scan_actually_detects_a_banned_call(self, tmp_path):
        # Proves the AST scan isn't vacuously passing.
        planted = tmp_path / "planted.py"
        planted.write_text("import time\ndef f():\n    return time.time()\n", encoding="utf-8")
        findings = _find_banned_calls(planted)
        assert findings, "the scanner failed to detect a planted time.time() call"


class TestVirtualClockBehavior:
    # Source: Impl Plan Day 1 acceptance test 7 -- "an actual behavior test
    # for VirtualClock... prove that time-dependent logic can use
    # deterministic virtual time."
    def test_virtual_clock_advances_without_any_wall_time(self):
        clock = VirtualClock(epoch_ms=1_000_000)
        assert clock.now_ms() == 1_000_000
        clock.advance_ms(60_000)
        assert clock.now_ms() == 1_060_000

    def test_virtual_clock_cannot_move_backwards(self):
        clock = VirtualClock(epoch_ms=1_000)
        with pytest.raises(ValueError):
            clock.advance_ms(-1)

    def test_window_expiry_driven_purely_by_virtual_clock(self):
        # Proves time-dependent logic (window trimming) can be driven
        # entirely by VirtualClock -- no sleep(), no wall time.
        clock = VirtualClock(epoch_ms=0)
        store = InMemoryWindowStore()

        first = store.record_and_read(WindowRequest(
            merchant_id="m1", space="ip", key="1.2.3.4", metric="ev",
            member="attempt-1", ingest_ms=clock.now_ms(), window_ms=60_000,
        ))
        assert first.count == 1

        # Advance virtual time past the window -- no real waiting occurs.
        clock.advance_ms(60_001)

        second = store.record_and_read(WindowRequest(
            merchant_id="m1", space="ip", key="1.2.3.4", metric="ev",
            member="attempt-2", ingest_ms=clock.now_ms(), window_ms=60_000,
        ))
        # attempt-1 has expired out of the window; only attempt-2 remains.
        assert second.count == 1
