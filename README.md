# Tollgate

Pre-authorization card-testing defence. Day 1 shipped a rules-only walking
skeleton (`POST /v1/score` → auth → rules → decision → spool → SQLite → SSE
→ dashboard ticker). Day 2 adds a deterministic, virtual-time-driven attack
simulator and replay so the dashboard's threat band moves against the real
scoring path — see `Flow.md` for the actual execution paths and
`Decisions.md` for the reasoning behind them.

## Running the demo

```
uv sync --extra dev
uv run python -m scripts.seed_merchant        # prints a demo API key
uv run uvicorn services.scorer.app:create_app --factory --port 8080
npm --prefix services/dashboard install && npm --prefix services/dashboard run dev   # :5174
npm --prefix services/storefront install && npm --prefix services/storefront run dev # :5173
```

Put the printed API key in `services/dashboard/.env` and
`services/storefront/.env` as `VITE_TOLLGATE_API_KEY=...` (gitignored, never
committed). Open `http://localhost:5174`, press **Launch** in the DC strip.

## Tests

```
uv run pytest -q                # full suite
uv run pytest -q -m safety      # simulator import-closure / egress safety
uv run pytest -q -m slow        # durability, lock contention, SSE, Day-2 E2E
uv run pytest -q -m characterization  # informational only, never a gate
```

## Data attribution

The Day-2 baseline traffic model is grounded in a derived profile of the UCI
Online Retail II dataset:

> Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning
> Repository. https://doi.org/10.24432/C5CG6D. Licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Only the derived, integer-only profile (`data/baseline/online_retail_ii.profile.json`,
~12 KB) is committed — see `data/baseline/README.md` for the full grounding
chain and regeneration instructions. The raw dataset is never committed.

## Safety posture

`packages/simulator/` generates synthetic demo traffic only: opaque
identifiers, fictional BINs (a reserved, non-real IIN prefix), and
documentation/example IP ranges (RFC 5737). It never constructs real card
numbers, never performs Luhn validation, and never opens a network
connection or subprocess (`tests/acceptance/test_simulator_safety.py`
enforces this both statically — an AST import-closure scan — and at
runtime, by monkeypatching `socket.socket` to raise during a full
generation run and asserting it still succeeds). `/v1/stream` is
unauthenticated and binds loopback only for the demo; it publishes rule-fire
detail that would be a real disclosure risk on a public network — see
`01-THREAT-MODEL-v2.md`'s Day-2 addendum.
