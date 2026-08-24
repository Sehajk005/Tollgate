# Baseline dataset grounding

Source: Day-2 Plan §D Decision 29 / §F "Baseline model" grounding chain.

## Attribution (CC BY 4.0)

> Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning
> Repository. https://doi.org/10.24432/C5CG6D. Licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The dataset records transactions for a UK-based, registered non-store online
retailer, 2009-12-01 to 2011-12-09 (1,067,371 line-item rows across two
sheets). Redistribution of a derived, aggregated artifact is permitted under
CC BY 4.0 with attribution -- this README, and the `source` field embedded
in `online_retail_ii.profile.json` itself, are that attribution.

## What is committed vs. gitignored

| file | committed? | contents |
|---|---|---|
| `online_retail_II.xlsx` | **no** (`.gitignore`: `data/baseline/*.xlsx`) | the raw 43.5 MB dataset, downloaded once |
| `online_retail_ii.profile.json` | yes | derived, integer-only profile (~12 KB) |
| `online_retail_ii.profile.sha256` | yes | SHA-256 of the profile file |

## Regenerating the raw dataset

```
curl -L -o data/baseline/online_retail_ii.zip \
  https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
unzip data/baseline/online_retail_ii.zip -d data/baseline/
rm data/baseline/online_retail_ii.zip
```

## Regenerating the derived profile

```
uv sync --extra dev --extra data
uv run python -m scripts.distill_baseline \
  --in data/baseline/online_retail_II.xlsx --out data/baseline/
```

`scripts/distill_baseline.py` is the only place `pandas`/`openpyxl` run
(dev-only extra; never imported by `packages/simulator` at runtime -- see
`tests/acceptance/test_simulator_safety.py`). It aggregates line items to
order level, drops cancelled invoices (`Invoice` starting `C`) and
non-positive totals, and records:

- `source` -- this attribution string
- `rows_aggregated` -- raw line-item row count (1,067,371)
- `orders` -- valid aggregated invoice count after filtering
- `mean_order_value_gbp_minor` -- mean order value, GBP pence
- `hour_of_week_weights` -- 168 integer counts (Monday 00:00 = index 0)
- `order_value_quantiles_minor_gbp` -- 1001-point order-value quantile
  table, GBP pence, 0.0% to 100.0% in 0.1% steps

Every value is an `int` or `str` (enforced by the script itself before
writing); this is the determinism boundary Day-2 Plan §F describes --
`packages/simulator/profile.py` loads this file at runtime, verifies its
SHA-256, and never touches pandas or the raw xlsx again.
