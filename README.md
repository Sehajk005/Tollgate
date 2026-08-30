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
uv run python -m scripts.learn_store_baseline --db data/corpus/tollgate.db --demo-db tollgate.db  # Day 6
uv run python -m scripts.tune_cusum          --db data/corpus/tollgate.db --demo-db tollgate.db  # Day 6
TOLLGATE_REDIS_URL=redis://localhost:6379 \
  uv run uvicorn services.scorer.app:create_app --factory --port 8080
npm --prefix services/dashboard install && npm --prefix services/dashboard run dev   # :5174
npm --prefix services/storefront install && npm --prefix services/storefront run dev # :5173
```

Put the printed API key in `services/dashboard/.env` and
`services/storefront/.env` as `VITE_TOLLGATE_API_KEY=...` (gitignored, never
committed). Open `http://localhost:5174`, press **Launch** in the DC strip —
on an `easy` replay the threat band moves to **UNDER ATTACK**, the
`ENFORCEMENT` tile climbs (`2 / 10`), and Layer 2b opens incidents that
resolve to `challenge`. The `store_baseline` + tuned `policy_config` steps are
required for Layer 2 to load; without them the scorer runs the byte-identical
Day-5 rules+model path. Because replay `attempt_uid`s are deterministic per
`(tier, seed)`, re-run `scripts.seed_merchant` (fresh `tollgate.db`) after
re-tuning the policy so the demo DB does not carry `INSERT OR IGNORE`-shadowed
rows from an earlier policy version.

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

## Layer 2 + policy (Day 6)

```
uv run python -m scripts.learn_store_baseline --db data/corpus/tollgate.db --demo-db tollgate.db
uv run python -m scripts.tune_cusum          --db data/corpus/tollgate.db --demo-db tollgate.db
uv run python -m scripts.seed_merchant        # if tollgate.db does not exist yet
```

Day 6 makes the system **decide**: entity-scoped, cost-derived,
hysteresis-damped, blast-radius-capped, and **never automatically above
`challenge`** (Threat Model §4/P1).

- **`packages/detect/cusum.py`** — Layer 2a, a one-sided Poisson CUSUM over
  `τ_flag`-gated counts per 10 s bucket. `τ_flag = CostModel.tier_ladder()["throttle"]`
  (≈ 0.0647, *derived*, never a literal — Decision 70). `steps_to_alarm` is the closed form
  the analytic gate checks against; empty buckets decay `S_t` by exactly `(λ₁−λ₀)`.
- **`packages/detect/drift.py`** — Layer 2b, a one-sided Wald SPRT on 95th-percentile
  exceedance of `distinct_cards_per_ip_30m` per `ip` / `ipua` (Decision 73). Toggle with
  `config/policy.yaml: drift.enabled`.
- **`packages/detect/episode.py`** — the incident state machine
  (`OPEN → ESCALATED → COOLING → CLOSED`, `CLOSED` terminal; re-fire in cooldown *merges*).
  Owns the harm fields: `attempts_before_alert`, `cards_exposed_before_alert`,
  `time_to_detect_s` (event time), `cusum_stat_at_alert`, `peak_tier`.
- **`packages/detect/policy.py`** — entity resolution (`card → ipua → ip`, never `asn`;
  store-wide is *unrepresentable*), the cost-derived threshold ladder read from
  `PolicySnapshot.thresholds` (no `eval/` dependency on the serving path), P3 corroboration,
  hysteresis (`θ_T` enter / `θ_T − 0.08` exit), the `challenge` auto-ceiling, `K_max`
  advisory mode, and the deterministic one-per-block-of-20 control arm.
- **`scripts/learn_store_baseline.py`** learns the `store_baseline` row **from the 7
  negative-control runs only**, re-scored through `models/` so `flagged_rate_mean` (p̄₀)
  matches the serving regime (Decision 83). **`scripts/tune_cusum.py`** tunes `cusum_h`
  from those same negative controls (ARL₀ ≥ 8,640 buckets; provenance names every merchant
  it reads — no `kind='attack'` row is ever touched) and writes a new `policy_config`
  version carrying `cusum_h` **and** `thresholds = CostModel.tier_ladder()` (`{0.065,
  0.257, 0.509, 0.874}`).
- **Guarded serving:** `services/scorer/deps.py::_load_layer2` loads the policy / baseline /
  engines exactly like `_load_model`; when a policy or baseline row is absent every
  `attempt_score` and SSE field is **byte-identical to Day 5** (verified: the rebuilt
  corpus's `attempt_score` digest is unchanged). One `store.score_path()` call per score is
  preserved (the 30 m distinct-card window is an 11th `WindowRequest` in the same call).
- **Persistence:** incidents / entities / tier transitions / enforcement actions flow
  through the existing spool → drainer → SQLite path; `enforcement_action` rows for
  `step_up` / `block` carry `confirmed_by IS NULL` and `applied_at IS NULL` (proposed, never
  applied). SSE gains `incident` (pseudonym only), `enforcement` (`active / k_max /
  advisory_mode`), `control_arm`; the D1 `ENFORCEMENT` tile is live and the advisory banner
  renders monochrome at the cap.
- **In practice:** with the weak 4-feature Day-5 model loaded, p̄₀ ≈ 0.60, so Layer 2a is
  conservative and **Layer 2b is the operative Layer-2 detector for `easy` / `medium`**
  (TTD ≈ 76 s in a demo replay). **`hard` is undetected by Layer 2** and is reported as
  such, not tuned around (Decision 83). The R1–R3 rule floors stay active on every tier.
- **Deferred (Day 7+):** Redis-backed CUSUM / enforcement state; `bin_metadata` load / real
  AFA ladder activation; the incident-detail screen / confirmation API / Gemini narrator
  (Day 8); rendering Layer-2 harm metrics into `eval/report.py` (Day 8/9); reinstating the
  `_q` / `*_sigma` / decline model features (Decision 16/64).

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

Day 6 adds `pytest -q -m metamorphic` (the M1–M8 Layer-2 relations) and ~65
new tests: `tests/acceptance/test_{cusum_analytic,cusum_tuning_isolation,
episode_state_machine,hysteresis,entity_required,enforcement_confirmation,
blast_radius,control_arm,policy_pinning,metamorphic}.py`,
`tests/unit/test_{cusum_recursion,drift_sprt,ladder_selection,
entity_narrowest}.py`, and the non-gating characterization snapshot
`tests/characterization/test_incident_shape.py`. Full suite:
**279 passed, 10 skipped (Redis), 2 xfailed** (both `handmade_40` gates).
The Day-6 integration acceptance tests seed a throwaway `tmp_path` DB via
`tests/acceptance/_day6_helpers.py` and never touch the corpus.

`tests/acceptance/test_handmade_40.py` (Day-3 feature values) **and**
`tests/acceptance/test_handmade_40_incident.py` (the Day-6 incident alert
point — one incident opens at the hand-counted `alert_seq`) both show as
`xfail` in every run until a human supplies `tests/fixtures/handmade_40.
{jsonl,expected.jsonl,sha256}` (the incident gate also reads one extra line,
`{"seq": null, "incident": {"alert_seq": N, ...}}`, from the expected file).
It is the one oracle in the suite that must not be generated by an
implementation agent (Decisions.md decision 14): an agent authoring both the
fixture and its expected values would produce a self-consistent artifact with
zero oracle value. Both `xfail`s become real pass/fail gates the moment the
files land, with no code change required. **`day-6-done` is not tagged until
the incident gate is green against that human fixture.**

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
