r"""
python scripts/diff_d6.py eval/outputs/d6.json <other>/d6.json \
    --ignore provenance.build_hash \
    --ignore provenance.generated_at \
    --ignore provenance.head_at_generation \
    --ignore provenance.tree_dirty_at_generation

Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §17.3 / §28 Phase 0 -- a
leaf-wise structural diff of two D6 artifacts with float tolerance. It is the
instrument that makes each backend change's blast radius observable *before*
anything is committed: regenerate into a scratch dir, diff against the
committed `eval/outputs/d6.json`, and read off exactly which leaves moved.

Not a generic JSON differ: it flattens to dotted leaf paths (list elements
become `foo[3]`), compares numbers with an absolute + relative tolerance so
platform float noise is not reported as a change, and lets whole subtrees be
`--ignore`d by prefix (the provenance fields that MUST differ between two
runs). Exit status is 0 when nothing substantive differs after the ignore
filter, 1 otherwise -- so it composes into a verification script.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

Leaves = Dict[str, Any]


def _flatten(node: Any, prefix: str, out: Leaves) -> None:
    """Walk `node`, writing every scalar leaf into `out` keyed by its dotted
    path. Dict keys join with '.'; list indices append '[i]'. Empty containers
    are themselves recorded as leaves so that `[] -> [1]` is a visible change."""
    if isinstance(node, dict):
        if not node:
            out[prefix or "<root>"] = {}
            return
        for key, value in node.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            _flatten(value, child, out)
    elif isinstance(node, list):
        if not node:
            out[prefix or "<root>"] = []
            return
        for i, value in enumerate(node):
            _flatten(value, f"{prefix}[{i}]", out)
    else:
        out[prefix or "<root>"] = node


def _is_ignored(path: str, ignore: Iterable[str]) -> bool:
    for token in ignore:
        if path == token or path.startswith(f"{token}.") or path.startswith(f"{token}["):
            return True
    return False


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _close(a: float, b: float, atol: float, rtol: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))


def diff(
    a: Any,
    b: Any,
    ignore: List[str],
    atol: float,
    rtol: float,
) -> Tuple[List[str], List[str], List[Tuple[str, Any, Any, float]]]:
    """Return (added, removed, changed). `added`/`removed` are dotted paths;
    `changed` is (path, old, new, abs_delta) with abs_delta 0.0 for non-numeric
    changes. Paths matched by an `ignore` prefix are dropped from all three."""
    fa: Leaves = {}
    fb: Leaves = {}
    _flatten(a, "", fa)
    _flatten(b, "", fb)

    keys_a = {k for k in fa if not _is_ignored(k, ignore)}
    keys_b = {k for k in fb if not _is_ignored(k, ignore)}

    added = sorted(keys_b - keys_a)
    removed = sorted(keys_a - keys_b)

    changed: List[Tuple[str, Any, Any, float]] = []
    for key in sorted(keys_a & keys_b):
        va, vb = fa[key], fb[key]
        if _num(va) and _num(vb):
            if not _close(float(va), float(vb), atol, rtol):
                changed.append((key, va, vb, abs(float(va) - float(vb))))
        elif va != vb:
            changed.append((key, va, vb, 0.0))
    return added, removed, changed


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return repr(value)
    return json.dumps(value)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leaf-wise structural diff of two D6 artifacts.")
    parser.add_argument("left", type=Path, help="baseline artifact (e.g. the committed eval/outputs/d6.json)")
    parser.add_argument("right", type=Path, help="candidate artifact (e.g. a scratch regeneration)")
    parser.add_argument("--ignore", action="append", default=[], metavar="PATH_PREFIX",
                        help="dotted path or subtree prefix to exclude (repeatable)")
    parser.add_argument("--atol", type=float, default=1e-9, help="absolute float tolerance (default 1e-9)")
    parser.add_argument("--rtol", type=float, default=1e-9, help="relative float tolerance (default 1e-9)")
    parser.add_argument("--quiet", action="store_true", help="print only the summary line")
    args = parser.parse_args(argv)

    left = json.loads(args.left.read_text(encoding="utf-8"))
    right = json.loads(args.right.read_text(encoding="utf-8"))

    added, removed, changed = diff(left, right, args.ignore, args.atol, args.rtol)

    if not args.quiet:
        if args.ignore:
            print(f"# ignoring: {', '.join(args.ignore)}")
        if removed:
            print(f"\n## removed in {args.right} ({len(removed)})")
            for path in removed:
                print(f"  - {path}")
        if added:
            print(f"\n## added in {args.right} ({len(added)})")
            for path in added:
                print(f"  + {path}")
        if changed:
            print(f"\n## changed ({len(changed)})")
            worst = 0.0
            for path, old, new, delta in changed:
                worst = max(worst, delta)
                tail = f"   (abs_delta = {delta:.3e})" if delta else ""
                print(f"  ~ {path}: {_fmt(old)} -> {_fmt(new)}{tail}")
            if worst:
                print(f"\n  max abs_delta over numeric changes: {worst:.3e}")

    total = len(added) + len(removed) + len(changed)
    print(f"\n{total} substantive difference(s) "
          f"[added {len(added)}, removed {len(removed)}, changed {len(changed)}] "
          f"after ignoring {len(args.ignore)} prefix(es)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
