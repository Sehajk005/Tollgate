# Tollgate — D6 Metrics Remediation: Implementation Report

**Plan:** `METRICS-REMEDIATION-PLAN-2026-09-02.md` · **Audit:** `METRICS-AUDIT-2026-09-02.md`
**Branch:** `day-2` · start HEAD `8cf17d9` · **Date:** 2026-09-02
**Detailed evidence log:** `METRICS-IMPLEMENTATION-LOG-2026-09-02.md`

> **Scope delivered (UPDATED — Phases 0–7 complete):** Phase 0 (artifact-integrity gate),
> Phase 1 (all backend work, schema v1→v2, the single deliberate artifact regeneration),
> Phase 2 (frontend foundation), Phase 3 (all six block components + provenance header +
> methodology panel + generated executive summary, off `buildMetricsModel`), Phase 4 (hash
> routing + `LiveShell` subscription isolation + error boundary), Phase 5 (§21 contrast +
> semantics + §22 responsive layer), Phase 6 (deleted the replaced grep tests — **staged, not
> committed**, pending review), Phase 7 (`e2e/metrics.spec.js` — **68 Playwright checks green
> across 4 viewports**, which caught and forced fixes for 3 real defects; the full §31
> verification procedure steps 1–10).
>
> **State:** backend `pytest tests/` → 619 passed / 2 xfailed / 0 failed; frontend
> `vitest run` → 205 passed / 21 files, 98.47 % line coverage; Playwright → 68 passed.
> `eval/outputs/d6.json` SHA `29edcb22…` and `models/audit.json` SHA `ce75cb7f…` unchanged;
> `git diff eval/metrics.py eval/cost.py eval/audit.py eval/baselines.py eval/provenance.py`
> empty. The 40-finding matrix is `METRICS-AUDIT-VERIFICATION-2026-09-02.md` (**40 FIXED**).
> **Outstanding:** §31 step 11 (the human reviewer test) and the Phase-6 review commit.
> The detailed slice-by-slice evidence is in `METRICS-IMPLEMENTATION-LOG-2026-09-02.md`
> (Slices 1–11); §5–7 below are the now-superseded continuation plan.

---

## 1. Phase 0 — artifact verification (§28 Phase 0 / §17.3)

`eval/outputs/d6.json` and `models/audit.json` backed up outside the repo and SHA-verified.
`scripts/diff_d6.py` (NEW) written — leaf-wise structural diff with float tolerance and
`--ignore` prefixes. Regenerated D6 into a scratch dir via
`python -m eval.harness --split all --seed 42 --corpus-db data/corpus/tollgate.db --model-dir models --out <scratch>`;
`eval/outputs/d6.json` SHA unchanged before/after.

**Diff (committed v1 vs scratch, nothing ignored):** exactly one leaf differs —
`provenance.build_hash` `9141a8ecc41b…` → `36d0cc4817e1…` (HEAD moved / tree dirty since the
artifact was committed; matches the audit §4/§8 exactly). `config_hash`, `fixture_sha256` and
every metric leaf reproduce identically.

**Decision (§17.3 table):** only the plan-permitted provenance field differs → the committed
artifact is **VERIFIED** against the current corpus/model/configs; the audit's §5.5 J-class
"unverified corpus provenance" is **closed**. Proceeded to Phase 1 (the "stop and report"
branch did not trigger).

## 2. Phase 1 — backend / artifact contract (§28 steps 6–13)

| Fix | Files | What changed |
|---|---|---|
| **FIX-BE-06** schema + provenance | `eval/d6_schema.py` **(NEW)**, `eval/d6.py` | stdlib declarative schema + `validate()`/`validate_or_raise()`; `write_artifact` refuses to write an invalid artifact; `SCHEMA_VERSION 1→2`; provenance gains `generated_at` (ISO-8601 UTC), `generation_command`, `head_at_generation`, `tree_dirty_at_generation`, `corpus_db_sha256`, `model_files_sha256`. `eval/provenance.py` not modified. |
| **FIX-BE-01** θ_challenge (M-020) | `eval/report.py`, `eval/d6.py` | `THETA_CHALLENGE = 0.257` → memoised `theta_challenge()` = `load_cost_model().tier_ladder()["challenge"]` = `1800/(1800+5200)` = `0.2571428571428571`; old name kept as a deprecated alias; both `report.py` sites + `d6.py` migrated; `block2_theta_challenge` emitted. `grep 0\.257 eval/` → nothing. **No Block-2 sanity-scorer FP movement.** |
| **FIX-BE-04** raw ECE + gap + verdict (M-010, M-036) | `eval/harness.py` | `_regime` adds `ece_raw` (same `metrics.ece` call) + `ece_gap_platt_prior_vs_platt`; block adds `prior_correction_helped_at_pi1`. **The 4 pre-existing calibration numbers are byte-identical.** |
| **FIX-BE-05** CI relabel + separability (M-040, M-011, M-013) | `eval/load.py`, `eval/report.py`, `eval/d6.py` | `_recall_json` adds `fpr_ci_low/high` + `ci_basis: "wilson_on_achieved_fpr"` (old keys kept); `_fmt_recall` → `95% CI on achieved FPR`; new `_augment_audit_block` DERIVES per-feature `separability = |auc-0.5|`, `direction`, `flagged_two_sided` (`>=` boundary) + `univariate_auc_threshold` (0.95) + `observed_max_univariate_auc` (0.9975874252835037). **`models/audit.json` SHA `ce75cb7f…` unchanged — no retrain, deep-copied input.** |
| **FIX-BE-03** Block 6 completeness (M-008, M-038) | `eval/harness.py`, `eval/d6.py` | `BaselineSummary.per_tier` (B1/B2 scored once over the whole timeline then **sliced by `stream_tier`** for easy/med/hard; the whole `tier_e` split for evasive); `block6_baselines.model` row; `b1/b2_sanity_floor` per-scorer Unavailable envelopes (`always_positive: null` now carries an "unreachable: constant scorer" reason). Per-tier tp/fp/tn/fn **sum exactly to overall**. |
| **FIX-BE-02** Block 2 model + B0 rows (M-007, M-017) | `eval/harness.py`, `eval/d6.py` | `HarnessRun.model_scorers` threaded through; `_block2_negative_controls` now emits **6 rows/scenario** (`l1-lgbm-v1`, `rules-only-v0` at `theta_challenge()`, then the 4 sanity scorers) = **42 rows**; adds `episode_flagged: bool`, `denominator_basis`, `available/reason`; model-less run → Unavailable envelopes. |

**Documented reading of the plan (not a behavioural deviation):** FIX-BE-03's implementation
text says slice `episode_tier == tier or not is_attack`, but its own regression test requires
per-tier confusion counts to *sum* to overall — mutually inconsistent (`or not is_attack`
shares legit across tiers so fp/tn can't sum). Resolved toward the test + the existing repo
convention: slice by `stream_tier` (exactly `evaluate().tier_breakdown`), which partitions
`temporal_test` 821+701+603=2125 and makes tp/fp/tn/fn all sum. Recorded in the log.

### 2.1 The single deliberate regeneration (§28 step 13)

| | SHA-256 |
|---|---|
| `eval/outputs/d6.json` before (v1) | `058f7e8ec3182a5414113e2c47d4b1df47f99e17eb02b3ef8f290850ad13f770` |
| `eval/outputs/d6.json` after (v2) | `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737` |
| `models/audit.json` before & after | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` **(unchanged)** |

**Full diff (committed v1 → regenerated v2, permitted provenance ignored):**
`added 528, removed 0, changed 72`. The 72 "changed" = `schema_version 1→2` (1) + Block-2 list
**re-indexing** (71 — the 4 sanity scorers' FP counts are byte-preserved through the shift,
verified pairwise). The 528 "added" are exclusively the intended additive v2 fields. **Zero
evaluation values changed.** `git diff --stat eval/metrics.py eval/cost.py` → empty.

### 2.2 Backend tests

**NEW (§24.3):** `test_d6_schema.py`, `test_d6_negative_controls_model_rows.py`,
`test_d6_block6_completeness.py`, `test_d6_audit_derivations.py`, `test_d6_provenance.py`.
**EXTENDED (§24.4):** `test_d6_cost_gap.py` (the weak `regime_switch_saving >= 0` replaced with
an exact recompute → `23214508.206055675`, `round(/100)==232145`; exact optima; all 20 curve
costs; ribbon/optima/decision-region), `test_calibration.py` (hand-computed
`ece([.1,.3,.6,.9],…,2) == 0.225`; `ece_raw`; verdict; 4 numbers byte-identical),
`test_cost_thresholds.py` (`theta_challenge() == 1800/7000`; no `0.257` in `eval/`),
`test_discriminability_audit.py` (derived fields vs a fresh corpus AUC recompute),
`test_d6_artifact.py` (`schema_version == 2`; delegates leaf validation; provenance v2).

**`python -m pytest tests/ -q` → 625 passed, 2 xfailed** (baseline 560 + 65; the 2 xfailed are
pre-existing). No regressions.

## 3. Phase 2 — frontend foundation

`scripts/diff_d6.py` **(NEW)**. `services/dashboard/`: `vitest.config.js`,
`playwright.config.js`, `src/test/setup.js`, `src/lib/{format,d6Contract,d6FieldCoverage,
metricsModel}.js` **(NEW)** + their `.test.js`, `src/__fixtures__/{realArtifact,mutate,
malformed,synthetic}.js` **(NEW)**, `package.json` (test scripts + 8 devDeps; **no runtime
dep**). `npx vitest run` → **51 passed** (format 9, contract 18, coverage 5, model 19),
including the mandatory `inr(23214508.206055675) === "₹2,32,145"` and the field-coverage
contract (zero unlisted / zero stale / every OMITTED ≥ 20-char reason across all 214 leaf
patterns).

## 4. Files

**NEW (backend):** `eval/d6_schema.py`, `scripts/diff_d6.py`,
`tests/acceptance/test_d6_{schema,negative_controls_model_rows,block6_completeness,audit_derivations,provenance}.py`.
**MODIFIED (backend):** `eval/d6.py`, `eval/harness.py`, `eval/report.py`, `eval/load.py`,
`tests/acceptance/test_d6_{artifact,cost_gap}.py`, `test_calibration.py`,
`test_cost_thresholds.py`, `test_discriminability_audit.py`, `eval/outputs/{d6.json,report.md}`.
**NEW (frontend):** `services/dashboard/{vitest,playwright}.config.js`, `src/test/setup.js`,
`src/lib/{format,d6Contract,d6FieldCoverage,metricsModel}.js` + 4 `.test.js`,
`src/__fixtures__/{realArtifact,mutate,malformed,synthetic}.js`.
**MODIFIED (frontend):** `services/dashboard/package.json`.
**NOT MODIFIED (deliberate):** `eval/metrics.py`, `eval/cost.py`, `eval/audit.py`,
`eval/baselines.py`, `eval/provenance.py`, `scripts/train_l1.py`, `models/*`, `config/*.yaml`,
`data/corpus/*`.

## 5. Remaining risks

- **R-1 (Phase 0 stale artifact):** retired — Phase 0 confirmed the artifact valid.
- **R-2 (θ_challenge moves Block-2):** retired — no sanity-scorer FP movement observed.
- **R-3 (per-tier B1 bitemporal bug):** mitigated — `stream_tier` slicing + the summed-counts
  test (`test_d6_block6_completeness.py`) both green.
- **Open:** everything Phase 3–7 covers is unmitigated because unbuilt — the Metrics *page*
  still renders the old JSX against the new v2 artifact. The v2 additions are additive so the
  old page still works, but none of the 40 findings' *frontend* halves is fixed yet.

## 6. Continuation plan (Phases 3–7, not done)

Start at §28 step 19. In order:
1. `src/lib/costCurveGeometry.js` + tests (extract geometry so it is unit-testable).
2. `src/components/MetricsErrorBoundary.jsx`; wire it around the Metrics route in `App.jsx`.
3. Rewrite `D6Metrics.jsx` as composition over `buildMetricsModel`; add
   `components/metrics/{Block1PerTier,Block2NegativeControls,Block5Calibration,Block6Baselines,
   ProvenanceHeader,MethodologyPanel,UnavailableGroup,OperatingPointTable}.jsx`,
   `components/charts/ReliabilityDiagram.jsx`; rewrite `BarRow`/`AuditBars`/`CostCurve`.
4. Rendering tests FE-T-B1..B6, FE-T-PROV, FE-T-SUM, FE-T-ERR, FE-T-A11Y (≥120, exact strings,
   `vitest-axe`).
5. `hooks/useHashRoute.js` (`#/metrics`, `<title>`, `aria-current`); `components/LiveShell.jsx`
   (mount `useEventStream/useReplayStatus/useIncidents` only on live routes).
6. §21 token contrast (`--tg-text-mute` `#6E7885`→`#8B95A3`), semantic tables/ARIA/SVG,
   §22 `styles/metrics.css` responsive layer.
7. Delete the obsolete grep tests — separate commit, only after JS replacements are green.
8. `e2e/metrics.spec.js` Playwright (18 checks × 4 viewports); §31 steps 1–11; then
   `METRICS-AUDIT-VERIFICATION-2026-09-02.md` and the §31.11 reviewer test.

## 7. Reviewer test (§31.11)

**Not performed** — the reviewer test requires the rebuilt Metrics page (Phases 3–5). The
twelve questions it poses are answerable from the *artifact* today (Phase 1 added every field
they need) but not yet from the *page*.
