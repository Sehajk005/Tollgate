"""
python -m scripts.learn_store_baseline [--db data/corpus/tollgate.db] [--demo-db tollgate.db]

Source: Day-6 Plan §3.7 -- `store_baseline` has 0 rows and no Day-6 detector
can run without it. lambda_0(t) needs `hourly_volume_profile` and
`flagged_rate_mean` (p_bar_0); L2b needs `cards_per_ip_quantiles["30m"]`.

Reads ONLY the 7 negative-control runs already in the corpus
(m-eval-12..18, episode_truth.kind = 'negative_control'). Writes one
`store_baseline` row per negative-control merchant plus one aggregated row
for `merchant_demo` (the live demo merchant).

Explicit scope boundary (Day-6 Plan §3.7 / D11): the row is consumed ONLY by
packages/detect/. It is deliberately NOT wired into compute_features, so
`distinct_cards_per_ip_5m_q`, `amount_percentile_vs_store` and the `*_sigma`
features stay at their neutral 0.0 -- populating them would change the
model's inputs and invalidate models/, models/audit.json and every eval_run
row. Reinstating them remains Decision 16/64's deferred work.

`tau_flag` is DERIVED here from CostModel.tier_ladder()['throttle'] -- never
a literal (Day-6 Plan D1). This script lives in scripts/, so importing
eval.cost is fine (packages/detect/ imports no eval.*).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from eval.cost import load_cost_model
from packages.clock.clock import SystemClock

DEFAULT_MODEL_DIR = Path("models")

MS_PER_HOUR = 3_600_000
NEGATIVE_CONTROL_MERCHANTS = tuple(f"m-eval-{i:02d}" for i in range(12, 19))
DEMO_MERCHANT_ID = "merchant_demo"

WINDOW_5M_MS = 5 * 60_000
WINDOW_30M_MS = 30 * 60_000
QUANTILE_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _percentile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]))


def _quantile_grid(values: List[float]) -> List[float]:
    s = sorted(values)
    return [round(_percentile(s, q), 6) for q in QUANTILE_GRID]


def _hourly_volume_profile(ingest_times: List[int]) -> List[float]:
    """24-bin histogram by hour-of-day (arithmetic, no datetime). Bins with
    no observation are flat-filled with the mean of the observed bins, so
    lambda_0(t) never collapses to lambda_min in an hour the store simply
    did not span in a 3-hour negative-control run (limitation stated in
    README)."""
    counts = [0] * 24
    span_hours: Dict[int, set] = {h: set() for h in range(24)}
    for t in ingest_times:
        h = (t // MS_PER_HOUR) % 24
        counts[h] += 1
        span_hours[h].add(t // MS_PER_HOUR)
    profile: List[float] = []
    observed: List[float] = []
    for h in range(24):
        if span_hours[h]:
            rate = counts[h] / max(1, len(span_hours[h]))
            profile.append(rate)
            observed.append(rate)
        else:
            profile.append(0.0)
    mean_observed = sum(observed) / len(observed) if observed else 0.0
    return [round(p if p > 0.0 else mean_observed, 6) for p in profile]


def _sliding_distinct_cards(rows: List[Tuple[int, str]], window_ms: int) -> List[int]:
    """The max distinct-card count seen in any `window_ms` sliding window
    over one IP's time-sorted stream."""
    rows = sorted(rows)
    dq: deque = deque()
    counts: Dict[str, int] = {}
    best = 0
    for t, card in rows:
        dq.append((t, card))
        counts[card] = counts.get(card, 0) + 1
        while dq and dq[0][0] <= t - window_ms:
            _, old = dq.popleft()
            counts[old] -= 1
            if counts[old] == 0:
                del counts[old]
        best = max(best, len(counts))
    return [best]


def _load_serving_scorer(model_dir: Path):
    """Return a fn feature_snapshot -> p_calibrated matching the SERVING
    regime: the Layer-1 model + Platt calibrator when models/ is loadable,
    else None (caller falls back to the stored rules-only score_calibrated).

    Without this, p_bar_0 is learned from the model-less corpus (~1.0) while
    the live path runs the model, so lambda_0 is wildly over-estimated and
    Layer 2a never accumulates. Re-scoring here keeps p_bar_0 regime-consistent.
    """
    try:
        from packages.detect.calibrate import Calibrator, serving_prior
        from packages.detect.model import Layer1Model, artifact_exists
        from packages.features.compute import FEATURE_NAMES
    except Exception:  # noqa: BLE001
        return None
    if not artifact_exists(model_dir) or not (model_dir / "platt-v1.json").exists():
        return None
    try:
        model = Layer1Model.load(model_dir)
        calib = Calibrator.load(model_dir / "platt-v1.json")
        pi_s = serving_prior("in_control", load_cost_model())

        def _score(snapshot: dict) -> float:
            x = [float(snapshot[name]) for name in FEATURE_NAMES]
            return calib.apply(model.margin(x), pi_s)

        return _score
    except Exception:  # noqa: BLE001
        return None


def _learn_one(
    conn: sqlite3.Connection, merchant_ids: Tuple[str, ...], tau_flag: float, serving_scorer=None
) -> dict:
    placeholders = ",".join("?" for _ in merchant_ids)
    attempts = conn.execute(
        f"""
        SELECT a.ip AS ip, a.card_hash AS card_hash, a.ingest_time AS ingest_time,
               a.amount_minor AS amount_minor, s.score_calibrated AS score_calibrated,
               s.feature_snapshot AS feature_snapshot
        FROM auth_attempt a JOIN attempt_score s ON a.attempt_uid = s.attempt_uid
        WHERE a.merchant_id IN ({placeholders})
        ORDER BY a.ingest_time
        """,
        merchant_ids,
    ).fetchall()

    ingest_times = [int(r["ingest_time"]) for r in attempts]
    amounts = sorted(int(r["amount_minor"]) for r in attempts)
    n = len(attempts)

    def _p_calibrated(row) -> float:
        if serving_scorer is not None:
            try:
                return serving_scorer(json.loads(row["feature_snapshot"]))
            except Exception:  # noqa: BLE001
                pass
        return float(row["score_calibrated"])

    flagged = sum(1 for r in attempts if _p_calibrated(r) >= tau_flag)
    flagged_rate = flagged / n if n else 0.0

    by_ip: Dict[str, List[Tuple[int, str]]] = {}
    for r in attempts:
        by_ip.setdefault(r["ip"], []).append((int(r["ingest_time"]), r["card_hash"]))

    cards_5m: List[float] = []
    cards_30m: List[float] = []
    for ip_rows in by_ip.values():
        cards_5m.extend(_sliding_distinct_cards(ip_rows, WINDOW_5M_MS))
        cards_30m.extend(_sliding_distinct_cards(ip_rows, WINDOW_30M_MS))

    return {
        "hourly_volume_profile": json.dumps(_hourly_volume_profile(ingest_times)),
        "decline_rate_mean": 0.0,
        "decline_rate_std": 0.0,
        "amount_p05_minor": int(_percentile(amounts, 0.05)),
        "amount_p50_minor": int(_percentile(amounts, 0.50)),
        "amount_p95_minor": int(_percentile(amounts, 0.95)),
        "bin_entropy_mean": 0.0,
        "bin_entropy_std": 0.0,
        "foreign_bin_share_mean": 0.0,
        "foreign_bin_share_std": 0.0,
        "cards_per_ip_quantiles": json.dumps(
            {"5m": _quantile_grid(cards_5m), "30m": _quantile_grid(cards_30m)}
        ),
        "flagged_rate_mean": round(flagged_rate, 6),
        "sample_count": n,
        "is_stable": 0,
    }


_COLS = (
    "merchant_id", "hourly_volume_profile", "decline_rate_mean", "decline_rate_std",
    "amount_p05_minor", "amount_p50_minor", "amount_p95_minor", "bin_entropy_mean",
    "bin_entropy_std", "foreign_bin_share_mean", "foreign_bin_share_std",
    "cards_per_ip_quantiles", "flagged_rate_mean", "sample_count", "is_stable", "updated_at",
)


def _write_row(conn: sqlite3.Connection, merchant_id: str, row: dict, now_ms: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
        "api_key_hash, outcome_hmac_key_hash, created_at) "
        "VALUES (?, 'baseline', 'INR', 'Asia/Kolkata', 'baseline', 'baseline', 0)",
        (merchant_id,),
    )
    values = {**row, "merchant_id": merchant_id, "updated_at": now_ms}
    placeholders = ", ".join("?" for _ in _COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _COLS if c != "merchant_id")
    conn.execute(
        f"INSERT INTO store_baseline ({', '.join(_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(merchant_id) DO UPDATE SET {updates}",
        tuple(values[c] for c in _COLS),
    )


def run(db_path: Path, demo_db_path: Optional[Path] = None, model_dir: Path = DEFAULT_MODEL_DIR) -> dict:
    cost_model = load_cost_model()
    tau_flag = cost_model.tier_ladder()["throttle"]
    now_ms = SystemClock().now_ms()
    serving_scorer = _load_serving_scorer(model_dir)

    conn = _connect(db_path)
    try:
        per_merchant = {
            m: _learn_one(conn, (m,), tau_flag, serving_scorer) for m in NEGATIVE_CONTROL_MERCHANTS
        }
        aggregate = _learn_one(conn, NEGATIVE_CONTROL_MERCHANTS, tau_flag, serving_scorer)
        for m, row in per_merchant.items():
            _write_row(conn, m, row, now_ms)
        _write_row(conn, DEMO_MERCHANT_ID, aggregate, now_ms)
        conn.commit()
    finally:
        conn.close()

    if demo_db_path is not None and Path(demo_db_path).exists():
        dconn = _connect(demo_db_path)
        try:
            _write_row(dconn, DEMO_MERCHANT_ID, aggregate, now_ms)
            dconn.commit()
        finally:
            dconn.close()

    return {
        "tau_flag": tau_flag,
        "serving_scorer": "model+calibrator" if serving_scorer is not None else "rules-only",
        "merchants_written": list(per_merchant) + [DEMO_MERCHANT_ID],
        "flagged_rate_mean_aggregate": aggregate["flagged_rate_mean"],
        "cards_per_ip_quantiles_aggregate": json.loads(aggregate["cards_per_ip_quantiles"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/corpus/tollgate.db")
    ap.add_argument("--demo-db", default="tollgate.db")
    args = ap.parse_args()
    print(json.dumps(run(Path(args.db), Path(args.demo_db)), indent=2))


if __name__ == "__main__":
    main()
