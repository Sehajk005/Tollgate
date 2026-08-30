"""
python -m scripts.tune_cusum [--db data/corpus/tollgate.db] [--demo-db tollgate.db]

Source: Day-6 Plan §3.8 / TRD v2 §6.5 -- "`h` is tuned on NEGATIVE CONTROLS
ONLY to hit a target ARL0 (asserted: the tuning script never opens attack
data)". `policy_config.cusum_h` ships as a placeholder 5.0 and
`policy_config.thresholds` as `{}`; this script replaces both, as a new
policy_config version.

Target: ARL0 >= 8,640 buckets = <=1 false alarm per merchant per 24 virtual
hours at the 10 s bucket width (Day-6 Plan D3 -- an operator-facing SLO; no
document states a number).

Method:
  1. tau_flag = CostModel.tier_ladder()['throttle'] (DERIVED, never a literal).
  2. Replay each of the 7 negative-control runs' logged
     (ingest_time, score_calibrated) through PoissonCusum at tau_flag, using
     that merchant's own store_baseline row for lambda_0(t). Bisect `h` for
     ZERO false alarms across all 7 runs.
  3. Validate that `h` against synthetic Poisson(lam0_bar) noise for
     ARL0 >= 8,640 (lam0_bar is the mean lambda_0 across the negative-control
     buckets -- still negative-control-derived, no attack data). Bump `h` if
     the synthetic ARL0 falls short.
  4. Write a NEW policy_config version via append_policy_config, carrying the
     tuned cusum_h AND thresholds = CostModel.tier_ladder().

Provenance: `TuningProvenance` names every merchant_id it read. This is the
assertion surface for test_cusum_tuning_isolation.py -- the set must equal
the negative-control merchant set, and no episode_truth row with
kind='attack' is ever touched.

Lives in scripts/, never packages/detect/, so test_detect_label_isolation.py
stays green. Reads the persisted corpus DB directly -- it never imports the
stream / tier-block construction.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from eval.cost import load_cost_model
from packages.clock.clock import SystemClock
from packages.detect.cusum import CusumParams, PoissonCusum, baseline_lambda0, hour_of_day
from packages.storage.repository import append_policy_config

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_YAML = REPO_ROOT / "config" / "policy.yaml"


def _cfg(node) -> object:
    return node["value"] if isinstance(node, dict) and "value" in node else node


def _load_policy_yaml() -> dict:
    raw = yaml.safe_load(POLICY_YAML.read_text(encoding="utf-8"))
    return {
        "rho": float(_cfg(raw["cusum"]["rho"])),
        "bucket_s": int(_cfg(raw["cusum"]["bucket_s"])),
        "lambda_min": float(_cfg(raw["cusum"]["lambda_min"])),
        "target_arl0_buckets": int(_cfg(raw["cusum"]["target_arl0_buckets"])),
    }


@dataclass(frozen=True)
class TuningProvenance:
    merchant_ids_read: Tuple[str, ...]
    scenarios: Tuple[str, ...]
    target_arl0_buckets: int
    tau_flag: float
    tuned_h: float
    h_from_negative_controls: float
    h_from_synthetic_arl0: float
    false_alarms_at_tuned_h: int
    total_negative_control_buckets: int
    synthetic_arl0_at_tuned_h: float

    def to_dict(self) -> dict:
        return {
            "merchant_ids_read": list(self.merchant_ids_read),
            "scenarios": list(self.scenarios),
            "target_arl0_buckets": self.target_arl0_buckets,
            "tau_flag": self.tau_flag,
            "tuned_h": self.tuned_h,
            "h_from_negative_controls": self.h_from_negative_controls,
            "h_from_synthetic_arl0": self.h_from_synthetic_arl0,
            "false_alarms_at_tuned_h": self.false_alarms_at_tuned_h,
            "total_negative_control_buckets": self.total_negative_control_buckets,
            "synthetic_arl0_at_tuned_h": self.synthetic_arl0_at_tuned_h,
        }


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def negative_control_merchants(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """(merchant_id, scenario) for every run whose episode_truth.kind is
    'negative_control'. This is the ONLY data this script may read -- a
    kind='attack' row is never selected."""
    rows = conn.execute(
        """
        SELECT DISTINCT a.merchant_id AS merchant_id, e.scenario AS scenario
        FROM auth_attempt a
        JOIN attempt_label l ON a.attempt_uid = l.attempt_uid
        JOIN episode_truth e ON l.episode_id = e.episode_id
        WHERE e.kind = 'negative_control'
        ORDER BY a.merchant_id
        """
    ).fetchall()
    return [(r["merchant_id"], r["scenario"]) for r in rows]


def _run_attempts(conn: sqlite3.Connection, merchant_id: str) -> List[Tuple[int, float]]:
    rows = conn.execute(
        """
        SELECT a.ingest_time AS ingest_time, s.score_calibrated AS score_calibrated
        FROM auth_attempt a JOIN attempt_score s ON a.attempt_uid = s.attempt_uid
        WHERE a.merchant_id = ?
        ORDER BY a.ingest_time
        """,
        (merchant_id,),
    ).fetchall()
    return [(int(r["ingest_time"]), float(r["score_calibrated"])) for r in rows]


def _baseline_row(conn: sqlite3.Connection, merchant_id: str) -> Optional[dict]:
    r = conn.execute(
        "SELECT hourly_volume_profile, flagged_rate_mean FROM store_baseline WHERE merchant_id = ?",
        (merchant_id,),
    ).fetchone()
    if r is None:
        return None
    return {
        "hourly_volume_profile": json.loads(r["hourly_volume_profile"]),
        "flagged_rate_mean": float(r["flagged_rate_mean"]),
    }


def replay_run(
    attempts: List[Tuple[int, float]],
    baseline: dict,
    params: CusumParams,
    tau_flag: float,
) -> Tuple[int, Optional[int], List[float]]:
    """Feed one run's (ingest_ms, score_calibrated) through a bucketed
    PoissonCusum gated at tau_flag. Returns (n_buckets, first_alarm_offset
    or None, lambda0_samples)."""
    if not attempts:
        return 0, None, []
    bucket_ms = params.bucket_s * 1000
    cusum = PoissonCusum(params)
    hv = baseline["hourly_volume_profile"]
    p_bar_0 = baseline["flagged_rate_mean"]

    def lam0_for(bucket_index: int) -> float:
        start_ms = bucket_index * bucket_ms
        return baseline_lambda0(
            attempts_this_hour=hv[hour_of_day(start_ms) % len(hv)],
            bucket_s=params.bucket_s,
            flagged_rate_mean=p_bar_0,
            lambda_min=params.lambda_min,
        )

    first_bucket = attempts[0][0] // bucket_ms
    last_bucket = attempts[-1][0] // bucket_ms
    counts: Dict[int, int] = {}
    for t, score in attempts:
        if score >= tau_flag:
            counts[t // bucket_ms] = counts.get(t // bucket_ms, 0) + 1

    lam0_samples: List[float] = []
    first_alarm: Optional[int] = None
    for b in range(first_bucket, last_bucket + 1):
        lam0 = lam0_for(b)
        lam0_samples.append(lam0)
        step = cusum.observe(b, counts.get(b, 0), lam0)
        if step.alarm and first_alarm is None:
            first_alarm = b - first_bucket
    return (last_bucket - first_bucket + 1), first_alarm, lam0_samples


def false_alarms_at(h: float, runs: List[dict], base: CusumParams, tau_flag: float) -> Tuple[int, int]:
    params = CusumParams(rho=base.rho, h=h, bucket_s=base.bucket_s, lambda_min=base.lambda_min)
    fa = 0
    total_buckets = 0
    for run in runs:
        n_buckets, first_alarm, _ = replay_run(run["attempts"], run["baseline"], params, tau_flag)
        total_buckets += n_buckets
        if first_alarm is not None:
            fa += 1
    return fa, total_buckets


def bisect_h_zero_false_alarms(
    runs: List[dict], base: CusumParams, tau_flag: float,
    *, lo: float = 0.25, hi: float = 400.0, iters: int = 44,
) -> float:
    """Smallest h with zero false alarms across the negative-control runs."""
    fa_hi, _ = false_alarms_at(hi, runs, base, tau_flag)
    if fa_hi > 0:
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fa, _ = false_alarms_at(mid, runs, base, tau_flag)
        if fa == 0:
            hi = mid
        else:
            lo = mid
    return hi


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's sampler (small lam; no numpy dependency in scripts/)."""
    if lam <= 0:
        return 0
    el = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= el:
            return k - 1


def arl0_on_poisson_noise(
    h: float, lam0: float, rho: float, lambda_min: float, bucket_s: int,
    *, seed: int, n_buckets: int,
) -> float:
    """Mean run length to first alarm on Poisson(lam0) noise. Right-censored
    at n_buckets (returns n_buckets when no alarm ever occurs)."""
    params = CusumParams(rho=rho, h=h, bucket_s=bucket_s, lambda_min=lambda_min)
    rng = random.Random(seed)
    cusum = PoissonCusum(params)
    lam0 = max(lam0, lambda_min)
    run_lengths: List[int] = []
    length = 0
    for b in range(n_buckets):
        length += 1
        step = cusum.observe(b, _poisson(rng, lam0), lam0)
        if step.alarm:
            run_lengths.append(length)
            length = 0
            cusum.reset()
    if not run_lengths:
        return float(n_buckets)
    return sum(run_lengths) / len(run_lengths)


def tune(db_path: Path) -> Tuple[float, TuningProvenance, dict]:
    cfg = _load_policy_yaml()
    cost_model = load_cost_model()
    thresholds = cost_model.tier_ladder()
    tau_flag = thresholds["throttle"]
    base = CusumParams(rho=cfg["rho"], h=0.0, bucket_s=cfg["bucket_s"], lambda_min=cfg["lambda_min"])
    target = cfg["target_arl0_buckets"]

    conn = _connect(db_path)
    try:
        nc = negative_control_merchants(conn)
        runs: List[dict] = []
        all_lam0: List[float] = []
        for merchant_id, scenario in nc:
            baseline = _baseline_row(conn, merchant_id)
            if baseline is None:
                raise SystemExit(
                    f"store_baseline missing for {merchant_id}; run scripts.learn_store_baseline first"
                )
            attempts = _run_attempts(conn, merchant_id)
            runs.append({"merchant_id": merchant_id, "scenario": scenario,
                         "attempts": attempts, "baseline": baseline})
            _, _, lam0s = replay_run(
                attempts, baseline, CusumParams(base.rho, 1e9, base.bucket_s, base.lambda_min), tau_flag
            )
            all_lam0.extend(lam0s)
    finally:
        conn.close()

    h_nc = bisect_h_zero_false_alarms(runs, base, tau_flag)
    fa_at_h_nc, total_buckets = false_alarms_at(h_nc, runs, base, tau_flag)

    lam0_bar = (sum(all_lam0) / len(all_lam0)) if all_lam0 else base.lambda_min
    h_arl = h_nc
    step = max(0.5, h_nc * 0.25)
    while (
        arl0_on_poisson_noise(
            h_arl, lam0_bar, base.rho, base.lambda_min, base.bucket_s, seed=20260829, n_buckets=target * 2
        )
        < target
        and h_arl < 1000.0
    ):
        h_arl += step
    synth_arl0 = arl0_on_poisson_noise(
        h_arl, lam0_bar, base.rho, base.lambda_min, base.bucket_s, seed=42, n_buckets=target * 2
    )

    tuned_h = round(max(h_nc, h_arl), 4)
    prov = TuningProvenance(
        merchant_ids_read=tuple(r["merchant_id"] for r in runs),
        scenarios=tuple(r["scenario"] for r in runs),
        target_arl0_buckets=target,
        tau_flag=tau_flag,
        tuned_h=tuned_h,
        h_from_negative_controls=round(h_nc, 4),
        h_from_synthetic_arl0=round(h_arl, 4),
        false_alarms_at_tuned_h=fa_at_h_nc,
        total_negative_control_buckets=total_buckets,
        synthetic_arl0_at_tuned_h=round(synth_arl0, 1),
    )
    return tuned_h, prov, thresholds


def write_policy_version(
    db_path: Path, cusum_h: float, thresholds: dict, merchant_ids: List[str]
) -> Dict[str, int]:
    now_ms = SystemClock().now_ms()
    conn = _connect(db_path)
    versions: Dict[str, int] = {}
    try:
        for merchant_id in merchant_ids:
            prev = conn.execute(
                "SELECT rules_config, cusum_rho, cusum_bucket_s, drift_window_s, hysteresis_gap, "
                "cooldown_seconds, allow_auto_block, auto_ceiling, k_max_entities, control_fraction "
                "FROM policy_config WHERE merchant_id = ? ORDER BY version DESC LIMIT 1",
                (merchant_id,),
            ).fetchone()
            if prev is None:
                continue
            versions[merchant_id] = append_policy_config(
                conn,
                merchant_id,
                thresholds=thresholds,
                rules_config=json.loads(prev["rules_config"] or "{}"),
                created_at=now_ms,
                hysteresis_gap=float(prev["hysteresis_gap"]),
                cooldown_seconds=int(prev["cooldown_seconds"]),
                cusum_rho=float(prev["cusum_rho"]),
                cusum_h=float(cusum_h),
                cusum_bucket_s=int(prev["cusum_bucket_s"]),
                drift_window_s=int(prev["drift_window_s"]),
                allow_auto_block=bool(prev["allow_auto_block"]),
                auto_ceiling=str(prev["auto_ceiling"]),
                k_max_entities=int(prev["k_max_entities"]),
                control_fraction=float(prev["control_fraction"]),
            )
    finally:
        conn.close()
    return versions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/corpus/tollgate.db")
    ap.add_argument("--demo-db", default="tollgate.db")
    args = ap.parse_args()

    cusum_h, prov, thresholds = tune(Path(args.db))

    conn = _connect(Path(args.db))
    try:
        merchant_ids = [
            r["merchant_id"]
            for r in conn.execute("SELECT DISTINCT merchant_id FROM policy_config ORDER BY merchant_id")
        ]
    finally:
        conn.close()
    v_corpus = write_policy_version(Path(args.db), cusum_h, thresholds, merchant_ids)

    v_demo: Dict[str, int] = {}
    if Path(args.demo_db).exists():
        v_demo = write_policy_version(Path(args.demo_db), cusum_h, thresholds, ["merchant_demo"])

    print(json.dumps({
        "provenance": prov.to_dict(),
        "policy_versions_corpus": v_corpus,
        "policy_versions_demo": v_demo,
        "thresholds": thresholds,
    }, indent=2))


if __name__ == "__main__":
    main()
