"""
python -m scripts.distill_baseline --in <xlsx> --out data/baseline/

Source: Day-2 Plan §F "Baseline model" grounding chain / Decision 29 --
distills the raw UCI Online Retail II dataset (CC BY 4.0, gitignored, never
committed) into a small, integer-only, committed derived profile that
packages/simulator/profile.py loads at runtime. This script IS the
determinism boundary (Day-2 Plan §F diagram): pandas/openpyxl run here,
once, dev-only, and never again -- packages/simulator itself is stdlib +
pyyaml only (enforced by tests/acceptance/test_simulator_safety.py's
import-closure scan, which does not cover this script by design -- see
Decision 28's "keeps the safety import-closure small").

Requires `uv sync --extra dev --extra data` (pandas, openpyxl). Not on
packages/simulator's runtime import path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

# Source: Day-2 Plan §D Decision 29 -- "UCI Online Retail II, CC BY 4.0
# (verified: 1 067 371 rows, 43.5 MB xlsx, Chen 2012, doi:10.24432/C5CG6D)".
ATTRIBUTION = (
    "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning "
    "Repository. https://doi.org/10.24432/C5CG6D. Licensed under CC BY 4.0."
)

REQUIRED_COLUMNS = ["Invoice", "Quantity", "InvoiceDate", "Price"]
QUANTILE_POINTS = 1001  # Day-2 Plan §F -- "1001-point integer quantile table"
HOUR_OF_WEEK_BINS = 168  # 24 hours * 7 days; index 0 = Monday 00:00-01:00


def _load_all_sheets(xlsx_path: Path) -> pd.DataFrame:
    xls = pd.ExcelFile(xlsx_path)
    frames = [
        pd.read_excel(xls, sheet_name=sheet, dtype={"Invoice": str, "StockCode": str})
        for sheet in xls.sheet_names
    ]
    return pd.concat(frames, ignore_index=True)


def _aggregate_to_orders(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Source: Day-2 Plan §F step 1 -- "Group by Invoice; order value =
    Sum(Quantity x Price); drop cancellations (Invoice starting 'C') and
    non-positive totals; take the first InvoiceDate per invoice."
    """
    raw = raw.dropna(subset=REQUIRED_COLUMNS)
    raw = raw[~raw["Invoice"].str.startswith("C")]
    raw = raw.assign(line_total=raw["Quantity"] * raw["Price"])
    orders = raw.groupby("Invoice").agg(
        order_total=("line_total", "sum"),
        first_ts=("InvoiceDate", "min"),
    )
    return orders[orders["order_total"] > 0]


def _hour_of_week_weights(timestamps: pd.Series) -> list:
    """Source: Day-2 Plan §F step 2 -- "168 hour-of-week integer weights"."""
    bin_index = timestamps.dt.dayofweek * 24 + timestamps.dt.hour
    counts = bin_index.value_counts().reindex(range(HOUR_OF_WEEK_BINS), fill_value=0)
    return [int(c) for c in counts.sort_index().tolist()]


def _quantile_table_minor_gbp(order_totals_gbp: pd.Series) -> list:
    """Source: Day-2 Plan §F step 3 -- "1001-point quantile table in GBP minor units"."""
    fractions = [i / (QUANTILE_POINTS - 1) for i in range(QUANTILE_POINTS)]
    q_values_gbp = order_totals_gbp.quantile(fractions, interpolation="linear")
    return [int(round(v * 100)) for v in q_values_gbp.tolist()]


def build_profile(xlsx_path: Path) -> dict:
    raw = _load_all_sheets(xlsx_path)
    rows_aggregated = len(raw)
    orders = _aggregate_to_orders(raw)

    return {
        "source": ATTRIBUTION,
        "rows_aggregated": int(rows_aggregated),
        "orders": int(len(orders)),
        "mean_order_value_gbp_minor": int(round(orders["order_total"].mean() * 100)),
        "hour_of_week_weights": _hour_of_week_weights(orders["first_ts"]),
        "order_value_quantiles_minor_gbp": _quantile_table_minor_gbp(orders["order_total"]),
    }


def _assert_no_floats(obj, path: str = "root") -> None:
    # Source: Day-2 Plan §F -- "THE DETERMINISM BOUNDARY (committed, ~40 KB)
    # ... integer tables only". packages/simulator/profile.py (Step 4) loads
    # this file at runtime and must never see a float.
    if isinstance(obj, bool):
        return
    if isinstance(obj, float):
        raise TypeError(f"{path}: float leaked into the committed profile: {obj!r}")
    if isinstance(obj, dict):
        for key, value in obj.items():
            _assert_no_floats(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _assert_no_floats(value, f"{path}[{index}]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_dir", required=True, type=Path)
    args = parser.parse_args()

    profile = build_profile(args.in_path)
    _assert_no_floats(profile)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = args.out_dir / "online_retail_ii.profile.json"
    sha_path = args.out_dir / "online_retail_ii.profile.sha256"

    with open(profile_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(profile, fh, indent=2, sort_keys=True, ensure_ascii=True)
        fh.write("\n")

    digest = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    with open(sha_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{digest}  {profile_path.name}\n")

    print(f"Wrote {profile_path} ({profile_path.stat().st_size} bytes)")
    print(f"orders={profile['orders']} rows_aggregated={profile['rows_aggregated']}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
