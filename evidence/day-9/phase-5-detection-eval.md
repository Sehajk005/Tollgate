# Day 9 — Phase 5: Detection & Evaluation QA

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 5. This is a major release gate.
**Stop condition S-6** (`d6.json` / `models/audit.json` SHA changed without a
deliberate reviewed diffed regeneration): **NOT triggered** — see §1.

---

## 1. DEF-D9-003 reconciliation — done first, before any `diff_d6.py`

The plan requires the corpus / `d6.json` provenance drift from Session 1 to be
reconciled and the evaluation artifacts proven valid *before* the D6 gate runs.

### What drifted (exact scope)

| Item | Baseline | Now | Nature |
|---|---|---|---|
| `data/corpus/tollgate.db` SHA-256 | `7f6ef6dd…` (recorded in `d6.json.provenance.corpus_db_sha256`) | `9e1e3346…` | gitignored 18 MB input file |
| `store_baseline.updated_at` | (original, unknown) | `1788419860256` on **all 8 rows** | wall-clock metadata column (`learn_store_baseline.py:222` stamps `SystemClock().now_ms()`) |
| `policy_config` | 156 rows, `MAX(version)=8` | 156 rows, `MAX(version)=8` | 20 rows appended by an early bootstrap iteration were **already deleted** in Session 1; `freelist_count=1` free page remains |
| `attempt_score` (the data the eval consumes) | 10,512 rows | 10,512 rows | **untouched** |
| `PRAGMA integrity_check` | — | `ok` | — |

### S-6 frozen artifacts — all unchanged from Phase 0

```
eval/outputs/d6.json      29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737  ✓
models/audit.json         ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c  ✓
models/l1-lgbm-v1.json    7cb7fa8a187129bb300147d97ca97354cf52b9d944065da8a4669f42de5b66cc  ✓
models/platt-v1.json      22dc48f0a47db1447862781d241d641d7e5145c6ea94bc9fd1f64d5c7b508864  ✓
```

### Metadata-only or affects evaluation semantics?

**Metadata-only — proven by regeneration.**
`uv run python -m eval.harness --split all --seed 42 --corpus-db data/corpus/tollgate.db --model-dir models/ --out <scratch>`
run twice → **run A ≡ run B** (only the `--out` path echoed in `generation_command`
differs). The harness is fully deterministic.

`scripts/diff_d6.py eval/outputs/d6.json <scratch>/d6.json` with the plan's exact
ignore set (`build_hash, generated_at, head_at_generation, tree_dirty_at_generation`)
→ **exactly 2 changed leaves, both provenance metadata:**

```
~ provenance.corpus_db_sha256:   7f6ef6dd… -> 9e1e3346…   (the drift itself)
~ provenance.generation_command: …--model-dir models --out eval/outputs
                              -> …--model-dir models/ --out <scratch>   (invocation echo)
```

`diff_d6.py … --ignore provenance` → **`0 substantive difference(s)`.**
`report.md`: byte-identical excluding the volatile provenance lines.

**Every metric block reproduces bit-for-bit:** block1 per-tier (incl. `tier_e`),
block2 negative controls + `theta_challenge`, block3 discriminability audit
(24 rows), block4 cost (curves, optima, rupee gap), block5 calibration (ECE /
Brier / reliability at π₀ and π₁), block6 baselines (B0, B1, B2, sanity floors),
ROC/PR, prevalence transform. The corpus's `store_baseline` rows are read by the
*serving* Layer-2 load, **not** by the offline eval harness, and `d6.json` pins
`policy_version: 1` (intact).

### Reconciliation verdict

- `eval/outputs/d6.json` is **NOT contaminated** — SHA `29edcb22…` byte-identical
  to Phase 0, and it reproduces with **zero substantive metric differences**.
- The drift is confined to a wall-clock metadata column + one freelist page. The
  original corpus SHA `7f6ef6dd…` was itself a snapshot of a **non-byte-deterministic
  build** (`learn_store_baseline` stamps a wall-clock `updated_at`), so a documented
  rebuild would break the exact-hash check anyway. Bit-identical restoration is not
  possible — the 8 original `updated_at` values are unrecoverable (corpus gitignored,
  never tracked).
- `eval/outputs/d6.json` is **left untouched** (not regenerated) — the plan requires
  its SHA to stay unchanged, and regenerating for a cosmetic provenance-hash update
  would bake a QA-session `head_at_generation` / timestamp into a committed
  evaluation artifact (Plan §8).
- `test_d6_provenance::test_corpus_identity_is_recorded_and_matches_the_real_corpus`
  **stays RED**, documented as **DEF-D9-003 (P2, known limitation)** — a byte-exact
  hash check on a gitignored, non-deterministically-built input file. Not weakened,
  not deleted (Plan §8). It does **not** block this gate: the gate's real
  requirement — "0 substantive differences; `d6.json` SHA unchanged" — is **met**.

Evidence: `evidence/day-9/phase-5-diff_d6.txt`.

---

## 2. Detection — acceptance tests

`uv run pytest tests/ -q -k "<detection+eval subset>"` → **196 passed / 1 failed**
(the 1 = `test_corpus_identity`, DEF-D9-003). Green subset covers:

| Area | Tests | Result |
|---|---|---|
| Layer 2a CUSUM (analytic `steps_to_alarm`, empty-bucket decay) | `test_cusum_analytic` | ✅ |
| Layer 2b distinct-card SPRT / drift | `test_drift*`, `test_metamorphic` | ✅ |
| Platt calibration + prior correction + ECE | `test_calibration` | ✅ |
| Hysteresis (`θ_T` enter / `θ_T − 0.08` exit) | `test_hysteresis` | ✅ |
| Blast-radius `K_max` + advisory mode | `test_blast_radius` | ✅ |
| Control arm (deterministic 1-per-block-of-20) | `test_control_arm` | ✅ |
| Incident state machine `OPEN→ESCALATED→COOLING→CLOSED` (cooldown merge) | `test_episode_state_machine` | ✅ |
| Policy pinning / auto-ceiling = `challenge` | `test_policy_pinning`, `test_auto_ceiling`* | ✅ |
| Entity resolution `card → ipua → ip` (store-wide unrepresentable) | `test_entity*` | ✅ |
| P3 corroboration | `test_corroboration`* | ✅ |
| Metamorphic M1–M8 | `test_metamorphic` | ✅ (8/8) |
| Eval: harness sanity, splits, negative scenarios, discriminability audit, cost thresholds, prevalence, tier_e, time-travel, eval_run rows | `test_harness_sanity`, `test_splits`, … | ✅ |

---

## 3. Detection — live, against the running Compose stack

`easy` replay, seed 42, speed 60, `pace_from: episode`, through the real
`score_attempt` path. Harness: `phase-5-live-detection-harness.py` →
`phase-5-live-detection-results.json`. **8 / 8 substantive checks pass**
(the harness's 9th line searched for literal rule names `R1/R2/R3`; the rules are
recorded by *feature name*, so it read `False` — corrected below).

| Check | Result |
|---|---|
| event count `easy` = 821 | ✅ `finished 821/821`, terminal |
| R1 / R2 / R3 floors fire, recorded in `attempt_score.rules_fired` | ✅ `attempts_per_ip_60s` (R1), `distinct_cards_per_ip_5m` (R2), `distinct_cards_per_bin_5m` (R3) all present |
| decisions never AUTOMATICALLY exceed the `challenge` auto-ceiling | ✅ decision histogram over 821 events = `{allow: 269, challenge: 552}` — **zero `block`, zero `step_up`** |
| Layer 2b SPRT opens an incident | ✅ 2 incidents, `detector=drift`, `state=ESCALATED`, `peak_tier=challenge` |
| time-to-detect (event time) | 75.95 s / 78.39 s — matches README's "TTD ≈ 76 s" |
| harm fields populated | ✅ `attempts_before_alert` 32 / 36, `cards_exposed_before_alert` 32 / 32 |
| entity resolution — `ip` / `ipua` / `card` only, never store-wide / asn | ✅ `entity_type = ip` only (`198.51.100.57`, `198.51.100.249` — RFC 5737 doc range) |
| enforcement ledger | ✅ 2 actions `tier=challenge` `confirmed_by=auto` `requires_confirmation=0`; **no `step_up`/`block` proposed** on `easy` (expected — `easy` does not push past `challenge`) |
| SSE `enforcement` frame | ✅ `{active: 0, k_max: 10, advisory_mode: false}` |
| control arm | ✅ 29 / 821 attempts flagged `control_arm` (deterministic ≈ 1-per-block-of-20) |
| incident state machine terminal path | ✅ `ESCALATED → resolve(true_positive) → CLOSED`; every enforcement row `released_at` set |
| `reset` after | ✅ 200, `cleared={window_store:3234, threat, layer2, incidents, policy_engine, decision_cache, persisted_incidents:1}`, `degraded:false` |

Layer 2a **CUSUM does not trip on `easy`** live — by design (README: with the
weak 4-feature model p̄₀ ≈ 0.60, Layer 2a is conservative and Layer 2b is the
operative Layer-2 detector for `easy`/`medium`; `hard` is undetected by Layer 2
and reported as such). The analytic CUSUM gate (`test_cusum_analytic`) is green.

---

## 4. Evaluation — harness + D6

`uv run python -m eval.harness --split all --seed 42 --corpus-db
data/corpus/tollgate.db --model-dir models/ --out <scratch>` (14 s), diffed
against the committed `eval/outputs/d6.json`.

| Item | Verified |
|---|---|
| schema | `schema_version: 2`; blocks 1–6 + `tier_e` + `provenance` all present |
| provenance completeness | 5 EVAL9 attrs (`seed=42`, `policy_version=1`, `eval_prevalence=0.01`, `config_hash` 64-hex, `model_version`), `model_files_sha256` (4 files), `seeds_used=1`, `generation_command`, `head_at_generation`, `tree_dirty_at_generation` |
| deterministic reproduction | run A ≡ run B; **0 substantive metric differences** vs committed `d6.json`; `d6.json` SHA unchanged |
| per-tier incl `tier_e` | model easy **0.000** / medium **0.973** / hard **0.732** / evasive **0.391**; B0 easy **0.997** / medium **0.985** / hard **0.125** / evasive **0.284** — matches README verbatim |
| prevalence transform | π₀ = 0.001, π₁ = 0.9, π_t = 0.725, raw_prevalence = 0.643 |
| calibration / ECE | π₀: `ece_raw 0.262 → ece_platt 0.070 → ece_platt_prior 0.0007`; π₁: `prior_correction_helped_at_pi1: true` (Brier 0.341 → 0.202); reliability curves at both priors |
| cost model | `c_fn_minor=5200`, `c_fp_minor_challenge=1800`, `pi0=0.001`, `optima_coincident: true`, `rupee_gap_minor: 0.0` + `rupee_gap_is_structural: true` + full note (Decision 100), `regime_switch_saving_minor=23214508` |
| cost-optimal thresholds / tier ladder | `theta_challenge = 0.2571` (≈ 0.257, Decision 70); `decision_region_fpr_max = 0.00198` |
| ROC / PR | B0 `roc_auc=0.9943` `ap_raw=0.9970`; model `roc_auc=0.8893` `ap_raw=0.9453` — B0 beats the model (honesty requirement) |
| FP / FN behaviour | B1 (`fp=1, fn=1264, precision=0.990`), B2 (`fp=0, fn=385, recall=0.718`) confusion matrices present |
| negative controls | 7 scenarios (`flash_sale, corporate_nat, cgnat, retry_storm, subscription_batch, nri_traffic, shared_ip_legit`) × 6 scorers; `nri_traffic` marked **inert** in `report.md` |
| discriminability audit | 24 features, threshold 0.95; **6 excluded** (`attempts_per_ip_{5m,60s}`, `attempts_per_ipua_5m`, `distinct_amounts_per_ip_5m`, `distinct_cards_per_bin_5m`, `distinct_ips_per_bin_5m`), 14 constant un-fed → **model runs on 4 live features** |
| every metric with its measurement conditions | ✅ every recall figure in `report.md` carries "95% CI on achieved FPR […], n_neg=…, UNRESOLVABLE (too few negatives)"; `AlwaysPositiveScorer` → "unreachable (resolvable=False)", never a fake `0.000` (AUDIT-011 pattern) |
| sanity scorers | perfect=1.0, inverted=0.0, random≈0.001, always_positive=`unreachable` (honestly `available:false`) |

---

## 5. Verdict

**Phase 5 COMPLETE — the release gate PASSES.**

- DEF-D9-003 reconciled: `d6.json` uncontaminated (SHA `29edcb22…` unchanged),
  reproduces with **0 substantive metric differences**, drift is metadata-only.
  S-6 not triggered.
- Detection: 196/1 acceptance tests (the 1 = DEF-D9-003) + 8/8 live checks. R1/R2/R3
  floors fire and never auto-exceed `challenge`; Layer 2b opens ESCALATED
  incidents at TTD ≈ 76 s; entity resolution stays `ip`; state machine reaches
  `CLOSED` and releases enforcement; control arm deterministic.
- Evaluation: every block reproduces bit-for-bit; every metric carries its
  measurement conditions; B0-beats-model and Tier-E-0.39 honesty items intact.

**No new defects.** DEF-D9-003 remains OPEN (P2, documented known limitation —
byte-hash check on a non-deterministically-built gitignored input; zero metric
impact proven).
