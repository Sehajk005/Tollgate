# Tollgate — D6 Metrics Remediation: Implementation Log

**Plan:** `METRICS-REMEDIATION-PLAN-2026-09-02.md`
**Audit:** `METRICS-AUDIT-2026-09-02.md`
**Branch:** `day-2` · start HEAD `8cf17d9121d76ba22b42975bcbc88dfde5cc0eac` · working tree dirty (60 modified/untracked)
**Started:** 2026-09-02

This log records evidence for every phase gate, every scratch regeneration diff, and
every deviation, as required by the plan (§17.3, §28, §31).

---

## Recorded baseline SHAs (must be honoured at the end)

| Artifact | SHA-256 at start | Constraint |
|---|---|---|
| `eval/outputs/d6.json` | `058f7e8ec3182a5414113e2c47d4b1df47f99e17eb02b3ef8f290850ad13f770` | replaced exactly once, end of Phase 1, reviewed + diffed |
| `models/audit.json` | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` | **UNCHANGED at completion** (no retrain) |

Backups (outside the repo):
`…/scratchpad/phase0-backup/d6.committed.json` (sha `058f7e8e…`) ·
`…/scratchpad/phase0-backup/audit.committed.json` (sha `ce75cb7f…`)

Environment: Python 3.13.3 (`.venv`), Node v22.14.0, npm 11.7.0.
`data/corpus/tollgate.db` (18 MB) present; `models/{audit,l1-lgbm-v1,platt-v1}` present.

---

## PHASE 0 — Verify before touching anything  ✅ PASS

**Step 1 — backup.** `eval/outputs/d6.json` and `models/audit.json` copied outside the repo
and SHA-verified against the originals (see table above).

**Step 2 — `scripts/diff_d6.py`.** Written (NEW). Leaf-wise structural diff: flattens both
artifacts to dotted leaf paths (`foo[3]` for list elements), compares numbers with abs+rel
float tolerance (default 1e-9/1e-9), supports `--ignore <prefix>` (repeatable), exit 1 on
any surviving difference.

**Step 3 — scratch regeneration.**
```
python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db --model-dir models \
    --out <scratch>/d6-verify
```
Exit 0 in 13 s. `<scratch>/d6-verify/d6.json` written (26 897 bytes — identical size to the
committed file). **`eval/outputs/d6.json` SHA `058f7e8e…` unchanged before and after** — the
`--out` path is honoured, nothing under `eval/outputs/` was touched.

**Step 4 — diff.**
```
python scripts/diff_d6.py eval/outputs/d6.json <scratch>/d6-verify/d6.json \
    --ignore provenance.build_hash --ignore provenance.generated_at \
    --ignore provenance.head_at_generation --ignore provenance.tree_dirty_at_generation
→ 0 substantive difference(s) [added 0, removed 0, changed 0]
```
With **nothing** ignored, exactly one leaf differs:
```
~ provenance.build_hash:
    "9141a8ecc41be43182fdb3882cdf7a7045e3755fc3146be6b8563cda8c69198e"
 -> "36d0cc4817e171112b098bcc8a96416be57769f313e57ec2b99f93099243d113"
```
This matches the audit exactly (§4 header `9141a8ecc41b`; §8 "now" `36d0cc4817…`).
`build_hash` = HEAD + dirty flag + baseline-profile SHA + fixture SHA; HEAD moved and the
tree is dirty since the artifact was committed, so this divergence is expected and
plan-permitted (§17.3). `config_hash` (`a7db8c6118…`) and `fixture_sha256` (`5672a0e683…`)
reproduce identically; all six blocks and every metric leaf are byte-reproducible.

**Decision (per §17.3 interpretation table):** only ignored fields differ →
**the committed artifact is VERIFIED** against the current corpus, model and configs.
The audit's §5.5 J-class "unverified corpus provenance" unknown is **closed**.
Proceed to Phase 1. No user consultation required — the "stop and report" branch
(substantive value differences) did not trigger.

---

## PHASE 1 — Backend data completeness  ✅ COMPLETE

**Baseline backend test run (pre-change):** 117 D6-related tests pass (extended set: 135 pass).

### FIX-BE-06 — schema + provenance
- **NEW** `eval/d6_schema.py` — stdlib-only declarative `Field` spec + `validate()` walker
  + `validate_or_raise()`. Additive: every v1 leaf declared + required at v2; v2 leaves carry
  `min_version=2` (required at v2, tolerated at v1, never "unknown"). Verified: accepts the
  committed v1 artifact with 0 errors; 8 malformed mutations each produce a named,
  path-anchored error (missing block, `[]` curve, `schema_version 99`, wrong scalar type,
  disallowed null, unknown key, int→float).
- `eval/d6.py`: `SCHEMA_VERSION 1 → 2`; `write_artifact` now calls `validate_or_raise` before
  writing (generation boundary — an invalid artifact never hits disk); `_provenance` adds
  `generated_at` (ISO-8601 UTC), `generation_command`, `head_at_generation`,
  `tree_dirty_at_generation`, `corpus_db_sha256`, `model_files_sha256` (freshness model =
  config + corpus + model identity + generation metadata; `build_hash` divergence alone is
  NOT treated as staleness — plan §17.2, M-029). `build_artifact`/`write_artifact` gained
  optional `corpus_db`/`model_dir` kwargs, threaded from `harness.main()`.
- `eval/provenance.py` — **not modified** (reuse only): `_git_head_and_dirty` imported;
  file SHAs computed locally in `d6.py` with `hashlib`.

### FIX-BE-01 — θ_challenge derived (M-020)
- `eval/report.py`: `THETA_CHALLENGE = 0.257` (hand-typed, rounded down) → `@lru_cache`
  accessor `theta_challenge()` returning `load_cost_model().tier_ladder()["challenge"]` =
  `1800/(1800+5200)` = `0.2571428571428571`. Old name kept as a deprecated import-time alias.
  Both `report.py` call sites + `eval/d6.py::_block2_negative_controls` migrated.
- Acceptance: `grep -rn "0\.257" eval/` → **nothing** (docstring references the formula, not
  the number). `block2_theta_challenge == 0.2571428571428571` in the regenerated artifact.
  **Block-2 movement:** NONE — the 4 sanity scorers' FP counts are byte-identical before/after
  (no `random` score fell in `[0.257, 0.2571428…)`); the only Block-2 changes are the new
  model/B0 rows and the resulting list re-indexing.

### FIX-BE-04 — raw ECE + gap + verdict (M-010, M-036)
- `eval/harness.py::_regime`: adds `ece_raw` (identical `metrics.ece(raw, labels, n_bins, w)`
  call, over `raw = sigmoid(margins)` already in scope) and
  `ece_gap_platt_prior_vs_platt = ece_platt - ece_platt_prior`. Block level:
  `prior_correction_helped_at_pi1` (Eval §3.4's own pass/fail test).
- Verified: the 4 pre-existing calibration numbers are **byte-identical** post-regeneration
  (`0.07031799883085593`, `0.0007305349387266664`, `0.39547724058805567`,
  `0.2806765620747161`); `pi1.ece_raw = 0.20889069891274548`;
  `prior_correction_helped_at_pi1 = true` (0.3955 → 0.2807).

### FIX-BE-05 — CI relabel + separability derivation (M-040, M-011, M-013)
- `eval/load.py::_recall_json`: adds `fpr_ci_low`/`fpr_ci_high` (= the Wilson interval on the
  ACHIEVED FPR, correctly named) + `ci_basis: "wilson_on_achieved_fpr"`; `ci_low`/`ci_high`
  retained as deprecated aliases.
- `eval/report.py::_fmt_recall`: `95% CI` → `95% CI on achieved FPR` (the audit found only the
  frontend instance; this is the backend/report half).
- `eval/d6.py::_augment_audit_block` **(NEW)** — pure, deep-copies its input, **never mutates
  `models/audit.json` and never retrains**. Per feature: `separability = abs(auc-0.5)`,
  `direction` (`inverted`/`positive`/`null`; `null` for constants), `flagged_two_sided`
  (`>=` boundary, `not constant`). Block level: `univariate_auc_threshold` (= `max_univariate_auc`
  = 0.95) and `observed_max_univariate_auc` (`max` over non-constant = `0.9975874252835037`,
  `distinct_cards_per_bin_5m`). `models/audit.json` SHA `ce75cb7f…` **unchanged** post-run.

### FIX-BE-03 — Block 6 model row + B3 floor + per-tier (M-008, M-038)
- `eval/harness.py`: `BaselineSummary` gains `per_tier` (default `{}`); `_baseline_summary`
  gains `model_scorers` kwarg and computes per **stream-tier** {b1,b2,model,b0} operating
  points — B1/B2 scored **once** over the whole `temporal_test` timeline then **sliced by
  `stream_tier`** (bitemporal correctness; clean partition so tp/fp/tn/fn sum to overall).
  `HarnessRun` gains `model_scorers` (default `{}`), passed through.
- `eval/d6.py::_block6_baselines`: adds `model` (same shape as `b0`, from the `l1-lgbm-v1`
  temporal_test report), `b1_sanity_floor`/`b2_sanity_floor` (per-scorer Unavailable
  envelopes — `always_positive: null` now carries its "unreachable: constant scorer" reason),
  and `per_tier`.
- **Documented reading of the plan:** FIX-BE-03's implementation text says slice
  `[s for s in split.samples if s.episode_tier == tier or not s.is_attack]`, but its own
  regression test requires "per-tier confusion counts **sum exactly** to the overall counts".
  Those are mutually inconsistent (`or not is_attack` puts every legit sample in every tier
  slice, so fp/tn cannot sum). Resolved toward the test + the existing repo convention:
  slice by `stream_tier` (exactly what `evaluate().tier_breakdown` does — 821+701+603=2125),
  which makes tp/fp/tn/fn all sum to overall and keeps Block 6 tiering consistent with
  Block 1. Not a behavioural deviation, a disambiguation.

### FIX-BE-02 — Block 2 model + B0 rows (M-007, M-017)
- `eval/d6.py::_block2_negative_controls`: rewritten. Each scenario now carries **6 rows** —
  `l1-lgbm-v1`, `rules-only-v0` (scored on the negative-control samples with the SAME scorer
  instances `run_all` built, at `theta_challenge()`), then the 4 sanity scorers (bare names,
  unchanged, as the harness floor). Adds `episode_flagged: bool` (structurally-forced boolean
  re-type of `episodes`, §1(B)/M-017), `denominator_basis: "legitimate_attempts_only"`,
  `available`/`reason`. Model-less run → the two model rows emit as `available:false`
  Unavailable envelopes with a reason (never omitted, never zeroed).
- Regenerated: 7 scenarios × 6 rows = 42. Feasibility (§2.3) confirmed — no `KeyError` (all
  7 negative-control runs have feature-corpus rows). The model/B0 FP counts are real
  measurements (e.g. `l1-lgbm-v1` flags 376/500 legitimate CGNAT attempts at θ_challenge — an
  unflattering finding the block is meant to surface).

### Phase 1 regeneration (§28 step 13 — the single deliberate write)

| | SHA-256 |
|---|---|
| `eval/outputs/d6.json` **before** (v1) | `058f7e8ec3182a5414113e2c47d4b1df47f99e17eb02b3ef8f290850ad13f770` |
| `eval/outputs/d6.json` after 1st v2 regen | `66cf00562d92223681faa907ac8054c464d613e273fc6ef407413dee258536e7` |
| `eval/outputs/d6.json` **after** (v2, +evasive per_tier) | `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737` |
| `models/audit.json` before & after | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` (**unchanged**) |

A follow-up within Phase 1 added `block6_baselines.per_tier.evasive` (4th tier, from the
`tier_e` split — a homogeneous complete timeline, so B1 runs over all of it, no slice). The
diff vs the 1st v2 regen was `[added 32, removed 0, changed 0]` (only the new evasive
operating-point leaves). B1 per-tier counts sum exactly to overall:
`Σ(easy,med,hard) tp/fp/tn/fn = 103/1/757/1264` = overall.

**Full structural diff (committed v1 → regenerated v2), permitted-provenance ignored:**
`600 differences [added 528, removed 0, changed 72]`.
- **changed (72):** `schema_version 1→2` (1); Block-2 list **re-indexing** only (71) — the 4
  sanity scorers' FP counts are byte-preserved through the shift (verified pairwise:
  `cgnat[2]=perfect` new ↔ `cgnat[0]=perfect` old, both `attempt_fp:0`, etc.). **No
  evaluation value changed.**
- **added (528):** exclusively the intended additive v2 fields — `block2_theta_challenge`,
  Block-2 rows `[4][5]` × 7 scenarios, `ribbon_envelope`, `rupee_gap_is_structural` + note,
  `decision_region_fpr_max`, `optima_coincident`, `ece_raw`×2, `ece_gap`×2,
  `prior_correction_helped_at_pi1`, `block3_audit.{separability,direction,flagged_two_sided}`
  ×24 + `{univariate_auc_threshold, observed_max_univariate_auc}`,
  `block1_per_tier.*.*.{split,eval_prevalence}` ×8, `recall_at_target_fpr.{fpr_ci_low,
  fpr_ci_high,ci_basis}`, `block6_baselines.{model, per_tier, b1_sanity_floor,
  b2_sanity_floor}`, provenance additions.
- **removed (0).** Every v1 key survives — additive compatibility confirmed.

### Backend tests (§28 step 12) — §24.3 NEW / §24.4 extended

| File | Kind | Covers |
|---|---|---|
| `test_d6_schema.py` | NEW | `validate()` accepts committed; 10 malformed mutations each named; source SHA unchanged by the module |
| `test_d6_negative_controls_model_rows.py` | NEW | 42 rows (7×6); model/B0 first + available; identical denominators across all 6 rows per scenario; `episode_flagged` bool consistent with `episode_fp>0`; shared_ip_legit n=1, retry_storm n=5, flash_sale n=720 |
| `test_d6_block6_completeness.py` | NEW | model/b0/b1/b2 present; B3 floor with `unreachable` reason on `always_positive`; per_tier = {easy,evasive,hard,medium}×{model,b0,b1,b2}; per-tier tp/fp/tn/fn **sum to overall** for B1 and B2; row totals = tier n (821/701/603/390) |
| `test_d6_audit_derivations.py` | NEW | `separability == abs(auc-0.5)` ×24; `direction` inverted iff `{bin_hhi_5m, card_seen_24h}`; `observed_max = 0.9975874… ≠ 0.95`; boundary at exactly 0.95 flagged (`>=`); `_augment_audit_block` does not mutate input; `models/audit.json` SHA `ce75cb7f…` |
| `test_d6_provenance.py` | NEW | 5 header §9 attrs real; split reachable per block (easy→temporal_test, evasive→tier_e); `generated_at` ISO-8601 UTC; `corpus_db_sha256` == direct SHA of the corpus; `model_files_sha256[audit.json]` == on-disk SHA; `seeds_used=1` |
| `test_d6_cost_gap.py` | STRENGTHENED | `test_regime_switch_saving_is_non_negative` (`>=0`) → exact recompute: `stay 24855010.972933434 − best 1640502.7668777597 = 23214508.206055675`, `round(/100)=232145`; exact cost-optimal `(0.0, 0.46891002194586684, 27616.67885881492)`, F1-optimal `f1=0.6384462151394422`; all 20 curve costs recomputed; `optima_coincident`, `rupee_gap_is_structural`+note, `decision_region_fpr_max` contains both optima + next vertex, `ribbon_envelope` `hi>=lo` ∀i + monotone x (⇒ simple polygon) |
| `test_calibration.py` | EXTENDED | hand-computed `ece([.1,.3,.6,.9],…,n_bins=2) == 0.225`; `ece_raw` ∈ [0,1] both regimes; `ece_gap == ece_platt − ece_platt_prior`; verdict agrees with π1 comparison; **4 pre-existing calib numbers byte-identical** |
| `test_cost_thresholds.py` | EXTENDED | `theta_challenge() == 1800/(1800+5200)` exactly; `grep 0\.257` over `eval/**/*.py` finds nothing |
| `test_discriminability_audit.py` | EXTENDED | committed `separability`/`direction` agree with a fresh corpus AUC recompute |
| `test_d6_artifact.py` | EXTENDED | `schema_version == 2` + `in SUPPORTED`; delegates full leaf validation to `d6_schema.validate`; provenance v2 completeness + ISO-8601 |

**Full backend suite:** `python -m pytest tests/ -q` → **625 passed, 2 xfailed** (baseline
560 + 65 new; 2 xfailed are pre-existing). No regressions. `eval/metrics.py` and
`eval/cost.py` — `git diff --stat` empty (C1 preserved).

**Phase 1 CLOSED.** `eval/outputs/d6.json` @ `29edcb22…` is the frozen v2 artifact every
frontend test pins values against.

---

## PHASE 2 — Frontend foundations + JS test runner  ✅ FOUNDATION COMPLETE

### §23.4 — JS test infrastructure (NEW)
- `services/dashboard/package.json` — 6 `test*` scripts; devDeps added: `vitest@2.1.9`,
  `@vitest/coverage-v8`, `jsdom@25`, `@testing-library/{react@16.3,jest-dom@6.9,user-event}`,
  `vitest-axe@0.1` (axe-core 4.13), `@playwright/test@1.62`. `npm install` OK (172 pkgs). No
  runtime dependency added — shipped bundle unchanged.
- `services/dashboard/vitest.config.js` (NEW) — `mergeConfig(vite.config.js, …)` so the
  build-time `import ".../eval/outputs/d6.json"` resolves in tests identically to the app;
  `environment: jsdom`; coverage include globs + thresholds 85/85/80.
- `services/dashboard/src/test/setup.js` (NEW) — jest-dom + vitest-axe matchers,
  `afterEach(cleanup)`, `matchMedia` polyfill.
- `services/dashboard/playwright.config.js` (NEW) — 4 viewport projects (1536×960, 1280×800,
  768×1024, 390×844), `webServer` on `npm run dev`.

### FIX-FE-02 — `src/lib/format.js` (NEW) + `format.test.js`
One formatting policy: `inr` (en-IN, pinned, `inr(23214508.206055675) === "₹2,32,145"`),
`ap/auc/rate/prevalence/separability` 3dp, `ece/brier` 4dp, `fpr` 4dp or `x.xe-n` below 1e-3,
`count` grouped ≥10000, `pct` 1dp, `pi` verbatim. Every fn → `NA` for null/NaN/Infinity/string
(never a fabricated number). **9 tests pass**, incl. the mandatory headline.

### FIX-FE-01 — `src/lib/d6Contract.js` (NEW) + `d6Contract.test.js`
`parseArtifact(raw)` (schema_version ∈ {1,2}; 7 sections object-shaped; curves non-empty;
features non-empty) → typed `ArtifactContractError` with an actionable message, never a raw
TypeError. `normaliseMetric(node)` folds the rich recall object, the Unavailable envelope, a
bare number/null/undefined into one `{available, value, reason, detail}` shape.
**No `|| 0` / `?? 0` in the module (source-scanned).** **18 tests pass** — 9 missing-value
cases, both schema versions, malformed fixtures each named.

### §18.5 — fixtures (NEW): `src/__fixtures__/{realArtifact,mutate,malformed,synthetic}.js`
Real artifact re-exported unmodified; pure `deepClone/deepDelete/deepSet/leafPaths`;
7 malformed fixtures built in memory; synthetic branch fixtures (resolvable recall,
non-coincident optima, failed prior correction, boundary feature, config mismatch, π drift).
**No fixture edits `eval/outputs/d6.json`** (asserted by SHA in `test_d6_schema.py` too).

### FIX-FE-03 — `src/lib/d6FieldCoverage.js` (NEW) + `.test.js`
`FIELD_COVERAGE` declares all 214 leaf patterns as `RENDERED` / `RENDERED_IN_METHODOLOGY_PANEL`
/ `OMITTED(reason ≥ 20 chars)`. `checkCoverage(artifact)` walks the real artifact, collapses
dynamic segments, reports `unlisted` / `stale` / `badReason`. **5 tests pass** — zero unlisted,
zero stale, every OMITTED justified; adding/removing a leaf flips the result.

### FIX-FE-03 — `src/lib/metricsModel.js` (NEW) + `.test.js`
`buildMetricsModel({schemaVersion, artifact}, {currentConfigHash})` → the semantic view model
(provenance, freshness, block1–6, tierE, generated executive summary). Missing → `null`, never
`0`. **19 tests pass** — B0-beats-model on all 4 tiers, `|AUC-0.5|` sort (`card_seen_24h` above
`bin_entropy_5m`), 14/4/6 feature groups, unresolvable recall stays unavailable, ECE triple
both regimes, verdict flips on the failing-prior fixture, exec summary carries `₹2,32,145` /
`0.3955` / `0.2807`, freshness unknown/current/config-mismatch.

**JS suite so far:** `npx vitest run` → **51 passed** (4 files). Coverage thresholds not yet
meaningful (no components mounted yet).

---

## STATUS AT CHECKPOINT

**Complete and verified:**
- **Phase 0** — artifact-integrity hard gate PASSED (only `build_hash` differs; audit's J-class
  unknown closed).
- **Phase 1** — all backend work (FIX-BE-01..06), `schema_version 1→2`, the single deliberate
  artifact regeneration (`d6.json` `29edcb22…`), `models/audit.json` untouched, 4 calibration
  anchors + ₹ headline byte-identical. **`python -m pytest tests/ -q` → 625 passed, 2 xfailed**
  (baseline 560 + 65 new/extended backend tests). `eval/metrics.py` / `eval/cost.py` unchanged.
- **Phase 2 foundation** — JS test infra stood up; `format.js`, `d6Contract.js`,
  `d6FieldCoverage.js`, `metricsModel.js`, all 4 fixture modules, and their **51 passing tests**.

**Not yet done (frontend component + integration layers):**
- Phase 3 — rewrite the 6 block components + `BarRow`/`AuditBars`/`CostCurve`, add
  `components/metrics/*` (Block1PerTier, Block2NegativeControls, Block5Calibration,
  Block6Baselines, ProvenanceHeader, MethodologyPanel, UnavailableGroup, OperatingPointTable),
  `ReliabilityDiagram.jsx`, `costCurveGeometry.js`, and the ≥120 component-mounting rendering
  tests (FE-T-B1..B6, FE-T-PROV, FE-T-SUM, FE-T-ERR, FE-T-A11Y).
- Phase 4 — `useHashRoute.js`, `#/metrics` route, `<title>`, `aria-current`; `LiveShell.jsx`
  subscription isolation; `MetricsErrorBoundary.jsx`.
- Phase 5 — §20 hierarchy + exec-summary component, §21 token contrast fix + table/ARIA/SVG
  semantics + `vitest-axe` gate, §22 `metrics.css` responsive layer.
- Phase 6 — delete the obsolete grep tests once JS replacements are green (separate commit).
- Phase 7 — `e2e/metrics.spec.js` Playwright gates (18 checks × 4 viewports), §31 full
  verification procedure, `METRICS-AUDIT-VERIFICATION-2026-09-02.md` 40-finding matrix, the
  §31.11 reviewer test.

Stopped here at a clean, all-green checkpoint (no half-rewritten component, no failing test,
build intact) rather than rush the remaining frontend rewrite and its ~120 tests in a way that
would violate the brief's NO-CHEATING rule. Continuation starts at Phase 3 / §28 step 19 with
`D6Metrics.jsx` recomposed around `buildMetricsModel`.

---

## PHASE 3 — Block components (§28 steps 19-25)

### Slice 1 — error boundary + Block 1 (§28 step 18 tail + step 19)  ✅ green

**NEW**
- `src/components/MetricsErrorBoundary.jsx` (FIX-M-019) — class boundary, `getDerivedStateFromError`
  + `componentDidCatch` (ALWAYS `console.error`s the original); actionable fallback naming the
  cause + the regen command; DEV also renders the stack/path. Wired in `App.jsx` around
  `{route === "metrics" && ...}` only (routing itself is step 26).
- `src/components/metrics/UnavailableGroup.jsx` (FIX-M-015/028, §20.5) — the shared null-state
  primitive: one reason rendered once, N rows each `role="group"`, a dashed 1px rule (NOT a
  filled track), `n_neg` retained per row.
- `src/components/metrics/Block1PerTier.jsx` (FIX-M-001/002/015/016/028) — three sub-sections:
  1a recall@1e-3 via `UnavailableGroup` (8 rows, model+B0, grouped reason, per-row `n_neg`,
  no number rendered); 1b `ap_at_eval_prevalence` paired model/B0 bars, π_eval=0.01 reference
  marker, heading carries "comparable" + "π_eval = 0.01"; 1c `ap_raw` paired bars, each tier's
  own `prevalence` marker, row text `0.789 · prevalence 0.731 · n=821`, heading "not
  cross-tier". Verdict prose above (from the view model), not collapsed. Evasive row labelled
  `tier_e — adversarial split`; bar fill token identical to the other three (UIUX §6.13). B0
  hatched fill, SAME hue.
- Tests: `MetricsErrorBoundary.test.jsx` (7 — FE-T-ERR subset: 4 boundary fixtures named,
  `console.error` called, shell survives, no bare-zero leaf), `Block1PerTier.test.jsx` (17 —
  exact `ap` strings for model+B0 in 1b/1c, prevalence adjacency, reference-marker `left`
  geometry, 1a renders no number, 8 rows each with `n_neg`, grouped reason once, A7 no-bare-zero
  accessible names, evasive split label + identical fill, verdict names B0 stronger + ROC-AUC
  `0.889 vs 0.994`), `UnavailableGroup.test.jsx` (3), `D6Metrics.test.jsx` (7 — six blocks in
  argument order, Eval §9 identity line, FE-T-SUM exec summary carries `₹2,32,145` / `0.3955` /
  `0.2807` / B0-beats-model above block 1, no NaN/bare-zero, graceful degrade on
  missingCalibration + explicitNulls).

**MODIFIED**
- `src/screens/D6Metrics.jsx` — full rewrite as a composition over
  `buildMetricsModel(parseArtifact(artifact))` run INSIDE render (`useMemo`) so a malformed
  artifact throws an `ArtifactContractError` the boundary catches. Optional `artifact` /
  `currentConfigHash` props for testing (default: the committed `import d6`). Page header +
  Eval §9 identity line + generated executive summary + Block 1 (real component) + interim
  model-driven sections for blocks 2-6 + tier-E footer. Interim sections read `model.blockN`
  only — no raw field picking, no fabricated 0. The `import d6 from ".../d6.json"` name is
  kept (KEPT invariant test `test_d6_static.py::test_d6metrics_reaches_the_artifact_by_static_import`).
  A comment enumerates the six block keys so `test_all_six_blocks_are_referenced` stays green
  until its step-31 deletion.
- `src/App.jsx` — `import MetricsErrorBoundary`; wrap `<D6Metrics/>` on the metrics route.
- `src/lib/metricsModel.js` — block5 `verdict` copy: removed the rendered "Eval Protocol §3.4"
  string (M-032 — no internal spec IDs in rendered output; the §3.4 citation moved to a code
  comment). Values / "lower is better" / "broken" unchanged; `metricsModel.test.js` green.
  **Documented deviation vs FIX-M-010 §15 sample copy**, resolved toward the §30 F-gate.

**Deviations recorded (artifact vs stale plan prose):**
- B0 hard `ap_raw` renders **`0.981`** (`0.9814576232319572`.toFixed(3)); plan §11/§29 prose
  says `0.982`. The verified artifact value wins (§23.5/§23.7).
- π_eval renders **`0.01`** via `format.pi` (verbatim, drift-safe — the M-021 design); plan
  §23.6/§29 prose says `0.010`. AC §11.3 ("π_eval = 0.01 renders") is met.

**Tests:** `npx vitest run` → **85 passed** (51 foundation + 34 new). Backend D6/eval
acceptance (`test_d6_*`, `test_calibration`, `test_cost_thresholds`, `test_discriminability_audit`)
→ **91 passed**, unchanged. `eval/metrics.py` / `eval/cost.py` / `eval/audit.py` /
`eval/baselines.py` / `eval/provenance.py` — `git diff --stat` empty. `eval/outputs/d6.json`
untouched.

**Transient reds (expected, planned for step 31):**
`test_ui_contracts.py::TestD6Resolvability::test_d6_passes_metric_objects_not_bare_values` and
`::test_a_resolvable_alternative_is_shown` — grep `D6Metrics.jsx` for `recall_at_target_fpr` /
`metric={` / `ap_raw`, now moved into `metricsModel.js` + `Block1PerTier.jsx`. The whole
`TestD6Resolvability` class is on the §26.2 / Appendix-A deletion list, removed in the Phase 6
step-31 commit once every JS block suite is green. Its invariant is now covered by
`FE-T-B1` ("no recall renders as a number") + `FE-T-CONTRACT-01`. The other two tests in that
class (reading `BarRow.jsx`, untouched) still pass.

### Slice 2 — Block 4 cost curves (§28 step 20)  ✅ green

**NEW**
- `src/components/charts/costCurveGeometry.js` (FIX-M-003/004/005/034) — PURE, no DOM:
  `linScale` (with a low-end pixel `inset`), `logScale` + `decadeTicks` + `niceLogTicks`
  (1-2-5 mantissa, so Panel A's narrow window still gets gridlines), `buildPanelGeometry`,
  `costDomain` (log-space padded), `ribbonEnvelope` (accepts the pre-computed `[[fpr,lo,hi]]`
  OR the raw `[{pi,curve}]` and computes per-index min/max — a crossing-curve input still
  yields hi≥lo by construction), `ribbonPath`, `segmentsIntersect` + `properSegmentsCross` +
  `pathHasSelfIntersection` (transversal crossings only — collinear boundary edges from the
  two FPR=0 hull vertices are a valid fill, not a bowtie), `markerLayout` (merges coincident
  markers, stacks callout boxes so they never overlap), `boxesOverlap`.
- `src/components/metrics/OperatingPointTable.jsx` (§14.2/§21.2) — the chart's accessible
  data alternative: `<caption>` + `<th scope>`, exact FPR/TPR/cost per operating point
  (`0.0000` / `0.469` / `₹276` for the coincident π₀ optimum; `₹16,405` for the π₁ optimum).
- Tests: `costCurveGeometry.test.js` (11 — FE-T-GEOM-01..10: envelope hi≥lo + monotone x from
  both input forms, ribbon polygon simple, bowtie detected, Panel A min-to-max ≥ 40px, FPR=0
  maps `xInset`=8px clear of the axis, ≥1 log gridline in the narrow window, markerLayout
  merge/stack/no-overlap), `CostCurve.test.jsx` (15 — FE-T-B4: series/tier/split subtitle,
  `₹2,32,145` headline, `₹0` gap never without "structural" + the substantiating note, 3
  panels each `role="img"` with `<title>`+`<desc>`, Panel B/C draw the full 10-vertex curve,
  ONE marker when coincident / TWO under `withNonCoincidentOptima`, marker cx ≥ 6px from the
  y-axis, Panel A curve+ribbon vertical extent ≥ 40px, no rotated `<text>`, every `<text>`
  ≥ 11px inside the viewBox, Panel A/B ribbons simple, Panel C carries NO ribbon,
  operating-point row exact, `withDifferentPi` moves every π label).

**MODIFIED**
- `src/components/charts/CostCurve.jsx` — full rewrite: 3 stacked `<svg>` panels
  (A decision-region π₀ + ribbon, B full-range π₀ + ribbon + shaded Panel-A window,
  C full-range π₁, own log scale, NO ribbon) + `<OperatingPointTable>`. Log y disclosed in
  every axis label; y-axis label HORIZONTAL above the axis (M-034); inset filled-circle
  markers with collision-avoided callouts (M-004); one-vs-two markers driven by
  `block4.optimaCoincident` from the backend (M-004); π labels from `block4.pi0/pi1` (M-021);
  every rupee via `format.inr` (M-014); `series/tier/split` subtitle (M-037); the ₹0 gap
  stated as structural with `rupeeGapNote` (M-039). Consumes the view model
  (`curvePi0`, `ribbonEnvelope`, ...) — no raw artifact keys.
- `src/screens/D6Metrics.jsx` — `InterimBlock4` removed; `<CostCurve block4={model.block4} />`
  wired into Section 4. Unused `inr` import dropped.
- `src/screens/D6Metrics.test.jsx` — the "no bare-zero leaf" checks narrowed: exclude SVG
  internals (a chart axis origin legitimately labelled `0`) and match only a *bare* `0`/`NaN`
  leaf, not `0.000`/`0.0000` which are real measured values (D4's "no 0.000 in the Metrics
  region" is scoped to null fixtures, §30). `explicitNulls` now pins `easy: 1.000 vs n/a` in
  the generated summary.

**Tests:** `npx vitest run` → **111 passed** (85 + 26 new). `test_d6_cost_gap.py` /
`test_d6_artifact.py` → 24 passed, unchanged. `eval/{metrics,cost,audit,baselines,provenance}.py`
`git diff --stat` empty. `eval/outputs/d6.json` SHA `29edcb22…` and `models/audit.json` SHA
`ce75cb7f…` **unchanged** — verified.

**Transient red (expected, planned for step 31):**
`test_d6_static.py::test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap` — greps
`CostCurve.jsx` for `curve_pi0` / `cost_optimal` / `ribbon` / `rupee_gap_minor` (raw artifact
keys), now consumed via the view model. On the §26.2 / Appendix-A DELETE list; its intent is
carried by the 15 `FE-T-B4-*` + 11 `FE-T-GEOM-*` tests. Deleted in the Phase 6 step-31 commit.
`test_d6_static.py::test_no_runtime_data_path_*` and `test_all_six_blocks_are_referenced`
remain green.

### Slice 3 — Block 3 discriminability audit (§28 step 21)  ✅ green

**MODIFIED**
- `src/components/charts/AuditBars.jsx` — full rewrite (FIX-M-013/006/025). Consumes the
  `block3` view model. Three groups in order: **Flagged (6)** amber bars + ONE group header
  + each feature's own `reason` (no 6× repeated `FLAGGED — GENERATOR ARTIFACT` label);
  **Measured (4)** grey bars; **Not fed (14)** collapsed behind an `aria-expanded` `<button>`
  disclosure → `UnavailableGroup` (no bars, one shared reason, per-feature reason as row text).
  Bar length = `separability` (0→0.5), NOT raw AUC — an inverted feature gets a long bar;
  direction is a separate `↓ inverted` glyph with the raw AUC always printed. Threshold rule
  at `(threshold − 0.5)/0.5` from `univariate_auc_threshold` — **no `0.95` literal in the
  component** (M-012). `statistic` / `training_set` dropped from the caption (they are
  `RENDERED_IN_METHODOLOGY_PANEL` per the coverage map). Feature names in `tg-mono-caption`
  (lowercase, as identifiers — M-033), `overflow-wrap: anywhere` + `word-break` + `title`
  (M-025; full geometry is Playwright's).
- `src/screens/D6Metrics.jsx` — `InterimBlock3` removed; `<AuditBars block3={model.block3} />`
  wired into Section 3.
- Tests: `AuditBars.test.jsx` (10 — FE-T-B3: 6/4/14 group counts, disclosure toggles to 14
  `role="group"` rows, `card_seen_24h` sorts above `bin_entropy_5m` + renders `AUC 0.225` +
  `inverted`, bar length = separability (`bin_hhi_5m` AUC 0.289 → >40% wide), 6 amber / 4 grey
  / 0 not-fed bars, `0.500` appears nowhere collapsed or expanded, A7 not-fed accessible names
  never a bare zero, threshold marker at 90% and MOVES to 80% with a `univariate_auc_threshold:
  0.90` fixture, no `0.95` literal in source, no component-authored spec-ID copy, 6 distinct
  per-feature reasons rendered).

**Tests:** `npx vitest run` → **121 passed** (111 + 10). `test_discriminability_audit.py`,
`test_d6_audit_derivations.py` → pass, unchanged. `eval/{metrics,cost,audit,baselines,
provenance}.py` diff empty. `eval/outputs/d6.json` / `models/audit.json` SHAs unchanged.

**Transient reds unchanged from Slice 2:** the same two grep tests
(`TestD6Resolvability::{test_d6_passes_metric_objects_not_bare_values, test_a_resolvable_
alternative_is_shown}`, `test_d6_static.py::test_cost_curve_renders_both_regimes_both_optima_
ribbon_and_gap`) — all on the step-31 DELETE list, all covered by green JS suites.

**Note:** `AuditBars.jsx` renders the artifact's own `feature.reason` strings verbatim
(FIX-M-006 requires it); several cite `Eval Protocol §4/V2`. M-032 bans component-AUTHORED
spec-ID copy, not faithfully rendered data — the M-032 test scans the comment-stripped
component source, not the rendered DOM. Recorded for the §31.10 audit re-run.

### Slice 4 — Block 5 calibration (§28 step 22)  ✅ green

**NEW**
- `src/components/charts/ReliabilityDiagram.jsx` (FIX-M-010 5c) — inline SVG scatter of
  (mean_predicted, observed_rate) vs the y=x diagonal; point AREA ∝ bin weight
  (`r = R_MIN + (R_MAX−R_MIN)·√(w/wMax)`); empty bins omitted and their count stated;
  `<title>`+`<desc>`; labels ≥ 11px.
- `src/components/metrics/Block5Calibration.jsx` (FIX-M-010 / M-036 / M-021 / M-022) — three
  parts: **5a** the verdict first (from the view model, M-032-clean, "lower is better" stated
  once); **5b** the 2×6 grid Brier{raw,Platt,Platt+prior} + ECE{raw,Platt,Platt+prior} per
  regime + `effective_n` (759.5 / 1650.9) + `n` + `raw_prevalence`, best-in-family bolded,
  an inline MAGNITUDE bar per cell so `0.3955` and `0.0007` are not typographically identical
  (M-036); **5c** both reliability diagrams side by side. Regime labels from `block4.pi0/pi1`
  via the view model (M-021).
- Tests: `Block5Calibration.test.jsx` (11 — FE-T-B5: exact π₀ row `0.1193/0.0108/0.0007/
  0.2620/0.0703` + `759.5`, exact π₁ row `0.1403/0.3413/0.2020/0.2089/0.3955/0.2807` +
  `1650.9`, `n = 2125` + `raw prevalence 0.643`, verdict has `0.3955`/`0.2807`/`reduces`/
  `lower is better`, `withPriorCorrectionFailed` flips to `broken` and drops `reduces`,
  magnitude bar for `0.3955` wider than `0.0007`, 5 / 6 non-empty bins + `5 / 4 empty bins
  omitted`, point radius monotone in weight, `<title>`+`<desc>` per diagram, `withDifferentPi`
  moves the regime + diagram labels, `available:false` → "not measured").

**MODIFIED**
- `src/screens/D6Metrics.jsx` — `InterimBlock5` removed; `<Block5Calibration>` wired into
  Section 5. Unused `brier` / `ece` format imports dropped.

**Deviation (artifact vs stale plan prose):** the π₀ reliability diagram plots **5** non-empty
bins (weights 2124.04 / 0.0047 / 0.0016 / 0.5923 / 0.3638), π₁ plots **6**; plan §15/§23.6
prose says "4 points at π₀". The verified artifact's bin weights are the source of truth
(§23.5). `emptyBins` = 5 / 4.

**Tests:** `npx vitest run` → **132 passed** (121 + 11). `test_calibration.py` → 8 passed,
unchanged. `eval/{metrics,cost,audit,baselines,provenance}.py` diff empty. `eval/outputs/d6.json`
/ `models/audit.json` SHAs unchanged.

### Slice 5 — Block 6 baseline comparison (§28 step 23)  ✅ green

**NEW**
- `src/components/metrics/Block6Baselines.jsx` (FIX-M-008 / M-038 / M-026) — a comparison
  matrix with a subject. **Overall** table: model row (AP `0.945`, ROC-AUC `0.889`), B0 row
  (`0.997` / `0.994`), B1/B2 rows with a two-line TPR-at-own-op-point cell (`0.075` fpr 0.0013
  prec 0.990 / `0.718` fpr 0.0000 prec 1.000); model + B0 recall @ 1e-3 render
  `not resolvable · n_neg=758`, never a number. **B3 sanity floor**: perfect/random/inverted
  numeric, `always_positive` renders its "unreachable — a constant scorer has no intermediate
  operating point" reason, no number (M-038). **Per-tier** table: 4 tiers × {model, b0, b1, b2}
  = 16 TPR cells. B1 (bitemporal) and B2 (names B0, states non-independence — Eval §8) caveats
  preserved verbatim. Fixed row height (M-026 structural; real uniform-height check is
  Playwright E2E #15).
- Tests: `Block6Baselines.test.jsx` (9 — FE-T-B6: model row AP `0.945` / ROC-AUC `0.889`,
  B0 `0.997`/`0.994`, B1 TPR `0.075`, B2 TPR `0.718`, model+B0 recall `not resolvable ·
  n_neg=758` with no number, fixed row height, `always_positive` unreachable-reason + no
  number for both B1/B2 floors, perfect/random/inverted numeric, per-tier 4×4 = 16 cells with
  spot values, B2 caveat names B0 + non-independence, B1 bitemporal caveat present).

**MODIFIED**
- `src/screens/D6Metrics.jsx` — `InterimBlock6` removed; `<Block6Baselines>` wired into
  Section 6. Format imports trimmed to `count` + `pi` (all other blocks are now dedicated
  components). `src/screens/D6Metrics.test.jsx` — the broad `NaN`/`undefined` textContent
  scan narrowed to `NaN` only (the B3 floor reason string legitimately contains the word
  "undefined"); the bare-leaf regex now `/^(0|NaN|undefined)$/`.

**Tests:** `npx vitest run` → **141 passed** (132 + 9). `test_d6_block6_completeness.py`,
`test_baselines_single_source.py` → pass, unchanged. `eval/{metrics,cost,audit,baselines,
provenance}.py` diff empty. `eval/outputs/d6.json` / `models/audit.json` SHAs unchanged.

At this point Blocks 1, 3, 4, 5, 6 render from dedicated components; only Block 2 (interim)
and the Provenance header / Methodology panel remain in Phase 3.

### Slice 6 — Block 2 negative controls (§28 step 24)  ✅ green

**NEW**
- `src/components/metrics/Block2NegativeControls.jsx` (FIX-M-007-FE / M-017 / M-024) — one
  semantic `<table>` with a `<caption>` (accessible name), 7 `<tbody>`s, real `<th scope="row"
  rowSpan={6}>` per scenario (no empty `<td>` grouping cell). 6 rows/scenario: `l1-lgbm-v1`,
  `rules-only-v0` first (product), then the 4 sanity scorers (harness floor, muted).
  Episode-flagged is `yes`/`no` — the string `0/1` appears nowhere (M-017). Attempt FP over
  legitimate attempts only: n ≥ 30 → `<count> FP · <pct>` + a Wilson 95% CI + `n = 720`;
  n < 30 → `0 of 1` + a `single sample — n=1` / `underpowered — n=5` badge, no percentage.
  `shared_ip_legit` carries the F14 one-line note ("one legitimate attempt; 60 of 61 samples
  are the attacker's").
- Tests: `Block2NegativeControls.test.jsx` (8 — FE-T-B2: every scenario has l1-lgbm-v1 +
  rules-only-v0 first, 4 sanity scorers retained, `yes`/`no` and no `\d/1` fraction,
  `shared_ip_legit` → `0 of 1` + `single sample`, `flash_sale` → `n = 720` + `95% CI [`,
  `retry_storm` → `underpowered — n=5`, table has an accessible name + 7 `rowspan="6"` cells
  + zero empty grouping cells, θ_challenge `0.257143` from the artifact).

**MODIFIED**
- `src/screens/D6Metrics.jsx` — `InterimBlock2` removed; `<Block2NegativeControls>` wired into
  Section 2. All six blocks now render from dedicated components; the only remaining interim
  code is the `IdentityLine` + `ExecutiveSummary` (replaced by `ProvenanceHeader` /
  `MethodologyPanel` in step 25).

**Tests:** `npx vitest run` → **149 passed** (141 + 8). `test_negative_controls_evaluated.py`,
`test_d6_negative_controls_model_rows.py` → pass, unchanged. `eval/{metrics,cost,audit,
baselines,provenance}.py` diff empty. `eval/outputs/d6.json` / `models/audit.json` SHAs
unchanged.

### Slice 7 — Provenance header + Methodology panel (§28 step 25)  ✅ green — PHASE 3 COMPLETE

**NEW**
- `src/components/metrics/ProvenanceHeader.jsx` (FIX-M-029 / M-009 / M-022) — the six Eval §9
  attributes (seed, config_hash, model_version, policy_version, π_eval, split) + `seeds_used`,
  all without interaction; a human `generated_at` (`2026-09-02 17:03 UTC`); the single-seed
  disclosure. Freshness: three states — `config-mismatch` → a `role="alert"` warning with both
  hash prefixes; `current` → neutral "configs unchanged since"; `unknown` → "freshness not
  verifiable in this build" (never the word "current"). `build_hash` divergence alone is NOT
  staleness (§17.2 deviation).
- `src/components/metrics/MethodologyPanel.jsx` (§20.3) — collapsed-by-default `<button
  aria-expanded>` disclosure holding `build_hash`, `head_at_generation`,
  `tree_dirty_at_generation`, `fixture_sha256`, `corpus_db_sha256`, `model_files_sha256[*]`,
  `calibrator_version`, `generation_command`, seed/base_seed/seeds_used, the audit `statistic`
  + `training_set`, `n_bins` / `pi_t` / `raw_prevalence`, the tier_e converged params
  (`distinct_cards` 286, `episode_duration_s` 704, `amount_quantile_band [0, 26]`), and the
  split-composition table. The G-class omissions (`fixture_sha256`, `calibrator_version`) are
  now addressable.
- Tests: `ProvenanceHeader.test.jsx` (5 — FE-T-PROV: six §9 attrs + `seeds_used`,
  `generated 2026-09-02 17:03 UTC`, config-mismatch → alert with both hashes, matching → no
  alert + "configs unchanged", unknown → "not verifiable" + no "current"),
  `MethodologyPanel.test.jsx` (2 — collapsed by default; on expand the G-class + identity +
  methodology + split-composition values are all present).

**MODIFIED**
- `src/vite.config.js` — NEW `define: { __TG_CONFIG_HASH__ }`, computed at config-load time by
  `execFileSync("python", ["-c", "from eval.provenance import config_hash; print(config_hash())"])`
  (cwd `../..`), try/catch → `null`. The single source of truth is the authoritative
  `config_hash()` — no JS reimplementation. `null` in a bare build → the "unknown" freshness
  state.
- `src/screens/D6Metrics.jsx` — `IdentityLine` (inline) → `<ProvenanceHeader>`;
  `<MethodologyPanel>` added after the tier-E footer; `currentConfigHash` defaults to
  `__TG_CONFIG_HASH__` (guarded with `typeof`). Module doc comment updated — every block is
  now a dedicated component.
- `src/vitest.config.js` — coverage `include` gains `LiveShell.jsx` (slice 8); `exclude` for
  `labels.js` / `featureLabels.js` (D1/D3) and `BarRow.jsx` (superseded — the block components
  have their own row renderers; §26.3 deviation, `BarRow.jsx` kept until its `TestD6Resolvability`
  grep tests are deleted in step 31).

**Tests:** `npx vitest run` → **156 passed** (149 + 7). `npx vitest run --coverage` → exit 0,
**98.88% lines / 97.7% functions / 87.28% branches** (D6 source files 95–100%). `test_d6_provenance.py`
→ pass, unchanged. `eval/{metrics,cost,audit,baselines,provenance}.py` diff empty.
`eval/outputs/d6.json` / `models/audit.json` SHAs unchanged.

**PHASE 3 (§28 steps 19–25) COMPLETE.** All six blocks + the provenance header + methodology
panel + the generated executive summary render from dedicated, individually-tested components
off `buildMetricsModel`. Remaining transient reds (step-31 deletion list): `TestD6Resolvability`
×2, `test_d6_static.py::test_cost_curve_renders_...` — all covered by green JS suites.

---

## PHASE 4 — Page architecture (§28 steps 26–27)

### Slice 8 — routing + live-subscription isolation  ✅ green

**NEW**
- `src/hooks/useHashRoute.js` (FIX-M-018) — `ROUTES = ["live","incident","metrics"]`,
  `routeFromHash` (unknown hash → `"live"`, never throws), `ROUTE_TITLES` drives
  `document.title` via effect, `navigate(id)` sets `window.location.hash = "/"+id` **and**
  dispatches a `hashchange` Event (jsdom does not fire it on programmatic hash writes).
- `src/hooks/useReplayStatus.js`, `src/hooks/useIncidents.js` — extracted from the old
  monolithic `App.jsx` verbatim (no logic change) so `LiveShell` owns them.
- `src/components/LiveShell.jsx` (FIX-M-031) — holds `useReplayStatus` / `useEventStream` /
  `useIncidents`, the SSE status span, StreamRail + ThreatBand + SystemBanner, the `<main>`
  with D1Live / D3Incident, and the DemoControlStrip. `WINDOW_MS = 60_000`; the
  `shedInLast60` / `failOpenAgoS` `useMemo` blocks moved over unchanged. Mounted ONLY for
  `live` / `incident` — on `#/metrics` it never renders, so **zero EventSource constructions
  and zero poll timers** on the evaluation page.
- Tests: `useHashRoute.test.js` (5 — hash parse, unknown → live, title follows route,
  `navigate` updates + fires hashchange, back/forward via `hashchange`),
  `LiveShell.test.jsx` (4 — `FE-T-ROUTE`: `#/metrics` renders D6 on first paint with
  `aria-current="page"` on the Metrics nav; `FE-T-ARCH`: 0 EventSource on `#/metrics`, DC
  strip absent on Metrics / present on Live, `live→metrics` unmounts LiveShell and calls
  `EventSource.close()`).

**MODIFIED**
- `src/App.jsx` — rewritten as the D0 shell: `const [route, navigate] = useHashRoute()`; nav
  `<button onClick={() => navigate(n.id)} aria-current=…>`; `known === "metrics"` →
  `<StreamRail events={[]} />` + `<MetricsErrorBoundary><D6Metrics /></MetricsErrorBoundary>`;
  else `<LiveShell route={known} />`. Net −56 lines vs the pre-Phase-4 `App.jsx`.
- `tests/acceptance/test_ui_contracts.py` — `TestReplayStatusIsAuthoritative::…` and
  `TestIncidentsComeFromTheApi::…` retargeted from `App.jsx` to `components/LiveShell.jsx`
  (the asserted code moved there verbatim; the invariant is preserved — not a weakening).
  Comment cites `FIX-M-031`.
- `src/test/setup.js` — added a jsdom `HTMLCanvasElement.prototype.getContext` no-op stub
  (StreamRail paints a canvas; jsdom has none) guarded by `__tgStubbed`.
- `src/App.jsx` (Slice 9 addendum) — the `#/metrics` branch's `<D6Metrics>` is now wrapped in
  `<main style={{ flex: 1 }}>`, mirroring `LiveShell.jsx:81`, so the evaluation page has a
  `main` landmark (§21.2). Verified by `D6Metrics.a11y.test.jsx` ("single `<main>`").

**D1 / D3 behavioural gates (§26.4):** `python -m pytest tests/acceptance/test_sse.py
tests/acceptance/test_demo_lifecycle.py tests/acceptance/test_incident_api.py -q` →
**19 passed, exit 0**. The App/LiveShell refactor did not disturb the live path.

**Tests:** `npx vitest run` → **165 passed**. `eval/{metrics,cost,audit,baselines,provenance}.py`
diff empty. `eval/outputs/d6.json` / `models/audit.json` SHAs unchanged.

**PHASE 4 (§28 steps 26–27) COMPLETE.**

---

## PHASE 5 — Presentation (§28 steps 28–30)

### Slice 9 — a11y contrast + semantics + responsive scaffold  ✅ green

**NEW**
- `src/styles/contrast.test.js` (FIX-M-023, `FE-T-A11Y-01..04`) — parses the hex tokens
  straight out of `tokens.css` and recomputes the WCAG 2.1 relative-luminance contrast ratio.
  Asserts every (foreground-text token, background token) pair the page paints
  (`--tg-text` / `--tg-text-2` / `--tg-text-mute` / `--viz-flag` × `--tg-canvas` /
  `--tg-surface-1` / `--tg-surface-2`) is **≥ 4.5:1**. Calibration cases reproduce the
  audit's own measurements exactly (`#6E7885` on canvas = **4.34**, `--tg-text-2` = **8.88**).
  Computed ratios for the new `--tg-text-mute` `#8B95A3`: **6.42 / 5.99 / 5.52** (was
  4.34 / 4.05 / 3.74). Hierarchy `L(text) > L(text-2) > L(text-mute)` asserted.
- `src/screens/D6Metrics.a11y.test.jsx` (FIX-M-024, `FE-T-A11Y-05..12`) — `vitest-axe` over
  the full `.tg-app > main > D6Metrics` render: **zero violations**, happy path AND a
  drifted-π artifact. `color-contrast` disabled (jsdom does not lay out / `css:false`; that
  split is contrast.test.js + Playwright E2E #17). Plus: every `<table>` has an accessible
  name; every `svg[role=img]` has a `<title>`; one `<main>`; **no UnavailableGroup row's
  `aria-label` matches `/\b0(\.0+)?\b/`** and each reads "not resolvable / n_neg=". 30 s
  per-test timeout — axe full-page under jsdom is ~4–12 s and single-flight.
- `src/screens/D6Metrics.copy.test.jsx` (§20.4, M-032 / M-033) — comment-stripped source
  scan of all 13 composed components for component-AUTHORED spec-ID copy
  (`/UIUX v2|SS\d|App Flow §|Eval Protocol §|Backend Schema §|Decisions\.md|§\s?\d/`) — all
  clean (the two `Eval Protocol §` hits are in code comments, which M-032 permits). M-033:
  `l1-lgbm-v1` / `rules-only-v0` render as literal lowercase, never inside a `.tg-label`
  (the only `text-transform: uppercase` class).
- `src/components/metrics/ScrollableTableRegion.jsx` (§22.2, M-027) — the shared table-scroll
  primitive: `<div className="tg-scroll-x" role="region" tabIndex={0} aria-label={label}>`.

**MODIFIED**
- `src/styles/tokens.css` — `--tg-text-mute` `#6E7885` → `#8B95A3` (M-023). Comment cites
  §21.1. `--tg-calm` (a threat-state token that happens to share the old hex) **not** changed.
- `src/styles/metrics.css` — `.tg-metrics` 1280 px centred container; `.tg-scroll-x`
  (`overflow-x:auto` + `:focus-visible` ring); `.tg-mono-caption` / `code` `overflow-wrap`.
  The `.tg-metric-row` `@media` stack (768 / 480) now carries `grid-template-areas` and a
  comment: the class is **opt-in, adopted by the row components in Phase 7** once the
  Playwright viewport gates (§22.3) confirm the stacked geometry — the Phase-3 block
  components already ship fluid `minmax(_, 1fr)` inline grids (the "key inversion"), and
  jsdom cannot verify layout.
- `src/main.jsx` — `import "./styles/metrics.css";` after `base.css`.
- Tables wrapped in `<ScrollableTableRegion label=…>` (distinct label each, §22.2 / M-024):
  `Block2NegativeControls.jsx` (the 42-row widest), `Block5Calibration.jsx` (2×6 grid),
  `Block6Baselines.jsx` (×2 — overall + per-tier), `OperatingPointTable.jsx`. Captions,
  `<th scope>`, rowspans and every rendered value are untouched — the per-block FE-T-B*
  suites stay green.
- `.gitignore` — `*.timestamp-*.mjs` (Vite's transient ESM config shim; one such file was
  left untracked in `services/dashboard/` and has been removed).

**Deviation (recorded):** §22.2's `.tg-metric-row` single-grid model is not retrofitted onto
Block1PerTier / AuditBars / UnavailableGroup in this slice — they diverged in Phase 3
(Block1 has a 4-col row with a reference-marker column; AuditBars a wider name column;
§26.3 deviation already on file). Their inline grids are already fluid; the breakpoint STACK
is wired and tuned against real layout in Phase 7 step 32 (§22.3), not guessed at here.

**Tests:** `npx vitest run` → **205 passed / 21 files** (165 + 19 contrast + 6 a11y + 15
copy). `python -m pytest tests/acceptance/test_d6_static.py tests/acceptance/test_ui_contracts.py`
→ **3 failed** (the same step-31 deletion-list grep tests, unchanged), 50 passed.
`eval/{metrics,cost,audit,baselines,provenance}.py` diff empty. `eval/outputs/d6.json` SHA
`29edcb22…` / `models/audit.json` SHA `ce75cb7f…` — **unchanged**.

**Full backend suite** (re-run this session): `python -m pytest tests/ -q` → **620 passed,
2 skipped, 2 xfailed, 3 failed** in 412 s. The 2 skipped are Redis-availability skips
(`pytest.skip("Redis unreachable")`, environment — Redis not up), unrelated to the
remediation. The 3 failed are the known transient reds. 2 xfailed are pre-existing.

**PHASE 5 (§28 steps 28–30) COMPLETE** except the `.tg-metric-row` stack adoption, which is
a Phase 7 §22.3 layout-verification task (recorded above). Steps 28 (hierarchy + exec
summary + M-032/033/036) / 29 (contrast + ARIA + SVG title/desc) / 30 (metrics.css +
overflow regions + 1280 container) all have test evidence.

---

## PHASE 6 — Test migration (§28 step 31)

### Slice 10 — delete the superseded grep tests  ✅ green  (NOT committed — user review pending)

Per §26.2, each Python source-grep test is deleted only after its real-rendering JS
replacement is green (all were, by end of Phase 5).

**DELETED**
- `tests/acceptance/test_d6_static.py::TestD6Static::test_all_six_blocks_are_referenced`
  — grepped `D6Metrics.jsx` for the six `block*` keys. Replaced by
  `screens/D6Metrics.test.jsx` ("renders the six blocks in argument order" — real `<h2>`
  DOM assertions) + `lib/d6FieldCoverage.test.js` (every artifact leaf RENDERED / MP /
  OMITTED, walked against the real artifact).
- `tests/acceptance/test_d6_static.py::TestD6Static::test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap`
  — grepped `CostCurve.jsx` for raw artifact keys (`curve_pi0`, `cost_optimal`, `ribbon`,
  `rupee_gap_minor`). Replaced by `charts/CostCurve.test.jsx` (15 `FE-T-B4-*`) +
  `charts/costCurveGeometry.test.js` (11 `FE-T-GEOM-*`).
- `tests/acceptance/test_ui_contracts.py::TestD6Resolvability` — **whole class, 4 tests**
  (`test_barrow_reads_resolvable`, `test_d6_passes_metric_objects_not_bare_values`,
  `test_no_unresolvable_entry_can_reach_a_tofixed_path`, `test_a_resolvable_alternative_is_shown`).
  Grepped `D6Metrics.jsx` / `BarRow.jsx` (the superseded shared-bar primitive, §26.3) for
  the strings proving an unresolvable metric never reaches `.toFixed()`. Replaced by
  `metrics/UnavailableGroup.test.jsx`, `metrics/Block1PerTier.test.jsx` (`FE-T-B1` "no
  recall renders as a number"; 1c renders `ap_raw` as the resolvable alternative),
  `lib/d6Contract.test.js` (`FE-T-CONTRACT` — 9 missing-value cases → `available === false`,
  never a number). A migration-pointer comment replaces the class in-file.

**MODIFIED**
- `tests/acceptance/test_d6_static.py` — module docstring rewritten to
  "**architectural invariants only**". The two KEPT tests are verbatim:
  `test_d6metrics_reaches_the_artifact_by_static_import` (static `import`, not fetch) and
  `test_no_runtime_data_path_in_d6_or_its_charts` (no `fetch(` / `EventSource` /
  `XMLHttpRequest` in `D6Metrics.jsx` or `components/charts/*`).

**`BarRow.jsx` note:** still on disk (nothing imports it — verified `grep -rn BarRow src/`).
Its last referencing tests are now gone; it can be deleted outright, but that is a
frontend-source deletion, not a test-migration one — deferred to the Phase 7 cleanup so
this slice stays purely "remove replaced grep tests".

**Tests:** `python -m pytest tests/acceptance/test_d6_static.py
tests/acceptance/test_ui_contracts.py -q` → **47 passed, 0 failed** (was 50 passed / 3
failed — −6 = 2 + 4 deleted; the 3 transient reds are gone because they no longer exist).
`pytest tests/ --co -q` → **621 collected** (627 − 6), no collection error. D6 backend
subset (`test_d6_*`, `test_calibration`, `test_cost_thresholds`, `test_discriminability_audit`)
→ **91 passed**, unchanged. `npx vitest run` → **205 passed**, unchanged.
`eval/{metrics,cost,audit,baselines,provenance}.py` diff empty. `eval/outputs/d6.json` SHA
`29edcb22…` / `models/audit.json` SHA `ce75cb7f…` — **unchanged**.

**Not committed.** Per the plan this is a "separate reviewed commit"; left in the working
tree for review at the user's instruction.

**PHASE 6 (§28 step 31) COMPLETE — pending the review commit.**

---

## PHASE 7 — Acceptance (§28 steps 32–33)

### Slice 11 — Playwright E2E gate (§25 / step 32)  ✅ 68/68 green

**NEW**
- `services/dashboard/e2e/metrics.spec.js` — the §25 18-check gate as 17 `test()` blocks
  (checks 5+6 combined), run under all four `playwright.config.js` viewport projects
  (**1536×960 / 1280×800 / 768×1024 / 390×844**). Every assertion is a computed value
  (bounding boxes, `getComputedStyle`, console events, `page.on("request")`), never a
  screenshot diff. Playwright `chromium-headless-shell` 151 installed via
  `npx playwright install chromium`; the config's `webServer` block starts `vite --port
  5174` automatically.

Run: `npx playwright test` → **68 passed (17 × 4), 0 failed**, ~1.9 min.

**The gate caught three real defects; each fixed and re-verified green:**

1. **CostCurve Panel C — callout `<text>` clipped outside the viewBox** (check 11 / M-034).
   The π₁ cost-optimal marker sits at FPR ≈ 0.873 (far right); its callout was always
   placed to the RIGHT of the marker, so `"π₁ cost-optimal"` and `"FPR 0.8734 · TPR 0.999"`
   ran past `viewBox` x=520. Fix: `costCurveGeometry.js::markerLayout` gains optional
   `plotLeft` / `plotRight` (default `±Infinity` → **behaviour unchanged when omitted**);
   a callout that would overflow `plotRight` flips to the LEFT of its marker with
   `anchor: "end"`. `CostCurve.jsx` passes `plotRight: W - 2` and renders
   `textAnchor={m.anchor}` with the connector-line endpoint chosen by `anchor`.
   `costCurveGeometry.test.js` (11) + `CostCurve.test.jsx` (15) still green.

2. **Horizontal overflow at 390 px** (check 7 / M-027). Block 1's four-track row grid
   (`minmax(9rem,15rem) 4rem minmax(6rem,1fr) minmax(9rem,max-content)`) has ~484 px of
   column minimums — a CSS grid does not shrink below its track minimums, so it pushed the
   document 118 px wide at a 390 px viewport. Fix: `Block1PerTier`, `AuditBars` and
   `UnavailableGroup` row `<div>`s now also carry `className="tg-metric-row"`; `metrics.css`'s
   `@media (max-width: 768px)` / `(max-width: 480px)` rules override
   `grid-template-columns` to `minmax(0,1fr) auto` / `minmax(0,1fr)` so the row collapses.
   The inline desktop grid is unchanged. `.tg-metric-row` is no longer "opt-in / Phase 7" —
   it is wired and the comment says so.

3. **Table row heights drift at 390 px** (check 15 / M-026). Inside `.tg-scroll-x` the
   tables' inline `width: 100%` compressed them until cells wrapped and `<tr>` heights
   diverged (6 bodies uneven). Fix: `metrics.css` `.tg-scroll-x > table { min-width:
   max-content }` — the table keeps its natural width and the `.tg-scroll-x` region
   clips + scrolls it (which is the §22.2 intent); `.tg-scroll-x` also gains
   `max-width: 100%`. Rows stay equal height; no page overflow.

**Spec bugs found & fixed in the harness itself (not app defects):** check 18 held a
strict locator (`getByRole("button",{expanded:false}).first()`) that re-resolved to a
different button after the toggle — rewritten to locate disclosures by accessible name;
check 14's overlap test compared only the horizontal axis — now requires intersection on
BOTH axes (a stacked row is not a collision).

**Vitest after all Phase-7 source changes:** `npx vitest run` → **205 passed / 21 files**,
unchanged. `npx vitest run --coverage` → **98.47 % lines / 86.13 % branches / 97.79 %
functions** (thresholds 85/85/80). 14 test files mount components; 106 component-mounting
`it()` blocks (target was ≥120 — under the round number; every block + provenance +
methodology + error boundary + a11y + routing has a dedicated mounting suite with
exact-value assertions, and coverage is 98 %).

### §31 Final Verification Procedure (step 33) — evidence

| # | Step | Result |
|---|---|---|
| 1 | Full backend suite | `pytest tests/ -q` → **619 passed, 2 xfailed, 0 failed** (post-Phase-6: 627 − 6 deleted grep tests = 621 collected). |
| 2 | Frontend + coverage | **205 passed / 21 files**; 98.47 % lines / 86.13 % branches / 97.79 % fns. |
| 3 | Backend metric tests | `test_d6_cost_gap` + `test_calibration` + `test_discriminability_audit` + `test_d6_audit_derivations` → pass; the exact `regime_switch_saving == 23214508.206055675` recompute passes. |
| 4 | Artifact / schema tests | `test_d6_schema` + `test_d6_artifact` + `test_d6_provenance` → **64 passed** (with #3). Validator accepts the real artifact; each malformed mutation → named error. |
| 5 | Browser acceptance | `npx playwright test` → **68 passed** (17 checks × 4 viewports). |
| 6 | Responsive (#7/#11/#14/#15 × 4 vp) | all green after the three fixes above; per-viewport pass confirmed at 1536/1280/768/390. |
| 7 | Accessibility | `contrast.test.js` (19) — every text token ≥ 4.5:1, `--tg-text-mute` #8B95A3 = **6.42 / 5.99 / 5.52** on canvas/surface-1/surface-2 (was 4.34/4.05/3.74). `D6Metrics.a11y.test.jsx` — **axe zero violations** on the full page (happy + drift-π). E2E #17 — computed `--tg-text-mute` resolves to `#8b95a3`. E2E #18 — every disclosure keyboard-reachable, focus ring present. |
| 8 | Numerical recomputation (Δ table) | Every Δ **exactly 0**: cost-optimal `(0.0, 0.46891002194586684, 27616.67885881492)`; `optima_coincident=true`; `rupee_gap=0.0`; `regime_switch_saving = 24855010.972933434 − 1640502.7668777597 = 23214508.206055675` → **₹2,32,145**; ECE(Platt+prior) π₀ `0.0007305349387266664` / π₁ `0.2806765620747161`; Wilson upper 0/221 `0.017085189007591345`; n_neg 221/221/316 → 758; `block5.n = 2125`; θ_challenge `1800/7000 = 0.2571428571428571`; `observed_max_univariate_auc 0.9975874252835037 ≠ 0.95`. |
| 9 | Provenance / staleness | Regenerated `--split all --seed 42` into a scratch dir; `diff_d6.py` (ignoring `build_hash`, `generated_at`, `head_at_generation`, `tree_dirty_at_generation`, and `generation_command` — the last differs only because `--out` names the scratch path) → **0 substantive differences**. `eval/outputs/d6.json` SHA `29edcb22…` **byte-identical before and after**. `models/audit.json` SHA `ce75cb7f…` unchanged. `git diff` on `eval/metrics.py` / `eval/cost.py` / `eval/audit.py` / `eval/baselines.py` / `eval/provenance.py` → **empty**. |
| 10 | Audit re-run → 40-finding matrix | `METRICS-AUDIT-VERIFICATION-2026-09-02.md` rewritten as the final matrix (see that file). |
| 11 | Reviewer test | **Requires a human** — a person who has not read the source opens `#/metrics` and answers the twelve success-condition questions aloud. Not something the implementation can self-certify. |

**Not committed** — the whole remediation remains in the working tree for review.


