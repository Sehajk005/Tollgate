"""
Source: TRD v2 §6.4 -- "A test asserts nothing outside tests/ imports the
oracle." Day-3 Plan Step 5 test list, item 10. Reuses the transitive
AST import-closure scanner from tests/acceptance/test_simulator_safety.py
(Day-2 Plan §I A11's `_imported_module_names`) rather than reimplementing
import resolution, and walks every .py file under packages/, services/,
and scripts/ to prove none of them, directly or transitively, imports
tests.oracles.pandas_windows.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.test_simulator_safety import _imported_module_names

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "packages", REPO_ROOT / "services", REPO_ROOT / "scripts"]
# Source: TRD §6.4 -- resolvable local prefixes extended to include "tests"
# (unlike test_simulator_safety.py's scan, which never needs to resolve
# into tests/) so a violation found through an indirect chain (production
# code -> some local module -> tests.oracles) is still traced and reported.
RESOLVABLE_PREFIXES = ("packages", "services", "scripts", "tests")


def _local_module_file(module_name: str):
    if not module_name or not module_name.startswith(RESOLVABLE_PREFIXES):
        return None
    as_dir = REPO_ROOT / Path(*module_name.split("."))
    if (as_dir / "__init__.py").exists():
        return as_dir / "__init__.py"
    as_file = as_dir.with_suffix(".py")
    if as_file.exists():
        return as_file
    return None


def test_nothing_outside_tests_imports_pandas_oracle():
    to_visit = []
    for root in SCAN_ROOTS:
        if root.exists():
            to_visit.extend(root.rglob("*.py"))

    visited = set()
    violations = []
    while to_visit:
        path = to_visit.pop()
        if path in visited:
            continue
        visited.add(path)
        for imported in _imported_module_names(path):
            if imported == "tests" or imported.startswith("tests."):
                violations.append(f"{path}: imports {imported!r}")
                continue
            local_file = _local_module_file(imported)
            if local_file is not None and local_file not in visited:
                to_visit.append(local_file)

    assert not violations, "production code must never import tests/:\n" + "\n".join(violations)
