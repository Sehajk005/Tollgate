"""
Source: Day-2 Plan §F profile.py -- "loads store_profile.yaml + the
distilled dataset profile, verifies its SHA" (stdlib + pyyaml only;
Decision 29 -- pandas never runs again after scripts/distill_baseline.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PROFILE_PATH = REPO_ROOT / "config" / "store_profile.yaml"
DEFAULT_ATTACK_TIERS_PATH = REPO_ROOT / "config" / "attack_tiers.yaml"
DEFAULT_BASELINE_PROFILE_PATH = REPO_ROOT / "data" / "baseline" / "online_retail_ii.profile.json"
DEFAULT_BASELINE_SHA_PATH = REPO_ROOT / "data" / "baseline" / "online_retail_ii.profile.sha256"


def load_store_profile(path: Path = DEFAULT_STORE_PROFILE_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_attack_tiers(path: Path = DEFAULT_ATTACK_TIERS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_baseline_profile(
    profile_path: Path = DEFAULT_BASELINE_PROFILE_PATH,
    sha_path: Path = DEFAULT_BASELINE_SHA_PATH,
) -> dict:
    raw_bytes = Path(profile_path).read_bytes()
    actual_digest = hashlib.sha256(raw_bytes).hexdigest()

    sha_line = Path(sha_path).read_text(encoding="utf-8").strip().splitlines()[0]
    expected_digest = sha_line.split()[0]
    if actual_digest != expected_digest:
        raise ValueError(
            f"baseline profile SHA mismatch: expected {expected_digest}, got {actual_digest} "
            f"-- {profile_path} was edited without regenerating {sha_path}"
        )
    return json.loads(raw_bytes.decode("utf-8"))


def rescale_to_store_aov(quantile_value_gbp_minor: int, aov_minor: int, mean_gbp_minor: int) -> int:
    """
    Source: Day-2 Plan §F step 4 -- "amount_minor = round(q_gbp_minor x
    aov_minor / mean_order_value_gbp_minor)", integer rounding (round-half-
    up), shared by both the baseline model and the attack model's
    low-tail-of-the-same-table sampler (Eval Protocol v2 §4/V2).
    """
    numerator = quantile_value_gbp_minor * aov_minor
    return (numerator + mean_gbp_minor // 2) // mean_gbp_minor
