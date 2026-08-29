# Tollgate

Pre-authorization card-testing defence. Day 1 shipped a rules-only walking
skeleton (`POST /v1/score` → auth → rules → decision → spool → SQLite → SSE
→ dashboard ticker). Day 2 added a deterministic, virtual-time-driven attack
simulator and replay so the dashboard's threat band moves against the real
scoring path. Day 3 added the real feature path: a Redis-backed sliding-window
store (one atomic Lua script per score call), the canonical 24-feature
definition (`packages/features/compute.py`), and a template narrator. Day 4
builds the thing that measures the thing that measures traffic: an offline
evaluation harness (`eval/`), validated against four analytically-known
sanity scorers before any real model exists to flatter. Day 5 adds Layer 1:
a persistent replay corpus of the exact logged feature vectors, a
discriminability audit run against that real data, an `l1-lgbm-v1` LightGBM
detector, a Platt calibrator with explicit serving-prior correction, and the
first real per-tier `eval_run` rows — the model informs the score, never the
decision. See `Flow.md` for the actual execution paths and `Decisions.md` for
the reasoning behind them.

**Completed: Days 1-5.** Days 6-8 (incident detection / CUSUM, the operator
dashboard, Gemini narrator) are not yet built.

## Running the demo

```
uv sync --extra dev
docker compose up -d redis                     # Day 3: the WindowStore backend
uv run python -m scripts.seed_merchant          # prints a demo API key
TOLLGATE_REDIS_URL=redis://localhost:6379 \
  uv run uvicorn services.scorer.app:create_app --factory --port 8080
npm --prefix services/dashboard install && npm --prefix services/dashboard run dev   # :5174
npm --prefix services/storefront install && npm --prefix services/storefront run dev # :5173
```

Put the printed API key in `services/dashboard/.env` and
`services/storefront/.env` as `VITE_TOLLGATE_API_KEY=...` (gitignored, never
committed). Open `http://localhost:5174`, press **Launch** in the DC strip.

`TOLLGATE_REDIS_URL` is optional. If it's unset, or Redis is unreachable at
startup, the scorer logs a fallback notice and runs on `InMemoryWindowStore`
instead — same `WindowStore` protocol, single-process only (window state
does not survive a restart and would not be shared across multiple Uvicorn
workers). `docker-compose.yml` also defines a `redis-small` service
(`maxmemory 2mb`, `allkeys-lru`); it exists only for the eviction-vs-TTL
test and the application never connects to it.

## Evaluation harness (Day 4)

`eval/` is an offline harness, independent of the live scoring path, that generates simulator
traffic, splits it, scores it with four analytically-known **sanity scorers** (perfect, random,
inverted, always-positive), and renders a report:

```
uv run python -m eval.harness --split all --seed 42 [--seeds 5] [--out eval/outputs/]
cat eval/outputs/report.md
```

- No model, no calibrator exist yet — the four sanity scorers are the "ruler," not a
  detector. `--seeds` defaults to `1` (a stated limitation; the individual acceptance tests
  still verify tolerances across 5 seeds independently — see `Decisions.md` decision 61).
- The report's six blocks (per-tier recall@FPR, negative controls, discriminability audit,
  cost, calibration, baselines) each render an explicit empty/deferred state rather than a
  fabricated number for anything Day 4 cannot yet measure (no incident detector, no
  calibrator, no replay corpus).
- `medium` is now a real attack tier (`config/attack_tiers.yaml`); only `evasive` stays
  `pending: "Day 7"`.
- Seven negative-control scenarios exist (`packages/simulator/negative.py`):
  `flash_sale, corporate_nat, cgnat, retry_storm, subscription_batch, nri_traffic,
  shared_ip_legit`. Generate one by hand:
  ```
  uv run python -m packages.simulator.generate --seed 42 --scenario nri_traffic \
      --out data/streams/n.jsonl --labels data/streams/n.labels.jsonl \
      --episodes data/streams/n.eps.jsonl
  ```
  `nri_traffic` is marked **inert** in the report — it controls for `bin_is_foreign_issued`,
  which stays `0.0` until the BIN-metadata join lands (still deferred after Day 5 — see
  `Flow.md` §10). `test_nri_control_tripwire.py` fails the moment that changes.

## Layer 1 (Day 5)

```
uv sync --extra dev
uv run python -m scripts.train_l1 --seed 42 --db data/corpus/tollgate.db --out models/ --rebuild-corpus
uv run python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db --model-dir models/ --write-eval-run
cat eval/outputs/report.md
```

- **`eval/corpus.py`** replays the full `build_runs(42)` layout (12 tier blocks + 7
  negative-control scenarios, one merchant per run) through the *identical* `score_attempt`
  core and persists the logged `attempt_score.feature_snapshot` vectors — the training
  corpus. `data/corpus/tollgate.db` is gitignored; rebuild with `--rebuild-corpus`.
- **`scripts/train_l1.py`** builds the corpus, runs the discriminability audit
  (`univariate_auc` over all 24 features on the easy+medium training set — writes
  `models/audit.json`, exits non-zero if a feature over `0.95` is not in
  `config/features.yaml: audit.excluded`), then trains `l1-lgbm-v1` (LightGBM, `objective=
  binary`, 200 trees, `max_depth=6`, `scale_pos_weight = n_neg/n_pos`, `num_threads=1`,
  `deterministic=True`, `seed=42`) and fits the Platt calibrator on a held-out `calib` slice.
- **Committed artifacts:** `models/l1-lgbm-v1.json` (`ModelArtifact`), `models/platt-v1.json`
  (`Calibrator`), `models/audit.json`. The booster (`models/l1-lgbm-v1.txt`) is gitignored
  and regenerated by `train_l1`.
- **Six features are excluded by the audit** (per-IP rate / fan-out counts that are
  near-perfect single-feature discriminators on the training tiers — Eval Protocol §4/V2's
  "likely simulator artifact"). They are zeroed on model input but **stay active in the
  R1/R3 rule floors and B0**. The model therefore runs on 4 live features and, as the report
  states, is weaker than B0 overall (`temporal_test` ROC-AUC 0.889 vs 0.994) and on `easy`,
  but competitive on `medium` and **decisively better on `hard`, where B0 fires 0/3 rules**
  (recall@1e-3 0.73 vs 0.13). See `Decisions.md` decision 64.
- **`eval.harness --write-eval-run`** writes the first real `eval_run` rows
  (`l1-lgbm-v1` on `temporal_test` + the attack-shape holdout, `rules-only-v0` on
  `temporal_test`), idempotent by `run_id`. Report Block 1 gains model + B0 rows, Block 3 is
  the real 24-row audit table, Block 5 is the real calibration table at π₀ and π₁, Block 6
  has the real B0 row. Blocks 2 and 4 are unchanged — `apply_auto_ceiling` and the decision
  rule are untouched; applying `θ_T` to the calibrated posterior is Day 6 (decision 57).
- **Serving:** with a `models/` artifact present, `services/scorer` computes and logs
  `score_raw` / `score_calibrated` / `top_contributors` / `model_version` between rules and
  policy; with no artifact the path is byte-identical to Day 4 (the rules-only fallback).

## Tests

```
uv run pytest -q                # full suite
uv run pytest -q -m safety      # simulator import-closure / egress safety
uv run pytest -q -m slow        # durability, lock contention, SSE, Day-2 E2E
uv run pytest -q -m characterization  # informational only, never a gate
uv run pytest -q -m redis       # Day-3 Redis-backed tests; skip cleanly if Redis is down
```

The Day-4 evaluation-harness tests (`tests/acceptance/test_harness_sanity.py`,
`test_cost_thresholds.py`, `test_splits.py`, `test_negative_scenarios.py`, and others) run as
part of the full suite with no extra flags or services required. `eval/harness.py` and
`eval/scorers.py` stay stdlib + `pyyaml` and import no `lightgbm`; on Day 5 `eval/corpus.py`
lazily bridges to `services/scorer` to build the replay corpus, and
`eval.harness --model-dir` loads a duck-typed model/calibrator from `packages/detect/`
(which owns the `lightgbm` dependency). The Day-5 corpus/model acceptance tests
(`test_time_travel.py`, `test_discriminability_audit.py`, `test_calibration.py`,
`test_eval_run_row.py`, …) reuse `data/corpus/tollgate.db` + `models/` when present and
otherwise rebuild them once per session (so a fresh clone rebuilds; `uv sync --extra dev`
installs `lightgbm`).

Redis-marked tests read `TOLLGATE_REDIS_URL` (default `redis://localhost:6379`)
and `TOLLGATE_REDIS_SMALL_URL` (default `redis://localhost:6380`, the
eviction test only) and skip — never fail — when unreachable, so
`uv run pytest -q` is green with or without `docker compose up -d` having
been run first.

`tests/acceptance/test_handmade_40.py` is expected to show as `xfail` in
every run until a human supplies `tests/fixtures/handmade_40.{jsonl,
expected.jsonl,sha256}` — the fixture format is documented in that test
file's docstring. It is the one oracle in the suite that must not be
generated by an implementation agent (Decisions.md decision 14): an agent
authoring both the fixture and its expected values would produce a
self-consistent artifact with zero oracle value. The `xfail` becomes a real
pass/fail gate the moment the files land, with no code change required.

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
