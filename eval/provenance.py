"""
Source: Day-4 Plan (rev. 2) Step 7 -- config_hash / build_hash
construction and RunProvenance validation.

`config_hash` is structured, domain-separated, and covers only the BUILD
INPUTS (config files) -- three deliberate properties, each a rev. 1 bug
(F16):
  - path-prefixed, \\x00-framed: moving a line between two config files
    changes the hash (raw concatenation would not).
  - hashes the PARSED structure via canonical JSON (Decision 30's
    sort_keys/no-whitespace convention) -- comments/formatting never
    churn provenance.
`build_hash` is a SEPARATE value covering `git rev-parse HEAD` (+ dirty
flag), the baseline profile's SHA, and the golden fixture's SHA -- two
runs on different code no longer produce an identical config_hash +
build_hash pair.

`RunProvenance.validate()` checks MEANING, not presence (F15): a
placeholder-shaped string that merely looks non-empty is rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_HASH_DOMAIN = b"tollgate-config-v1\x00"
BUILD_HASH_DOMAIN = b"tollgate-build-v1\x00"
DEFAULT_CONFIG_PATHS: tuple = (
    "config/cost_model.yaml", "config/rules.yaml", "config/attack_tiers.yaml", "config/store_profile.yaml",
    # Source: Day-5 Plan Step 1 -- the model/audit/calibration knobs are a
    # BUILD INPUT and must be provenanced. test_config_hash.py is fully
    # relative, so this changes hash values but breaks no assertion.
    "config/features.yaml",
)
BASELINE_PROFILE_SHA_PATH = REPO_ROOT / "data" / "baseline" / "online_retail_ii.profile.sha256"
FIXTURE_SHA_PATH = REPO_ROOT / "tests" / "fixtures" / "golden.sha256"

# Source: Day-4 Plan Step 7 -- on Day 4 only a none:* sanity value is
# legal (no model, no calibrator exists yet).
MODEL_VERSION_RE = re.compile(r"^(none:(perfect|random|inverted|always_positive)|rules-only-v\d+|l1-lgbm-v\d+)$")


def _canonical_json(obj) -> str:
    """Decision 30's convention: sort_keys, no whitespace, ensure_ascii -- comments/formatting never affect the hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(paths: Sequence[str] = DEFAULT_CONFIG_PATHS, *, repo_root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256(CONFIG_HASH_DOMAIN)
    for rel_path in sorted(paths):
        full_path = repo_root / rel_path
        parsed = yaml.safe_load(full_path.read_text(encoding="utf-8"))
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(_canonical_json(parsed).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _git_head_and_dirty(repo_root: Path) -> tuple:
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout
        dirty = bool(status.strip())
    except Exception:
        rev, dirty = "unknown", True
    return rev, dirty


def _sha_file_first_token(path: Path) -> str:
    if not path.exists():
        return "missing"
    return path.read_text(encoding="utf-8").strip().splitlines()[0].split()[0]


def build_hash(*, repo_root: Path = REPO_ROOT) -> str:
    rev, dirty = _git_head_and_dirty(repo_root)
    baseline_sha = _sha_file_first_token(BASELINE_PROFILE_SHA_PATH)
    fixture_sha = _sha_file_first_token(FIXTURE_SHA_PATH)
    digest = hashlib.sha256(BUILD_HASH_DOMAIN)
    for token in (rev, "1" if dirty else "0", baseline_sha, fixture_sha):
        digest.update(token.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


class ProvenanceError(Exception):
    pass


@dataclass(frozen=True)
class RunProvenance:
    model_version: str
    config_hash: str
    policy_version: int
    eval_prevalence: float

    def validate(self, *, policy_versions_available: Sequence[int]) -> "RunProvenance":
        if not MODEL_VERSION_RE.match(self.model_version):
            raise ProvenanceError(
                f"model_version {self.model_version!r} does not match the declared vocabulary"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_hash):
            raise ProvenanceError(f"config_hash must be 64 hex chars, got {self.config_hash!r}")
        recomputed = config_hash()
        if self.config_hash != recomputed:
            raise ProvenanceError(
                f"config_hash {self.config_hash!r} does not match a fresh recompute {recomputed!r}"
            )
        if not isinstance(self.policy_version, int) or self.policy_version <= 0:
            raise ProvenanceError(f"policy_version must be a positive int, got {self.policy_version!r}")
        if self.policy_version not in policy_versions_available:
            raise ProvenanceError(
                f"policy_version {self.policy_version} does not exist in policy_config "
                f"(available: {list(policy_versions_available)})"
            )
        if not (0.0 < self.eval_prevalence < 1.0):
            raise ProvenanceError(f"eval_prevalence must be in (0,1), got {self.eval_prevalence!r}")
        return self
