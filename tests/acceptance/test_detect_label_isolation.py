"""
Source: Day-5 Plan §7 test 2 -- AC 2. `packages/detect/**` (the Layer-1 model
wrapper) must never see a label source, so a training bug can never leak
`is_attack` into the serving path. Transitive AST import-closure scan
(reusing `test_simulator_safety._imported_module_names`) + a source-literal
scan.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.acceptance.test_simulator_safety import _imported_module_names

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECT_ROOT = REPO_ROOT / "packages" / "detect"
RESOLVABLE_PREFIXES = ("packages", "services", "scripts", "eval", "tests")

BANNED_LABEL_MODULES = {"eval.load", "eval.dataset"}
BANNED_LABEL_TOPS = {"eval"}  # detect receives duck-typed objects; it imports NO eval.*
BANNED_SOURCE_LITERALS = ("attempt_label", "is_attack")


def _local_module_file(module_name: str):
    if not module_name or not module_name.startswith(RESOLVABLE_PREFIXES):
        return None
    as_dir = REPO_ROOT / Path(*module_name.split("."))
    if (as_dir / "__init__.py").exists():
        return as_dir / "__init__.py"
    as_file = as_dir.with_suffix(".py")
    return as_file if as_file.exists() else None


def _transitive_imports(entry_dir: Path) -> set:
    visited: set = set()
    to_visit = list(entry_dir.rglob("*.py"))
    all_imports: set = set()
    while to_visit:
        path = to_visit.pop()
        if path in visited:
            continue
        visited.add(path)
        for imported in _imported_module_names(path):
            all_imports.add(imported)
            local = _local_module_file(imported)
            if local is not None and local not in visited:
                to_visit.append(local)
    return all_imports


class TestDetectLabelIsolation:
    def test_no_label_module_in_the_import_closure_of_packages_detect(self):
        imports = _transitive_imports(DETECT_ROOT)
        offenders = {
            name for name in imports
            if name in BANNED_LABEL_MODULES or name.split(".", 1)[0] in BANNED_LABEL_TOPS
        }
        assert not offenders, (
            "packages/detect transitively imports a label / eval module: " + ", ".join(sorted(offenders))
        )

    def test_no_label_literals_in_packages_detect_source(self):
        violations = []
        for path in DETECT_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for literal in BANNED_SOURCE_LITERALS:
                if literal in text:
                    violations.append(f"{path.name}: contains {literal!r}")
        assert not violations, "\n".join(violations)

    def test_scan_actually_detects_a_planted_eval_load_import(self):
        # Non-vacuity: the closure scan really walks files (it saw real
        # imports from packages/detect), and the extraction catches a planted
        # `from eval.load import ...`. `_imported_module_names` requires the
        # file to live under the repo root, so plant it there and clean up.
        assert _transitive_imports(DETECT_ROOT), "the closure scan returned no imports at all"

        planted = REPO_ROOT / "packages" / "detect" / "_planted_leak_probe.py"
        planted.write_text("from eval.load import load_truth  # noqa\n", encoding="utf-8")
        try:
            names = _imported_module_names(planted)
        finally:
            planted.unlink()
        assert "eval.load" in names, "the scanner missed a planted `from eval.load import ...`"
        tree = ast.parse("from eval.dataset import Sample\n")
        assert any(
            isinstance(n, ast.ImportFrom) and n.module == "eval.dataset" for n in ast.walk(tree)
        )
