"""
Source: Day-5 Plan §7 test 3 -- AC 8. Class imbalance is handled by LightGBM's
`scale_pos_weight = n_neg/n_pos` on the fit slice ONLY (TRD §6.9). No SMOTE,
no resampling, no `imblearn` anywhere in the tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("packages", "services", "scripts", "eval", "tests")
BANNED_IMPORT_TOPS = {"imblearn"}
BANNED_SOURCE_TOKENS = ("imblearn", "SMOTE", "smote")
SELF = Path(__file__).name


def _iter_py():
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if root.exists():
            yield from root.rglob("*.py")


class TestNoSmote:
    def test_no_imblearn_import_anywhere(self):
        offenders = []
        for path in _iter_py():
            if path.name == SELF:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".", 1)[0] in BANNED_IMPORT_TOPS:
                            offenders.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".", 1)[0] in BANNED_IMPORT_TOPS:
                        offenders.append(f"{path}: from {node.module} import ...")
        assert not offenders, "\n".join(offenders)

    def test_no_smote_tokens_in_source(self):
        offenders = []
        for path in _iter_py():
            if path.name == SELF:
                continue
            text = path.read_text(encoding="utf-8")
            for token in BANNED_SOURCE_TOKENS:
                if token in text:
                    offenders.append(f"{path}: contains {token!r}")
        assert not offenders, "\n".join(offenders)
