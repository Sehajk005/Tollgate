# Tollgate — D6 Metrics & Evaluation: Remediation Plan

**Date:** 2026-09-02
**Remediates:** `METRICS-AUDIT-2026-09-02.md` (40 findings: 2 Critical · 8 High · 21 Medium · 9 Low)
**Branch:** `day-2` · HEAD `8cf17d9` · working tree dirty
**Status:** PLAN ONLY. No repository file was modified in producing this document.

---

## 1. Executive Summary

The audit's central conclusion is correct and this plan is built on it: **the arithmetic is
right, the rendering is faithful, and the page is still misleading — because it selects the
flattering half of an honest artifact.** There are zero calculation errors and zero
backend/frontend value mismatches. There are 23 computed values the frontend throws away,
4 the backend never computes, and 6 that are represented in a way that misleads.

The remediation is therefore **overwhelmingly a consumption-and-presentation problem, not a
mathematics problem.** No metric implementation in `eval/metrics.py` or `eval/cost.py` is
rewritten. The Wilson interval, the `resolvable:false` semantics, the ROC hull, the ECE
definition, the prevalence transform and the cost formulas are preserved exactly.

Two investigations during planning changed the shape of the work relative to what the audit
assumed. Both are load-bearing.

**(A) Safe artifact regeneration already exists.** `eval/harness.py:496` declares `--out`
(default `eval/outputs`). Running

```
python -m eval.harness --split all --seed 42 \
  --corpus-db data/corpus/tollgate.db --model-dir models \
  --out <scratch-dir>
```

writes `report.md` and `d6.json` into `<scratch-dir>` and **never touches
`eval/outputs/d6.json`**. The audit's §5.5 "UNVERIFIED corpus provenance" is resolvable today
with no new mechanism — see §17.3. This plan therefore closes that gap rather than carrying it
forward as a caveat.

**(B) Block 2's `episodes = 1` is structurally forced, not statistically under-powered.**
`eval/corpus.py::build_runs()` creates exactly **one run per negative-control scenario**, and
each such run contains exactly **one** negative-control episode. `episodes` can therefore never
exceed 1 under the current corpus construction. The audit classified this as
"SUSPICIOUS-LEGITIMATE / under-powered" (M-017). It is neither — it is a **boolean rendered as
a rate**. The correct fix is to re-type it (`episode_flagged: true|false`), not to attach a
confidence interval and not to seek more episodes, which would require regenerating the corpus
and would move every number on the page.

A third finding, smaller but real, was not in the audit: **`flagged` is computed with `>` in
the backend (`scripts/train_l1.py:165`) and with `>=` in the frontend (`AuditBars.jsx:16`)**,
and the backend's `flagged` excludes the `excluded` set while the frontend's includes it. They
agree today only because no feature sits exactly at 0.95 and all 6 excluded features are also
over threshold. This is a second latent drift inside M-012.

### The one-sentence statement of what must change

The Metrics page must stop being a *selection* of the artifact and become a *projection* of it
— every field either rendered, or explicitly and testably declared as intentionally omitted —
with a real JavaScript test suite that fails when the projection lies.

### Scale of work

| Layer | Work |
|---|---|
| Backend (`eval/`) | 4 missing metrics, 1 threshold derivation, 1 CI mislabel, schema + `generated_at`. **No metric maths rewritten.** |
| Artifact contract | `schema_version` 1 to 2, additive-only, backwards-readable |
| Frontend | 23 discarded fields consumed; 6 representations corrected; cost chart rebuilt; routing; error boundary; a11y; responsive |
| Tests | **New JS test infrastructure** (Vitest + Testing Library + jsdom; Playwright for viewport gates); Python grep-tests demoted from "frontend contract" to what they actually are |

### Non-negotiables carried from the audit

- The 9 `resolvable:false` recall figures **stay `n/a`**. They are mathematically unresolvable
  at n_neg 221/221/316/758 against the 1000 that FPR=1e-3 requires. This is the page's best
  existing behaviour; it is preserved, improved in presentation only.
- B0 beats the learned model on all four tiers in raw AP. **That gets rendered**, in the form
  `Decisions.md` Decision 64 already commits to publishing.
- No undefined value becomes `0`. No placeholder is styled like a measurement.

---

## 2. Current Architecture

### 2.1 The real data path (verified end to end)

```
config/*.yaml ─────────────┐
data/corpus/tollgate.db ───┤
models/{l1-lgbm-v1,platt-v1,audit}.json ─┘
        │
        ▼
python -m eval.harness              (OFFLINE, MANUAL, human-run)
        │  eval/harness.py::run_all() -> HarnessRun{
        │      eval_reports{split -> [Report per scorer]},
        │      negative_splits, baseline_summary,
        │      calibration_block, audit_block }
        ▼
eval/d6.py::build_artifact()        (pure serialiser; only block 4 is new arithmetic)
        │
        ▼
eval/outputs/d6.json                (COMMITTED; .gitignore:24-28 carries !eval/outputs/d6.json)
        │
        ▼  ES-module import at BUILD time (Vite inlines it)
services/dashboard/src/screens/D6Metrics.jsx
        ├─ Block1 -> components/charts/BarRow.jsx
        ├─ Block2 -> inline <table>
        ├─ Block3 -> components/charts/AuditBars.jsx
        ├─ Block4 -> components/charts/CostCurve.jsx   (inline SVG, no chart library)
        ├─ Block5 -> inline <table>
        └─ Block6 -> components/charts/BarRow.jsx
        ▼
DOM
```

**Path correction to the brief:** `BarRow.jsx` and `AuditBars.jsx` live at
`services/dashboard/src/components/charts/`, **not** `services/dashboard/src/components/`.
The brief lists the latter; those files do not exist. All three chart components are in
`components/charts/`.

### 2.2 Architectural facts that constrain every fix

| # | Fact | Consequence for this plan |
|---|---|---|
| 1 | D6 is a **build-time import**, not an API | No loading state needed; a *missing* file fails the Vite build; the exposure is a *malformed* or *version-skewed* file |
| 2 | `block3_audit` is byte-identical to `models/audit.json` | Block 3 is produced at **model-training time** by `scripts/train_l1.py::run_audit`. Changing its shape means retraining (changes model identity) or deriving downstream. **This plan derives.** |
| 3 | Only `block4_cost` is computed by `eval/d6.py` | Blocks 1/2/3/5/6 are pass-through; new backend metrics belong in `harness.py`/`d6.py`, not a new module |
| 4 | `_block1_per_tier` reads `evasive` from the `tier_e` split, easy/medium/hard from `temporal_test` | M-016 is real and must be **labelled**, not merged |
| 5 | `Layer1Scorer`/`B0RulesScorer` raise `KeyError` on a missing feature-corpus row | M-007 feasibility depends on corpus coverage of negative-control runs — **verified present, §2.3** |
| 6 | `run_all` builds model scorers only when `--corpus-db` + `--model-dir` are supplied | Every new model-dependent field must degrade to an explicit "unavailable + reason", never to a fabricated value |
| 7 | `App.jsx` calls `useReplayStatus`/`useEventStream`/`useIncidents` unconditionally, before the route switch | M-031: SSE + 1 Hz polling stay live on a static screen |
| 8 | `services/dashboard/package.json` declares exactly one script, `dev` | No JS test runner exists at all (M-030) |

### 2.3 Feature-corpus coverage — the M-007 feasibility gate

Queried read-only against `data/corpus/tollgate.db` using `eval/corpus.py::_CORPUS_QUERY`:

| run_index | rows | identity |
|---:|---:|---|
| 0–11 | 821/701/508 (×4 blocks each) | 12 tier blocks (easy/medium/hard) |
| **12–18** | **720, 300, 500, 5, 200, 216, 61** | **the 7 negative-control scenario runs** |
| 19 | 390 | tier_e |

**All 7 negative-control runs have feature rows.** `Layer1Scorer` and `B0RulesScorer` can
therefore score negative-control samples without raising. **M-007 is implementable with no
corpus regeneration and no retraining.**

Note that `shared_ip_legit` carries **61** corpus rows but Block 2 reports `attempts = 1`.
That is correct and deliberate: `eval/report.py::_episode_and_attempt_fp` counts only
`is_attack=False` samples, and in the F14 scenario 60 of the 61 attempts are the attacker's.
The denominator semantics are **"legitimate attempts only"** and must be labelled as such —
the current UI does not say this anywhere.

### 2.4 Existing test inventory, classified

| File | Class | Disposition |
|---|---|---|
| `tests/acceptance/test_d6_cost_gap.py` | **Real artifact-contract test with an anti-circularity anchor** | **KEEP + STRENGTHEN.** The `C_FN=5200`/`C_FP=1800` hardcodes are correct by design. Replace `regime_switch_saving >= 0` with an exact recomputation. |
| `tests/acceptance/test_d6_artifact.py` | Artifact presence test | **KEEP + EXTEND** into real schema validation |
| `tests/acceptance/test_d6_static.py` | **Source-string grep over JSX** | **DEMOTE + RESCOPE.** Its `fetch(`/`EventSource` ban is a genuine architectural invariant and stays as a source scan. `test_all_six_blocks_are_referenced` and `test_cost_curve_renders_*` are fake rendering coverage and are **replaced** by real DOM tests. |
| `tests/acceptance/test_ui_contracts.py::TestD6Resolvability` | **Source-string grep** | **REPLACE** with rendering tests. `test_no_unresolvable_entry_can_reach_a_tofixed_path` guards a real invariant — reimplement as a DOM assertion. |
| `tests/acceptance/test_metrics_resolution.py` | **Real backend unit test** | KEEP UNCHANGED |
| `tests/acceptance/test_discriminability_audit.py` | **Real backend test** (recomputes AUC from the corpus) | KEEP; extend for the new derived fields |
| `test_calibration.py`, `test_cost_thresholds.py`, `test_cost_curve_endpoints.py`, `test_baselines_single_source.py`, `test_negative_controls_evaluated.py`, `test_harness_sanity.py` | Real backend tests | KEEP; extend where this plan adds metrics |

**The rule this plan enforces:** a source-string test may assert an *architectural* invariant
("this file contains no `fetch(`"). It may **never** stand as evidence that a value is
rendered. Every "does the UI show X" assertion moves to the JS suite.

---

## 3. Audit Findings Summary

| Severity | Count | IDs |
|---|---:|---|
| Critical | 2 | M-001, M-002 |
| High | 8 | M-003 … M-010 |
| Medium | 21 | M-011 … M-031 |
| Low | 9 | M-032 … M-040 |

Grouped by the layer that must actually change:

| Fix layer | Findings | n |
|---|---|---:|
| **Frontend consumption** (field exists, discarded) | M-001 (part), M-002, M-006, M-009, M-010 (part), M-012, M-021, M-022, M-038 | 9 |
| **Backend metric missing** | M-007, M-008 (part), M-010 (ECE-raw) | 3 |
| **Backend contract / naming** | M-011, M-020, M-029, M-040 | 4 |
| **Visualisation correctness** | M-003, M-004, M-005, M-013, M-028, M-034, M-039 | 7 |
| **Copy / representation** | M-015, M-016, M-017, M-032, M-033, M-036, M-037 | 7 |
| **Page architecture** | M-018, M-019, M-031, M-035 | 4 |
| **Accessibility** | M-023, M-024 | 2 |
| **Responsive / layout** | M-025, M-026, M-027 | 3 |
| **Test infrastructure / formatting** | M-030, M-014 | 2 |

---

## 4. Root-Cause Analysis

Forty findings reduce to **six** root causes. Fixing the causes rather than the symptoms is
what keeps this from becoming forty independent patches.

### RC-1 — The frontend is a curator, not a projector
*Drives M-001, M-002, M-006, M-009, M-010, M-022, M-038 and all 23 discarded values.*

`D6Metrics.jsx` hand-picks fields (`apMetric = (tm) => ({ value: tm.ap_raw })`). Nothing
enumerates the artifact's surface, so a field can be added to the backend and silently never
appear. There is no inventory, no diff, no test.

**Structural remedy:** an explicit **field-coverage contract** — a machine-checked list of every
artifact leaf, each marked `rendered` or `intentionally-omitted (reason)`. A test walks the real
artifact and fails on any leaf in neither set. "The frontend quietly dropped it" becomes a
permanent test failure.

### RC-2 — Semantic constants are duplicated instead of read
*Drives M-012, M-020, M-021 and the `>` vs `>=` drift found during planning.*

`THRESHOLD = 0.95`, the `flagged` recomputation, the `π₀ = 0.001` / `π₁ = 0.9` label literals
and `THETA_CHALLENGE = 0.257` are copies of values that exist authoritatively elsewhere.

**Structural remedy:** one authoritative source per semantic value; layout constants (SVG
`W`/`H`/margins, tier display order) explicitly exempted and documented as exemptions.

### RC-3 — "Unknown" has three incompatible encodings
*Drives M-011, M-038, M-040 and the whole schema gap.*

`recall_at_target_fpr` is a rich object with `resolvable`. `ap_raw` is a bare `float | absent`.
`sanity_recall_at_*.always_positive` is a bare `null` with no reason. `max_univariate_auc` is
misnamed — it is the *threshold* (0.95); the real maximum is 0.9976.

**Structural remedy:** a single **`Unavailable` envelope** `{value, available, reason, …}`
introduced additively at `schema_version: 2`, with all v1 keys retained.

### RC-4 — Charts were built for the data's *shape*, not its *distribution*
*Drives M-003, M-004, M-005, M-013, M-028, M-034.*

`CostCurve` assumes two comparable series (they differ 900×), a linear FPR axis (the decision
region occupies 0.13% of it), non-crossing ribbon envelopes (they cross at FPR≈0.30) and markers
not on an axis (both optima are at FPR=0.0). `AuditBars` assumes discriminability is one-sided
(it is `|AUC−0.5|`) and that every row is a measurement (14 of 24 are not).

**Structural remedy:** re-derive each chart from what the data actually is — per-regime scales,
a decision-region focus, a true per-x min/max envelope, `|AUC−0.5|` ranking, and a null state
that is not bar-shaped.

### RC-5 — A static report living inside a live shell
*Drives M-018, M-031, M-035 and the stale `<title>`.*

`App.jsx` mounts the SSE/polling hooks before the route switch, uses `useState` for navigation,
and caps content at `maxWidth: 900`.

**Structural remedy:** hash routing plus route-scoped subscription mounting.

### RC-6 — No frontend test runner, so none of the above is detectable
*Drives M-030 and the invisibility of the other 39.*

The suite is green while the ₹2,32,145 headline is asserted only `>= 0`.

**Structural remedy:** a real JS suite whose assertions are DOM- and geometry-level, plus
migration of the misleading grep tests.

---

## 5. Data Lineage

Per block: `SOURCE → CALCULATION → ARTIFACT → IMPORT → TRANSFORM → COMPONENT → DOM`, with the
remediation layer named. **This table is the instrument that decides where each fix goes.**

### Block 1 — Per-tier performance

| Value | Source | Calculation | Artifact path | Frontend today | Fix layer |
|---|---|---|---|---|---|
| recall @ FPR 1e-3 | corpus + model | `metrics.py::recall_at_fpr` | `block1_per_tier.{mv}.{tier}.recall_at_target_fpr` | rendered `n/a` — **correct** | presentation only |
| `ap_raw` | corpus + model | `metrics.py::average_precision` | `…{tier}.ap_raw` | rendered **without prevalence** | **frontend** |
| `prevalence` | split | `n_pos/n` | `…{tier}.prevalence` | **discarded** | **frontend** |
| `ap_at_eval_prevalence` | corpus + model | `metrics.py::ap_at_prevalence` | `…{tier}.ap_at_eval_prevalence` | **discarded** | **frontend** |
| `n` | split | count | `…{tier}.n` | discarded | frontend |
| B0 per-tier AP | corpus + rules | same | `block1_per_tier["rules-only-v0"].{tier}.ap_raw` | **discarded** | **frontend** |
| π_eval | `cost_model.yaml:eval_prevalence` | — | `provenance.eval_prevalence` | **discarded** | **frontend** |
| split identity | `Report.split_name` | — | `block4_cost.split`, `block6_baselines.b0.split` | **discarded** | **backend (add per-tier) + frontend** |

**Every Block 1 defect except the per-tier split label is frontend-only.** The backend already
computes all of it.

### Block 2 — Negative controls

| Value | Source | Calculation | Artifact | Frontend | Fix layer |
|---|---|---|---|---|---|
| sanity FP rows | negative splits | `report.py::_episode_and_attempt_fp` | `block2_negative_controls.{scenario}[]` | rendered — correct | presentation |
| **model FP rows** | corpus + model | *not computed* | **absent** | — | **BACKEND** |
| **B0 FP rows** | corpus + rules | *not computed* | **absent** | — | **BACKEND** |
| θ_challenge | `cost_model.yaml` | `C_FP/(C_FP+C_FN)` | *not emitted* | hardcoded `0.257` upstream | **BACKEND (derive + emit)** |
| `episodes` | `len(flagged_by_episode)` | structurally 1 | `…[].episodes` | rendered as a rate | **BACKEND re-type + frontend** |
| denominator meaning | legit-only | `is_attack` filter | implicit | unlabelled | frontend copy |

### Block 3 — Discriminability

| Value | Source | Calculation | Artifact | Frontend | Fix layer |
|---|---|---|---|---|---|
| `univariate_auc` | training matrix | `eval/audit.py::univariate_auc` | `block3_audit.features.{f}.univariate_auc` | rendered | ok |
| `constant` | `np.all(col==col[0])` | `train_l1.py:162` | `…{f}.constant` | **discarded** | **frontend** |
| `reason` | `features.yaml` / Decision 43 | `train_l1.py:173` | `…{f}.reason` | **discarded** | **frontend** |
| `flagged` | `auc > threshold and not constant` | `train_l1.py:165` | `…{f}.flagged` | **recomputed with `>=` and `\|\| excluded`** | **frontend (read it)** |
| threshold | `config/features.yaml:19` | — | `block3_audit.max_univariate_auc` | hardcoded | **frontend + backend rename** |
| separability `\|AUC−0.5\|` | derived | *not computed* | absent | absent | **`eval/d6.py` derive — NOT retrain** |

**Critical constraint:** `block3_audit` *is* `models/audit.json`, written at training time.
Adding a two-sided flag must **not** require retraining — it is a pure function of
`univariate_auc`, already present. Derive it in `eval/d6.py`.

### Block 4 — Cost

All values verified exact by the audit. The lineage is sound; **only the rendering is wrong**
(M-003/004/005/034), plus two additive backend emissions: `coincident` as a stated fact rather
than a frontend float comparison, and a correct ribbon envelope.

### Block 5 — Calibration

| Value | Artifact | Frontend | Fix layer |
|---|---|---|---|
| `brier_platt`, `brier_platt_prior`, `ece_platt`, `ece_platt_prior` | present | rendered | ok |
| `brier_raw` | **present** | **discarded** | **frontend** |
| **`ece_raw`** | **absent** | — | **BACKEND** (`harness.py::_regime`) |
| `reliability_pi0` / `reliability_pi1` (2 × 10 bins) | **present** | **discarded** | **frontend** |
| `effective_n`, `pi_t`, `raw_prevalence`, `n`, `n_bins` | present | discarded | frontend |
| ECE gap / verdict | absent | absent | **BACKEND derive + frontend** |

### Block 6 — Baselines

| Value | Artifact | Frontend | Fix layer |
|---|---|---|---|
| B0 recall / AP / `roc_auc` | present (`roc_auc` discarded) | partial | frontend |
| B1 / B2 operating points | present (confusion matrix discarded) | partial | frontend |
| `sanity_recall_at_b1_fpr` / `…b2_fpr` (B3) | **present** | **discarded** | **frontend** |
| **model row** | **absent** | — | **BACKEND** |
| **per-tier baselines** | **absent** | — | **BACKEND** |

### Provenance

| Required by Eval §9 | In artifact | Rendered |
|---|---|---|
| `seed` | ✅ 42 | ✅ |
| `config_hash` | ✅ | ✅ |
| `model_version` | ✅ | ✅ |
| **`policy_version`** | ✅ 1 | ❌ **frontend** |
| **π_eval** | ✅ 0.01 | ❌ **frontend** |
| **split name** | ✅ (per block) | ❌ **frontend** |
| `seeds_used` | ✅ 1 | ❌ frontend |
| **`generated_at`** | ❌ | ❌ **BACKEND** |

---

## 6. Missing-Value Classification

Applying the brief's A–J taxonomy to every gap. **This table governs the remediation: a value
classified A is never given a number; a value classified B is never faked in the frontend.**

### A — Correctly unresolvable (9). PRESERVE.

| Value | Why unresolvable | Current UI | Plan |
|---|---|---|---|
| recall@1e-3 — model × easy/medium/hard/evasive (4) | n_neg 221/221/316/221 < 1000 | `n/a · n_neg=221`, no bar | **Keep the semantics exactly.** Improve presentation only (§13, §20.5): grouped explanation, non-bar-shaped null state, denominator retained. |
| recall@1e-3 — B0 × 4 tiers (4) | same | same | same |
| B0 overall recall@1e-3 (1) | n_neg 758 < 1000 | same | same |

`eval/metrics.py::recall_at_fpr` sets `resolvable = n_neg >= 1/target_fpr`. At
`target_fpr = 1e-3` that is 1000 negatives. Empirical FPR is quantised at `1/n_neg`; at 221
negatives the finest non-zero FPR is 0.00452 — **4.5× the target**. The metric genuinely
cannot be resolved. **Under no circumstances does this plan render a number here.**

The artifact deliberately still stores a `value` (e.g. B0 = 0.7769) so the markdown report can
distinguish "unreachable" from "measured but unresolvable". The UI must continue to refuse to
print it. This is enforced by a dedicated rendering test (§23.6, `FE-T-MV-01`).

### B — Backend metric missing (4). COMPUTE IN BACKEND.

| Value | Where it is added | Effort |
|---|---|---|
| `ece_raw` (both regimes) | `eval/harness.py::_regime` — one call to the existing `metrics.ece()` | trivial |
| Model + B0 FP rows, Block 2 | `eval/d6.py::_block2_negative_controls` — corpus coverage verified §2.3 | moderate |
| Model row, Block 6 | `eval/d6.py::_block6_baselines` — the report object is already in `_temporal_reports(run)` | small |
| Per-tier B1/B2, Block 6 | `eval/harness.py::_baseline_summary` — slice by `episode_tier` | moderate |

### C — Artifact field missing though computable (4). EMIT.

`generated_at` · `theta_challenge` · per-tier `split` name · `separability` + two-sided flag.
All derivable from data the harness already holds. **None requires retraining or corpus work.**

### D/E — Frontend mapping / rendering missing (23). CONSUME.

The full list is the audit's §5.2. Enforced permanently by the **field-coverage contract**
(§18.4). This is the single largest category and the one the current architecture makes
invisible.

### F — Incorrect representation of an available value (6). RE-PRESENT.

| Value | Shown as | Must become |
|---|---|---|
| 14 un-fed constants | `0.500` + a real 50% bar | grouped "not fed — no measurement", **no bar** |
| 2 inverted features (0.289, 0.225) | weakest bars, sorted last | ranked by `\|AUC−0.5\|`, sign shown separately |
| `ap_raw` ×4 | bare 0–1 bar | bar with its prevalence floor marked, prevalence printed |
| 8 unresolvable recalls | full-width grey **track** reading as a 100% bar | visually distinct non-bar null state |
| `episodes = 1` | fraction `0/1` | **boolean** — "episode flagged: no" |
| `₹0` rupee gap | an empirical finding | stated as **structurally forced** at π₀ |

### G — Intentional omission (2). DOCUMENT, don't silently drop.

`fixture_sha256` and `calibrator_version` — deliberately off the header line. Under the new
contract they become **explicit** `intentionally-omitted` entries with a stated reason, so the
coverage test passes for a declared reason rather than by silence. Both are surfaced in the
expandable Methodology panel (§20.3), so nothing is actually hidden.

### H — Stale data (1). DETECT AND DISCLOSE. §17.

### I — Specification mismatch (2).

- `max_univariate_auc` is the threshold, not a maximum (M-011).
- `ci_low`/`ci_high` are Wilson intervals on the **achieved FPR** but render immediately after
  the **recall** value (M-040) — **and the same mislabel exists in
  `eval/report.py::_fmt_recall:50`, which prints `95% CI` after the recall figure in the
  markdown report.** The audit found only the frontend instance. Both are fixed at source.

### J — Unknown / unverified (1 → 0).

Artifact-vs-corpus provenance. **This plan closes it** via the non-destructive `--out` workflow
(§17.3). It is a Phase 0 gate, not a carried-forward caveat.

---

## 7. Target Architecture

```
config/*.yaml + corpus + models/
        │
        ▼
eval/harness.py         + ece_raw, + ece_gap, + per-tier baselines,
        │                 + theta_challenge derived from the cost model
        ▼
eval/d6.py              + model/B0 negative-control rows, + model baseline row,
        │                 + separability (derived, no retrain), + generated_at,
        │                 + ribbon envelope, + coincident flag, + per-tier split
        ▼
eval/d6_schema.py  (NEW)  validates on write AND in the pytest contract test
        │
        ▼
eval/outputs/d6.json      schema_version: 2 — additive; every v1 key retained
        │
        ▼  build-time import (UNCHANGED — App Flow §5 D6 "static render" preserved)
services/dashboard/src/lib/d6Contract.js   (NEW)
        │   • schema_version check
        │   • normalises the three "unknown" encodings into one Unavailable envelope
        │   • throws a typed ArtifactContractError, never a raw TypeError
        ▼
services/dashboard/src/lib/format.js       (NEW)  single number/currency policy
services/dashboard/src/lib/metricsModel.js (NEW)  artifact -> view model; pure; unit-tested
        │
        ▼
screens/D6Metrics.jsx  (rewritten as a composition)
   + components/metrics/*.jsx (NEW)  one component per block, individually testable
        │
        ▼
components/MetricsErrorBoundary.jsx (NEW)  scoped to the Metrics route only
        ▼
DOM
```

**Deliberately unchanged:** the build-time-import architecture (a genuine strength — zero
runtime requests, no loading state, no partial data, verified by the audit at 0 network
requests and 0 console errors); the inline-SVG, no-charting-library decision (UIUX §6.13:
"three chart shapes do not justify a dependency"); the plain-CSS token system (`tokens.css`
documents why Tailwind was excluded despite UIUX §10, citing Decisions.md Day 8); and every
metric implementation in `eval/metrics.py` / `eval/cost.py`.

**The `metricsModel.js` seam is the key addition.** It converts the artifact into an explicit
view model *before* any component sees it. That makes the 23 dropped fields visible as a data
problem rather than an invisible omission, makes missing-value semantics testable without
rendering, and gives the coverage contract a concrete surface to check.

---

## 8. Artifact / Data Contract Changes

### 8.1 Principles

1. **Additive only.** Every `schema_version: 1` key survives unchanged at v2. Nothing is
   removed or re-typed in place; renames ship as *new key added, old key retained + deprecated*.
2. **A reader accepting v1 must still parse v2.** The frontend accepts `schema_version ∈ {1,2}`
   and degrades gracefully on v1 (new sections render an explicit "requires artifact v2" state,
   never a zero).
3. **No new metric is invented.** Every added field is either a value the harness already
   computes but does not serialise, or a pure function of fields already present.

### 8.2 The `Unavailable` envelope (fixes RC-3)

One shape for every "we don't know", used by all *new* fields:

```jsonc
{ "value": null, "available": false, "reason": "unreachable: scorer has <=2 distinct ROC points" }
{ "value": 0.9782, "available": true, "reason": null }
```

`recall_at_target_fpr` keeps its existing richer shape (`value`, `n_neg`, `resolvable`,
`ci_low`, `ci_high`) — it is the best-designed object in the artifact and re-typing it would
churn a correct, test-covered contract for no gain. `d6Contract.js` normalises **both** shapes
plus bare-`null` and absent-key into one internal representation, so components see exactly one
missing-value concept.

### 8.3 Field-by-field change list

| # | Path | Change | Type | Finding |
|---|---|---|---|---|
| 1 | `schema_version` | `1` → `2` | modify | schema |
| 2 | `provenance.generated_at` | ISO-8601 UTC, e.g. `2026-09-02T14:31:07Z` | **add** | M-029 |
| 3 | `provenance.generation_command` | the argv that produced it | **add** | M-029 |
| 4 | `provenance.corpus_db_sha256` | SHA-256 of `--corpus-db` | **add** | M-029, §17 |
| 5 | `provenance.model_files_sha256` | `{filename: sha256}` for `models/*` | **add** | M-029, §17 |
| 6 | `provenance.head_at_generation` | `git rev-parse HEAD` | **add** | M-029 |
| 7 | `provenance.tree_dirty_at_generation` | bool | **add** | M-029 |
| 8 | `block1_per_tier.{mv}.{tier}.split` | e.g. `temporal_test` / `tier_e` | **add** | M-016, M-009 |
| 9 | `block1_per_tier.{mv}.{tier}.eval_prevalence` | π_eval echoed per tier | **add** | M-001 |
| 10 | `block2_negative_controls.{s}[].episode_flagged` | bool — replaces the `0/1` rate reading | **add** | M-017 |
| 11 | `block2_negative_controls.{s}[].denominator_basis` | `"legitimate_attempts_only"` | **add** | M-017 |
| 12 | `block2_negative_controls.{s}[]` rows for `l1-lgbm-v1`, `rules-only-v0` | **add rows** | M-007 |
| 13 | `block2_theta_challenge` | derived `C_FP/(C_FP+C_FN)`, unrounded | **add** | M-020 |
| 14 | `block3_audit.univariate_auc_threshold` | correctly-named twin of `max_univariate_auc` | **add** | M-011 |
| 15 | `block3_audit.observed_max_univariate_auc` | the real maximum (0.9976) | **add** | M-011 |
| 16 | `block3_audit.features.{f}.separability` | `abs(auc - 0.5)`, `null` if `auc is None` | **add** | M-013 |
| 17 | `block3_audit.features.{f}.direction` | `"positive"` / `"inverted"` / `null` | **add** | M-013 |
| 18 | `block3_audit.features.{f}.flagged_two_sided` | `separability >= (thr - 0.5) and not constant` | **add** | M-013 |
| 19 | `block4_cost.optima_coincident` | bool, computed in Python not JS | **add** | M-004, M-039 |
| 20 | `block4_cost.rupee_gap_is_structural` | bool + `rupee_gap_note` | **add** | M-039 |
| 21 | `block4_cost.ribbon_envelope` | `[[fpr, lo_cost, hi_cost], …]` per-x min/max | **add** | M-005 |
| 22 | `block4_cost.decision_region_fpr_max` | e.g. `0.002` — the focus-panel bound | **add** | M-003 |
| 23 | `block5_calibration.pi{0,1}.ece_raw` | **new metric** | **add** | M-010 |
| 24 | `block5_calibration.pi{0,1}.ece_gap_platt_prior_vs_platt` | derived | **add** | M-010 |
| 25 | `block5_calibration.prior_correction_helped_at_pi1` | bool — Eval §3.4's own test | **add** | M-010, M-036 |
| 26 | `block6_baselines.model` | `{split, n, prevalence, roc_auc, ap_raw, recall_at_target_fpr}` | **add** | M-008 |
| 27 | `block6_baselines.per_tier.{tier}.{b0,b1,b2,model}` | per-tier operating points | **add** | M-008 |
| 28 | `block6_baselines.b{1,2}.sanity_floor` | re-homed `sanity_recall_at_b*_fpr` + reason for `null` | **add** | M-008, M-038 |
| 29 | `…recall_at_target_fpr.fpr_ci_low` / `.fpr_ci_high` | correctly-named twins; `ci_low`/`ci_high` retained + deprecated | **add** | M-040 |
| 30 | `…recall_at_target_fpr.ci_basis` | `"wilson_on_achieved_fpr"` | **add** | M-040 |

**Rows 12, 26, 27 are the only entries that require the model bundle.** When `run_all` is
invoked without `--corpus-db`/`--model-dir`, each is emitted as an explicit `Unavailable`
envelope with `reason: "harness run without --model-dir; model scorer unavailable"` — never
omitted, never zeroed. The UI then renders that reason verbatim.

### 8.4 Backwards compatibility

| Consumer | Impact | Action |
|---|---|---|
| `services/dashboard/src/screens/D6Metrics.jsx` | rewritten anyway | n/a |
| `tests/acceptance/test_d6_artifact.py` | asserts presence of 6 blocks + 8 provenance fields — all retained | extend, no break |
| `tests/acceptance/test_d6_cost_gap.py` | reads `block4_cost` keys — all retained | extend, no break |
| `tests/acceptance/test_ui_contracts.py` | reads `block1_per_tier.*.recall_at_target_fpr.resolvable` — retained | replaced by JS tests |
| `eval/report.py` | consumes `HarnessRun`, not the artifact | unaffected except the §9.5 `_fmt_recall` fix |
| `eval/load.py::write_eval_run` | writes `eval_run` rows from `Report`, not the artifact | unaffected |
| `models/audit.json` | **not modified** — `separability` is derived downstream in `d6.py` | **no retrain** |

---

## 9. Backend Remediation Plan

Six items. **No metric mathematics is rewritten.** Every item is either a new call to an
existing correct function, a serialisation, or a derivation.

---

### FIX-BE-01 — Derive `θ_challenge` from the cost model

**Related findings:** M-020
**Priority:** Medium (blocks FIX-BE-02, so scheduled early)
**Files:** `eval/report.py` (line 26 + the Block-2 renderer at ~line 298), `eval/d6.py`
(`_block2_negative_controls` imports `THETA_CHALLENGE`)
**Symbols:** `eval/report.py::THETA_CHALLENGE`, `eval/cost.py::CostModel.tier_ladder`,
`eval/d6.py::_block2_negative_controls`

**Current behavior.** `THETA_CHALLENGE = 0.257`, a hand-typed rounded copy. The cost model
derives `1800 / (1800 + 5200) = 0.2571428571428571`. The constant is rounded **down**, making
the threshold marginally more permissive than the model implies. All 28 Block-2 cells are
computed at it.

**Required behavior.** The threshold is read from `load_cost_model().tier_ladder()["challenge"]`
— unrounded — at every consumption site, and is emitted into the artifact as
`block2_theta_challenge` so the frontend can display it without duplicating it.

**Root cause.** RC-2. `CostModel.tier_ladder()` already returns exactly this value, documented
"UNROUNDED — callers round for display, never for comparison". The constant violates its own
module's stated discipline, and contradicts App Flow §2's argument for cutting the D5 threshold
UI ("thresholds are θ_T = C_FP(T)/(C_FP(T)+C_FN), arithmetic, not preference").

**Implementation approach.** Replace the module constant with a memoised accessor
`theta_challenge() -> float` returning `load_cost_model().tier_ladder()[COST_TIER]`. Keep the
name `THETA_CHALLENGE` as a deprecated module-level alias computed at import for one release so
no importer breaks. Update both call sites in `report.py` and the import in `d6.py`.

**Data flow.** `config/cost_model.yaml` → `CostModel.tier_ladder()` → `theta_challenge()` →
`_episode_and_attempt_fp(threshold=…)` → `block2_negative_controls[*]` + `block2_theta_challenge`
→ frontend label.

**Dependencies.** None. Do first.

**Tests.**
- MODIFY `tests/acceptance/test_cost_thresholds.py`: assert `theta_challenge()` equals
  `1800/(1800+5200)` to full float precision and that **no literal `0.257` remains** in
  `eval/` (source scan — legitimate use of a grep test: it asserts absence of a duplicate, not
  presence of a rendering).
- NEW `tests/acceptance/test_d6_artifact.py::test_theta_challenge_matches_cost_model`.

**Verification.** Run the safe regeneration (§17.3) into a scratch dir and **diff Block 2
against the committed artifact.** Any cell that changes means a score fell in
`[0.257, 0.2571428…)`. Record the diff in the implementation log — a change here is *expected
and correct*, but it must be observed, not assumed absent.

**Regression risk.** **Real.** Changing the threshold can move Block-2 FP counts. Mitigation:
the scratch-diff above makes any movement explicit before anything is committed. Also verify
`tests/acceptance/test_negative_controls_evaluated.py` and `test_nri_control_tripwire.py` still
pass — the latter is a tripwire specifically about NRI FP behaviour.

**Acceptance criteria.**
1. `grep -rn "0\.257" eval/` returns nothing.
2. `block2_theta_challenge == 0.2571428571428571` in the regenerated artifact.
3. Any Block-2 cell change vs. the committed artifact is enumerated and explained in the
   implementation log.

---

### FIX-BE-02 — Score negative controls with the model and B0

**Related findings:** M-007, M-017
**Priority:** High
**Files:** `eval/d6.py` (`_block2_negative_controls`), `eval/harness.py`
(`run_all` — to pass model scorers through)
**Symbols:** `eval/d6.py::_block2_negative_controls`, `eval/scorers.py::Layer1Scorer`,
`eval/scorers.py::B0RulesScorer`, `eval/report.py::_episode_and_attempt_fp`,
`eval/harness.py::HarnessRun`

**Current behavior.** The generator iterates a fixed list of four B3 sanity scorers. Neither
`l1-lgbm-v1` nor `rules-only-v0` appears in any of the 28 rows. A section titled
"Negative-control false positives", presented as the credibility exhibit for FP behaviour,
contains **zero information about the product's false positives.** All 28 cells are
analytically predetermined.

**Required behavior.** Each scenario carries **six** rows: `l1-lgbm-v1`, `rules-only-v0`, then
the four sanity scorers (retained, per the brief — they are the harness floor, not decoration).
Model and B0 rows are computed at `theta_challenge()` using the same
`_episode_and_attempt_fp` the sanity rows use, so denominators are identical and comparable.

**Root cause.** Backend gap. `run_all` evaluates negative splits with `sanity` only
(`harness.py:441-449`); `d6.py` mirrors that list.

**Implementation approach.**
1. `HarnessRun` gains `model_scorers: Dict[str, Tuple[str, object]]` (empty when no model
   bundle) so `d6.py` can reach the same scorer instances `run_all` built — **not** construct
   its own, which would risk a different `pi_s`.
2. `_block2_negative_controls` prepends model rows when `run.model_scorers` is non-empty.
3. **Feasibility is proven** (§2.3): all 7 scenario runs have feature-corpus rows, so neither
   scorer raises `KeyError`.
4. When the bundle is absent, emit the two rows as `Unavailable` envelopes with
   `reason: "harness run without --model-dir"`. **Never omit them silently** — omission is what
   produced M-007 in the first place.
5. Emit `episode_flagged: bool` alongside `episode_fp`/`episodes`, and
   `denominator_basis: "legitimate_attempts_only"`.

**Data flow.** corpus + `models/` → `Layer1Scorer`/`B0RulesScorer` → per-sample scores →
`_episode_and_attempt_fp(samples, scores, theta_challenge())` →
`block2_negative_controls.{scenario}[]` → Block-2 table → DOM.

**Dependencies.** FIX-BE-01 (threshold), FIX-BE-06 (schema).

**Tests.**
- NEW `tests/acceptance/test_d6_negative_controls_model_rows.py`: for every scenario, assert a
  row exists with `scorer == "l1-lgbm-v1"` and one with `"rules-only-v0"`; assert their
  `attempts` denominator **equals** the sanity rows' denominator for the same scenario
  (identical population); assert `episode_flagged` is a bool and consistent with
  `episode_fp > 0`.
- NEW: assert the model row's `attempt_fp <= attempts` and that `attempts` equals the count of
  `is_attack=False` samples in that scenario split — i.e. the denominator semantics are what
  the label claims.
- EXTEND `tests/acceptance/test_negative_controls_evaluated.py` for the new rows.

**Verification.** Regenerate to scratch; confirm 7 scenarios × 6 rows = 42 rows; hand-check one
scenario's model row against a direct scoring loop in a throwaway script.

**Regression risk.** Medium. `HarnessRun` is a frozen dataclass — adding a field with a default
is safe for all existing constructors. The `d6.py` import of scorers must stay a *local* import
to preserve the documented "eval/ stays free of lightgbm on the Day-4 path" property
(`harness.py:476-478`).

**Acceptance criteria.**
1. 42 rows in `block2_negative_controls`, 6 per scenario.
2. Model and B0 rows present for all 7 scenarios with a real numeric `attempt_fp`.
3. Sanity scorers still present and unchanged.
4. A model-less harness run emits `Unavailable` envelopes with a reason, and the suite passes.

---

### FIX-BE-03 — Complete Block 6: model row, B3 floor, per-tier baselines

**Related findings:** M-008, M-038
**Priority:** High
**Files:** `eval/d6.py` (`_block6_baselines`), `eval/harness.py` (`_baseline_summary`,
`BaselineSummary`)
**Symbols:** `eval/d6.py::_block6_baselines`, `eval/harness.py::_baseline_summary`,
`eval/harness.py::BaselineSummary`, `eval/metrics.py::operating_point`,
`eval/baselines.py::b1_decline_velocity`, `eval/baselines.py::B2BinConcentrationScorer`

**Current behavior.** Four rows: B0 recall (`n/a`), B0 AP, B1 TPR, B2 TPR. **No model row** —
the section named "Baseline comparison" has no subject. **No B3** — `sanity_recall_at_b1_fpr`
and `sanity_recall_at_b2_fpr` are in the artifact and unrendered. **Not per-tier**, though
App Flow §5 D6 #6 says "beside the model, **on every tier**".

**Required behavior.** `block6_baselines` carries `model` (same shape as `b0`), `b0`, `b1`,
`b2`, a re-homed `sanity_floor` under each of b1/b2, and a `per_tier` map giving each of
{model, b0, b1, b2} an operating point per tier.

**Root cause.** Backend gap for the model row and per-tier data; frontend gap for B3.
`_temporal_reports(run)["l1-lgbm-v1"]` is already in scope in `_block6_baselines` — the model
row is a five-line addition that was simply never written.

**Implementation approach.**
1. Model row: mirror the existing `b0` construction using `reports.get("l1-lgbm-v1")`.
2. B3: keep `sanity_recall_at_b1_fpr`/`…b2_fpr` at their current paths (compatibility) **and**
   add `b1.sanity_floor` / `b2.sanity_floor` carrying the same values wrapped in `Unavailable`
   envelopes, so `always_positive: null` finally carries its reason
   (`"unreachable: constant scorer has <=2 distinct ROC points"` — the exact branch in
   `metrics.py::recall_at_fpr:110`). This resolves M-038.
3. Per-tier: extend `_baseline_summary` to accept a tier filter and compute B1/B2 operating
   points over `[s for s in split.samples if s.episode_tier == tier or not s.is_attack]`.
   **Care:** B1 is bitemporal — it must be run over the *whole* timeline and then sliced, never
   re-run on a tier subset, or the 340 ms outcome-visibility discipline breaks. Compute once
   over `temporal_test`, then partition the resulting per-event scores by tier.

**Data flow.** `temporal_test` split → `_baseline_summary` (whole-timeline B1/B2) → tier
partition of scores → `operating_point` per tier → `block6_baselines.per_tier` → Block-6 table.

**Dependencies.** FIX-BE-06 (schema).

**Tests.**
- NEW `tests/acceptance/test_d6_block6_completeness.py`: assert `model`, `b0`, `b1`, `b2`
  present; assert `per_tier` has all four tiers × four series; assert `sanity_floor` present on
  b1 and b2 with an explicit reason on the `always_positive` null.
- NEW anti-regression: assert the **union** of per-tier B1 confusion-matrix counts equals the
  overall B1 confusion matrix (tp/fp/tn/fn each sum). This is the test that catches a
  re-run-per-tier bitemporal bug.
- EXTEND `tests/acceptance/test_baselines_single_source.py`.

**Verification.** Scratch regeneration; confirm B1 overall `tp=103, fp=1, tn=757, fn=1264`
still reproduces (the audit verified `103/(103+1264) = 0.0753475`), and that the per-tier
counts sum to it.

**Regression risk.** **Highest of the backend items.** B1's bitemporal correctness is protected
by `tests/acceptance/test_baselines_single_source.py` and the 340 ms gap test. The per-tier
slice must not re-invoke `b1_decline_velocity` per tier. The summed-counts test above is the
specific guard.

**Acceptance criteria.**
1. `block6_baselines.model.ap_raw` is a real number equal to the `l1-lgbm-v1` temporal_test AP.
2. Per-tier counts sum exactly to the overall counts for B1 and B2.
3. `always_positive` nulls carry a reason string.
4. `test_baselines_single_source.py` still passes unmodified.

---

### FIX-BE-04 — Add `ece_raw`, the ECE gap, and the prior-correction verdict

**Related findings:** M-010, M-036
**Priority:** High
**Files:** `eval/harness.py` (`_calibration_block::_regime`)
**Symbols:** `eval/harness.py::_calibration_block`, `eval/harness.py::_regime`,
`eval/metrics.py::ece`

**Current behavior.** `_regime` computes `brier_raw`, `brier_platt`, `brier_platt_prior`,
`ece_platt`, `ece_platt_prior`, `effective_n`. **There is no `ece_raw`**, so the spec's
`{raw, Platt, Platt+prior}` triple is incomplete for ECE. Eval Protocol §3.4 requires "Brier
for {raw, Platt, Platt + prior-correction}; **the ECE gap between them**."

**Required behavior.** `_regime` additionally returns `ece_raw`, computed with the **identical**
`metrics.ece(..., n_bins=n_bins, weights=w)` call the other two use, plus
`ece_gap_platt_prior_vs_platt = ece_platt - ece_platt_prior`. The block gains
`prior_correction_helped_at_pi1: bool` — Eval §3.4's own stated test ("If prior correction does
not improve ECE at π₁, it is broken and the test says so").

**Root cause.** Backend omission. `raw` is already in scope at `harness.py:272`
(`raw = [_sigmoid(m) for m in margins]`); only the `ece()` call is missing. One line.

**Implementation approach.** Inside `_regime`, add
`"ece_raw": ece(raw, labels, n_bins=n_bins, weights=w)`. `_regime` currently closes over `w`
and `platt_pc` only — `raw` is in the enclosing scope, so no signature change is needed. Then
at the block level compute the verdict from `pi1`'s two ECE values.

**Data flow.** margins → `sigmoid` → `raw` → `metrics.ece(weights=w1)` →
`block5_calibration.pi1.ece_raw` → Block-5 calibration section → DOM.

**Dependencies.** None. Can proceed in parallel with FIX-BE-01.

**Tests.**
- NEW `tests/acceptance/test_calibration.py::test_ece_raw_present_and_independently_recomputed`:
  recompute ECE from the artifact's own reliability bins is **not** possible for raw (the
  artifact only stores Platt+prior bins), so instead assert (a) `ece_raw` is present and in
  `[0,1]` at both regimes, and (b) a synthetic unit test on `metrics.ece` with hand-computed
  bins reproduces an exact expected value.
- NEW unit test with a 4-sample hand-computable example asserting `ece()` returns the exact
  weighted mean absolute gap.
- NEW: assert `prior_correction_helped_at_pi1` agrees with `ece_platt > ece_platt_prior` at π₁
  (currently 0.3955 → 0.2807, so `true`).

**Verification.** Scratch regeneration; confirm `ece_platt` and `ece_platt_prior` are
**byte-identical** to the committed artifact (proving the addition changed nothing), and that
`ece_raw` is new and plausible against `brier_raw` (0.1193 / 0.1403).

**Regression risk.** Very low — purely additive, and `metrics.ece` is unchanged.

**Acceptance criteria.**
1. `block5_calibration.pi0.ece_raw` and `pi1.ece_raw` present and numeric.
2. All four pre-existing calibration numbers unchanged to full precision.
3. `prior_correction_helped_at_pi1 == true` for the current artifact.

---

### FIX-BE-05 — Correct the CI mislabel and the `max_univariate_auc` misnomer; derive separability

**Related findings:** M-040, M-011, M-013
**Priority:** Medium
**Files:** `eval/load.py` (`_recall_json`), `eval/report.py` (`_fmt_recall`), `eval/d6.py`
(new `_augment_audit_block`)
**Symbols:** `eval/load.py::_recall_json`, `eval/report.py::_fmt_recall`,
`eval/d6.py::build_artifact`

**Current behavior.**
- `ci_low`/`ci_high` are Wilson intervals on the **achieved FPR** (`metrics.py:119` —
  `_wilson_interval(best_fp, n_neg)`), but `report.py::_fmt_recall:50` prints them as
  `95% CI` immediately after the **recall** value, and `BarRow.fmtCi` does the same in the UI.
  **Both are mislabels of the same underlying value.** The audit found only the frontend one.
- `max_univariate_auc` is the configured *threshold* (0.95); the real maximum is 0.9976.
- No two-sided discriminability measure exists anywhere.

**Required behavior.** The interval is labelled as what it is — a 95% Wilson interval on the
**achieved false-positive rate** — in both the markdown report and the UI. `block3_audit`
carries a correctly named `univariate_auc_threshold`, a real
`observed_max_univariate_auc`, and per-feature `separability`, `direction`,
`flagged_two_sided`.

**Root cause.** RC-3 (naming/encoding) and RC-4 (one-sided discriminability).

**Implementation approach.**
1. `_recall_json` emits `fpr_ci_low`/`fpr_ci_high` **and** `ci_basis: "wilson_on_achieved_fpr"`,
   retaining `ci_low`/`ci_high` as deprecated aliases.
2. `_fmt_recall` changes its label from `95% CI` to `95% CI on achieved FPR`.
3. **New** `eval/d6.py::_augment_audit_block(audit_block, ...)` — a pure function over
   `run.audit_block` that adds `separability = abs(auc - 0.5)` (or `None`),
   `direction = "inverted" if auc < 0.5 else "positive"` (or `None` when constant/None), and
   `flagged_two_sided = separability >= (threshold - 0.5) and not constant`. It also adds
   `univariate_auc_threshold` (copy of `max_univariate_auc`) and
   `observed_max_univariate_auc = max(auc for non-constant features)`.
   **`models/audit.json` is NOT modified and the model is NOT retrained.**
4. Reconcile the `>` / `>=` drift found in planning: `flagged_two_sided` uses `>=` to match the
   UI's long-standing boundary-inclusive reading and `config/features.yaml`'s "flag threshold"
   wording; document the deliberate choice in the function docstring and pin it with a test at
   exactly 0.95.

**Data flow.** `models/audit.json` → `run.audit_block` → `_augment_audit_block` (derive only)
→ `block3_audit` → `AuditBars` → DOM.

**Dependencies.** FIX-BE-06 (schema).

**Tests.**
- NEW `tests/acceptance/test_d6_audit_derivations.py`: `separability == abs(auc-0.5)` for all
  24; `card_seen_24h` (0.22475) has `direction == "inverted"` and
  `separability ≈ 0.27525`; `observed_max_univariate_auc ≈ 0.9975874` and is **not** 0.95;
  boundary test: a synthetic feature at exactly 0.95 is `flagged_two_sided == True`.
- MODIFY `tests/acceptance/test_discriminability_audit.py` to assert the derived fields agree
  with its independently recomputed AUCs.
- NEW: assert `models/audit.json` is byte-identical before and after a harness run
  (proves no retrain / no mutation).

**Verification.** Scratch regeneration + `sha256sum models/audit.json` unchanged.

**Regression risk.** Low. Purely derived, additive. The `_fmt_recall` label change alters
`eval/outputs/report.md` text — check no test asserts the old string.

**Acceptance criteria.**
1. `observed_max_univariate_auc != max_univariate_auc` in the regenerated artifact.
2. `models/audit.json` SHA unchanged.
3. `direction == "inverted"` for exactly `bin_hhi_5m` and `card_seen_24h`.

---

### FIX-BE-06 — Artifact schema, provenance and `generated_at`

**Related findings:** M-029, M-019 (enabling), schema gap
**Priority:** High (gates most other backend items)
**Files:** `eval/d6_schema.py` **(NEW)**, `eval/d6.py` (`_provenance`, `write_artifact`,
`SCHEMA_VERSION`), `eval/provenance.py` (reuse only)
**Symbols:** `eval/d6.py::SCHEMA_VERSION`, `eval/d6.py::_provenance`,
`eval/d6.py::write_artifact`, `eval/provenance.py::build_hash`, `::config_hash`

**Current behavior.** `schema_version: 1`, no validation anywhere — not at generation, not at
build, not at render. The artifact carries **no timestamp at all**; top-level keys are
`block1…block6, provenance, schema_version, tier_e`. There is no way from the page or the file
to learn how old the numbers are. `build_hash` covers HEAD + a dirty flag + two SHAs, so it
diverges silently.

**Required behavior.** `schema_version: 2`; `write_artifact` validates before writing and
**refuses to write an invalid artifact**; provenance carries `generated_at`,
`generation_command`, `head_at_generation`, `tree_dirty_at_generation`, `corpus_db_sha256`,
`model_files_sha256`.

**Root cause.** RC-3 plus an absent contract boundary.

**Implementation approach.** See §18 for the full schema design. `d6_schema.py` is
**stdlib-only** — a declarative spec (nested dicts of field → `{type, required, nullable}`) plus
a `validate(artifact) -> list[str]` walker. No `jsonschema` dependency: `eval/` is deliberately
dependency-clean (`metrics.py` docstring: "pure stdlib metrics, no new dependencies"), and
adding one for ~200 leaves is not warranted.

**Data flow.** `build_artifact()` → `validate()` → raise on error → `write_artifact` → disk.

**Dependencies.** None; **do this first** among the additive-field items so every later item
adds its fields to a live schema.

**Tests.** See §18.5 and §24.

**Verification.** §17.3 scratch regeneration; the validator must accept the regenerated file and
reject each of the five malformed fixtures.

**Regression risk.** Medium: a too-strict schema breaks generation. Mitigation — the validator
runs in **report-then-raise** mode with the full error list, and CI runs it against the
committed artifact before it is ever wired into `write_artifact`.

**Acceptance criteria.**
1. `validate(json.load(committed_artifact))` returns `[]` after the v1→v2 migration.
2. Each of the 5 malformed fixtures produces a specific, named error.
3. `generated_at` parses as ISO-8601 UTC.

---

## 10. Frontend Remediation Plan

The frontend work divides into **three foundation items** that everything else depends on, then
the per-block items (§11–§16), then architecture/UX/a11y (§19–§22).

---

### FIX-FE-01 — The artifact contract boundary (`d6Contract.js`)

**Related findings:** M-019, M-038, RC-3; enables every consumption fix
**Priority:** Critical
**Files:** `services/dashboard/src/lib/d6Contract.js` **(NEW)**
**Symbols (new):** `parseArtifact(raw)`, `ArtifactContractError`, `normaliseMetric(node)`,
`SUPPORTED_SCHEMA_VERSIONS`

**Current behavior.** `D6Metrics.jsx` dereferences the raw import directly:
`d6.provenance.build_hash?.slice(0,12)` (the `?.` guards the wrong level —
`provenance` absent throws), `Object.entries(d6.block2_negative_controls)`,
`d6.block3_audit.features || {}`, `b4.curve_pi0`, `b4.ribbon[0].curve`,
`d6.block6_baselines.b0`. **Five of six blocks throw on a malformed artifact**, and with no
error boundary React unmounts the entire dashboard.

**Required behavior.** One module owns artifact ingestion. It checks `schema_version`, validates
required structure, normalises the three "unknown" encodings into a single internal
`{ available, value, reason, detail }` shape, and throws a **typed** `ArtifactContractError`
carrying an actionable message. It never returns `0` for a missing value.

**Root cause.** RC-3 + no boundary. The audit's §12 table lists every unguarded dereference.

**Implementation approach.**
- `SUPPORTED_SCHEMA_VERSIONS = [1, 2]`. On an unsupported version, throw
  `ArtifactContractError("artifact schema_version N is not supported by this build (supports 1–2); regenerate with python -m eval.harness")`.
- `normaliseMetric` accepts: the rich `recall_at_target_fpr` object; an `Unavailable` envelope;
  a bare number; a bare `null`; an absent key. It returns the single internal shape, mapping
  `resolvable:false` → `{available:false, reason:"unresolvable", detail:{n_neg}}` and bare
  `null` → `{available:false, reason:"unspecified"}`.
- **Explicitly forbidden inside this module:** any `?? 0`, `|| 0`, or `Number(x) || 0`. A lint
  rule and a unit test enforce it.

**Data flow.** `import d6 from ".../d6.json"` → `parseArtifact(d6)` → view model → components.

**Dependencies.** FIX-BE-06 defines the shapes it parses (but v1 parsing must work first, so
this can start immediately against the current artifact).

**Tests.** `FE-T-CONTRACT-*` in §23.6 — 9 missing-value cases, 5 malformed fixtures, both
schema versions.

**Verification.** Feed the committed v1 artifact and the regenerated v2 artifact; both parse.
Feed each malformed fixture; each throws `ArtifactContractError` with a distinct message.

**Regression risk.** Low — new module, no existing behaviour depends on it until wired in.

**Acceptance criteria.**
1. No `|| 0` / `?? 0` anywhere in the module (lint + test).
2. All 9 missing-value cases produce `available:false` with a reason, never a number.
3. Unsupported `schema_version` throws, does not silently render.

---

### FIX-FE-02 — The number-formatting policy (`format.js`)

**Related findings:** M-014, M-033, and the inconsistent-precision issue in audit §18.2
**Priority:** High
**Files:** `services/dashboard/src/lib/format.js` **(NEW)**; all metric components consume it
**Symbols (new):** `inr(minorUnits)`, `ap()`, `auc()`, `rate()`, `fpr()`, `ece()`,
`prevalence()`, `count()`, `pct()`, `NA`

**Current behavior.** `CostCurve.jsx:16` uses
`` `₹${Math.round(minor/100).toLocaleString()}` `` — **no locale argument**, so the same
artifact renders `₹2,32,145` for an `en-IN` viewer and `₹232,145` for `en-US`. The headline
number differs between viewers of the same page. Precision is inconsistent across blocks:
3 dp in Blocks 1/3/6, 4 dp in Block 5, raw integers in Block 2.

**Required behavior.** One module, one policy, locale-independent for INR.

| Quantity | Precision | Rationale |
|---|---|---|
| AP, AUC, TPR, recall, precision | **3 dp** | matches existing Blocks 1/3/6; adequate at n≈2000 |
| FPR | **4 dp**, or `1.3e-3` notation below 1e-3 | the decision region lives at 1e-3 |
| ECE, Brier | **4 dp** | values reach 7e-4; 3 dp would round to 0.001 |
| prevalence | **3 dp** | |
| separability `\|AUC−0.5\|` | **3 dp** | |
| currency | **integer rupees**, `en-IN` grouping, pinned | M-014 |
| counts / denominators | integer, no grouping below 10 000 | |
| percentages | **1 dp** | |

`inr()` uses
`new Intl.NumberFormat("en-IN", {style:"currency", currency:"INR", maximumFractionDigits:0})`
constructed **once at module scope** with an explicit locale, so it is deterministic. A unit
test asserts `inr(23214508.206055675) === "₹2,32,145"` exactly — this is one of the mandatory
numeric tests.

**Root cause.** No formatting policy existed; each call site chose its own `toFixed`.

**Data flow.** view model → `format.*` → DOM text node.

**Dependencies.** None.

**Tests.** `FE-T-FMT-01..08` (§23.6), including the exact `₹2,32,145` assertion and a test that
the output is unchanged when `process.env.TZ` / the default locale is altered.

**Verification.** Run the JS suite under `LANG=en_US.UTF-8` and `LANG=en_IN.UTF-8`; identical
output.

**Regression risk.** Low.

**Acceptance criteria.**
1. `inr(23214508.206055675) === "₹2,32,145"` under any host locale.
2. No `toLocaleString()` without an explicit locale remains in `src/` (source scan).
3. No bare `.toFixed(` outside `format.js` (source scan).

---

### FIX-FE-03 — The view model and field-coverage contract (`metricsModel.js`)

**Related findings:** RC-1; enables M-001, M-002, M-006, M-009, M-010, M-022, M-038
**Priority:** Critical
**Files:** `services/dashboard/src/lib/metricsModel.js` **(NEW)**,
`services/dashboard/src/lib/d6FieldCoverage.js` **(NEW)**
**Symbols (new):** `buildMetricsModel(parsedArtifact)`, `FIELD_COVERAGE`

**Current behavior.** Field selection is scattered through JSX (`apMetric`, `recallMetric`,
inline `d6.block5_calibration` reads). 23 fields are dropped with no record that they exist.

**Required behavior.** A single pure function maps the parsed artifact to an explicit view model
consumed by every component. Alongside it, `d6FieldCoverage.js` declares **every artifact leaf
path** as either `RENDERED` or `OMITTED(reason)`. A test walks the real artifact and fails on
any leaf in neither set.

**This is the structural fix for RC-1** and the single most important anti-regression device in
the plan: it makes "a value was silently dropped" a permanent, automatic test failure rather
than something only an audit can find.

**Implementation approach.** `FIELD_COVERAGE` is a flat map of dotted paths with wildcards, e.g.

```
"block1_per_tier.*.*.ap_at_eval_prevalence": RENDERED,
"block1_per_tier.*.*.recall_at_target_fpr.ci_low": OMITTED("deprecated alias of fpr_ci_low (M-040)"),
"provenance.fixture_sha256":                 RENDERED_IN_METHODOLOGY_PANEL,
"provenance.calibrator_version":             RENDERED_IN_METHODOLOGY_PANEL,
```

The coverage test enumerates leaves of the actual committed artifact, matches each against the
map, and reports **both** directions: unlisted leaves (a field was added and forgotten) and
listed-but-absent paths (a field was removed and the map is stale).

**Data flow.** `parseArtifact` → `buildMetricsModel` → block components.

**Dependencies.** FIX-FE-01.

**Tests.** `FE-T-COVERAGE-01` (no unlisted leaf), `FE-T-COVERAGE-02` (no stale path),
`FE-T-COVERAGE-03` (every `OMITTED` carries a non-empty reason).

**Verification.** Add a throwaway field to a fixture artifact; the coverage test must fail.

**Regression risk.** The coverage test can become noisy if `OMITTED` is used as an escape hatch.
Mitigation: `FE-T-COVERAGE-03` requires a reason string, and code review treats a new `OMITTED`
as a decision requiring justification in `Decisions.md`.

**Acceptance criteria.**
1. Coverage test passes against the real artifact with **zero** unlisted leaves.
2. Deliberately adding a field to a test fixture fails the test.
3. Every `OMITTED` entry has a reason of ≥ 20 characters.

---

## 11. Block 1 Plan — Per-tier performance

### FIX-M-001 — AP is reported with its prevalence, and the comparable figure is the primary series

**Related findings:** M-001, M-009 (π_eval), M-015 (caption), M-016 (split label)
**Priority:** CRITICAL — fix first
**Files:** `services/dashboard/src/screens/D6Metrics.jsx` (Block1 removed),
`services/dashboard/src/components/metrics/Block1PerTier.jsx` **(NEW)**,
`services/dashboard/src/components/charts/BarRow.jsx` (gains a reference-marker prop),
`services/dashboard/src/lib/metricsModel.js`
**Symbols:** `apMetric` (deleted), `recallMetric`, `Block1`, `BarRow`

**Current behavior.** `apMetric = (tm) => ({ value: tm.ap_raw, resolvable: true })`. The UI
renders `ap_raw` alone as a 0–1 bar under the label "average precision (resolvable)". **No
prevalence is printed. `ap_at_eval_prevalence` is never read.** π_eval is never shown.

**Required behavior — the presentation decision.**

Eval Protocol §2.1 sets two rules, and they must be implemented as two *distinct* things:

> "**Cross-tier comparison uses `recall @ fixed FPR`** (default FPR = 0.001)… This is the
> headline table." · "**PR-AUC is reported within a tier, with that tier's prevalence printed
> beside it**, and every tier's eval set is resampled to a common evaluation prevalence
> (π_eval = 0.01, stated)… **Both the raw and resampled prevalence appear in the report.**"

**Therefore the primary comparable metric is `recall @ FPR 1e-3` — and it is unresolvable.**
This is the honest reading and the page must say it: the spec's designated cross-tier
comparator **cannot be resolved at these negative counts**, and that fact is itself a headline
finding, not a footnote.

The block is restructured into three explicitly labelled sub-sections:

| Sub-section | Series | Comparable across tiers? | Treatment |
|---|---|---|---|
| **1a. Cross-tier comparator (spec-designated)** | `recall @ FPR 1e-3`, model and B0 | — | **Unavailable at every tier.** One grouped explanation, not eight repeated captions (M-015, M-028) |
| **1b. Prevalence-normalised AP — π_eval = 0.01** | `ap_at_eval_prevalence`, model and B0 | **YES — this is the primary rendered comparable** | Bars, with the π_eval = 0.01 floor drawn as a reference marker |
| **1c. Within-tier AP at the tier's own prevalence** | `ap_raw` + `prevalence`, model and B0 | **NO — explicitly labelled "not comparable across tiers"** | Bars, with **each tier's own prevalence drawn as the reference marker on its own bar** |

**Why `ap_at_eval_prevalence` and not `ap_raw` is the primary rendered comparable:** §2.1
mandates resampling every tier to a common π_eval precisely so the numbers sit "on one footing".
`ap_raw`'s floor is the tier's own prevalence (0.433–0.731), so `ap_raw` is not comparable
between tiers by construction. `ap_at_eval_prevalence` shares a floor of 0.01 across all four.

**How the confusion the brief names is made impossible.** A reviewer must not be able to mistake
`0.789 at prevalence 0.731` for `0.789 at π_eval = 0.01`. Three independent devices:
1. The two AP series live in **separately headed sub-sections** with the prevalence in the
   heading (`AP at π_eval = 0.01` vs `AP at the tier's own prevalence`).
2. Every `ap_raw` row prints its tier's prevalence **in the row**, adjacent to the value.
3. Each bar carries a **reference marker at its trivial-classifier floor** — 0.01 in 1b, the
   tier prevalence in 1c. On `easy`, the 0.789 bar visibly sits just past a marker at 0.731;
   on `medium`, the 0.9782 bar sits far past a marker at 0.01. **The lift is visible as
   geometry.**

**Deliberately NOT done — and why.** The audit's finding table computes a "lift" column
(1.08× / 1.46× / …). This plan **does not mint a `lift` metric**, in either the artifact or the
UI. Reasons: (a) the brief says "Do not invent another metric"; (b) it is not in the Eval
Protocol; (c) a ratio of an AP to a prevalence is not a standard, defensible quantity and would
itself need conditions stating. The reference-marker geometry conveys the same information
without asserting a number the protocol does not define. **This is a deliberate deviation from
the audit's suggested fix and is recorded as such.**

**Root cause.** Frontend field selection (RC-1). The backend computes everything already:
`eval/metrics.py::ap_at_prevalence`, `eval/d6.py::_block1_per_tier`, `_tier_metrics_json`.

**Implementation approach.**
1. Delete `apMetric`; the view model exposes `tiers[tier] = {model, b0}` each with
   `recall`, `apRaw`, `apAtEvalPrevalence`, `prevalence`, `n`, `split`.
2. `BarRow` gains `referenceMarker={{ value, label }}` — a 1 px `--viz-threshold` rule at
   `value/max`, `aria-hidden`, with the numeric value exposed in the row's `aria-label`.
   (The same primitive `AuditBars` already uses for its 0.95 rule — one mechanism, two uses.)
3. Row value text: `0.789 · prevalence 0.731 · n=821` in 1c; `0.018 · π_eval 0.010` in 1b.
4. Per-tier split label (M-016) — see FIX-M-016 below.

**Data flow.**
`corpus+model → metrics.ap_at_prevalence(π=0.01) → block1_per_tier.{mv}.{tier}.ap_at_eval_prevalence
→ parseArtifact → buildMetricsModel → Block1PerTier → BarRow → DOM text + bar width + marker x`.

**Dependencies.** FIX-FE-01, FIX-FE-02, FIX-FE-03.

**Tests.** `FE-T-B1-01..12` (§23.6). Specifically:
- renders `0.018` for model/easy `ap_at_eval_prevalence` (exact, from the artifact).
- renders `0.789` **and** `0.731` in the same row for model/easy `ap_raw`.
- renders the string `π_eval` with the value `0.010` in the 1b heading.
- the reference marker's computed left offset equals `prevalence * 100` % within 0.01.
- **negative test:** the DOM contains no numeric rendering of any `resolvable:false` recall.

**Verification.** Browser at 1536×960: read the block and answer "on which tier is the model
barely better than trivial?" without opening the JSON. `easy` must be visibly at its floor.

**Regression risk.** The existing `recall` rows and their `resolvable:false` behaviour must be
untouched. `test_ui_contracts.py::TestD6Resolvability` is being replaced, so the JS suite must
carry the equivalent assertion **before** the Python test is removed (§26).

**Acceptance criteria.**
1. All four `ap_at_eval_prevalence` values render.
2. All four `prevalence` values render adjacent to their `ap_raw`.
3. `π_eval = 0.01` renders in the header and in the 1b sub-heading.
4. No recall value renders as a number.
5. The word "comparable" appears only on the 1b sub-section; 1c is explicitly marked not
   cross-tier comparable.

---

### FIX-M-002 — B0's per-tier AP renders beside the model, and the finding is stated

**Related findings:** M-002
**Priority:** CRITICAL
**Files:** `components/metrics/Block1PerTier.jsx` (NEW), `lib/metricsModel.js`
**Symbols:** `Block1PerTier`, `buildMetricsModel`

**Current behavior.** Block 1 renders B0's four **recall** bars — all `n/a`, therefore carrying
no information — and does not render B0's four **AP** values, which do. `b0.roc_auc = 0.9943`
is likewise present and unrendered.

**Required behavior.** Both AP sub-sections (1b and 1c) render **paired** model/B0 bars per
tier. The verdict is stated in prose above the block.

| Tier | model `ap_raw` | B0 `ap_raw` | winner |
|---|---:|---:|---|
| easy | 0.789 | **0.9998** | B0 |
| medium | 0.998 | **0.9987** | B0 |
| hard | 0.935 | **0.9815** | B0 |
| evasive | 0.814 | **0.9583** | B0 |

**The wording, cross-checked against the two governing sources.** Eval Protocol §8: *"If the
model only beats the naive baselines on the hard and evasive tiers, **that is the finding and
it gets stated in that form.**"* `Decisions.md` Decision 64 (Trade-off), verbatim:

> "with 6 of ~10 non-constant features removed and 14 constant `0.0` un-fed slots (Decision 43),
> the model runs on 4 live features… **It is weaker than B0 overall (temporal_test ROC-AUC
> 0.889 vs 0.994) and on easy, but competitive on medium (0.995) and decisively better on
> `hard`, where B0 fires 0/3 rules** (recall@1e-3 0.73 vs 0.13). Reported 'in exactly that form'
> (Eval Protocol §8). The excluded features can be reinstated once the store-relative quantile
> transforms land (Decision 16)."

The block's verdict copy is derived from that paragraph — same claims, product voice, no
internal IDs (M-032), no softening:

> **The rules baseline outperforms the learned model on average precision at every tier.**
> The model runs on 4 live features; 6 were removed by the discriminability audit as generator
> artifacts and 14 slots are un-fed. It is weaker than B0 overall (ROC-AUC 0.889 vs 0.994) and
> on easy, competitive on medium, and stronger on hard, where B0's rules do not fire. The
> excluded features can be reinstated when store-relative quantile transforms land.

Two constraints on this copy, both enforced by test: it must contain the phrase identifying B0
as the winner, and it must **not** be placed below the fold or in a collapsed panel.

**Root cause.** `Block1` calls `apMetric(model[t])` inside one `TIERS.map`; there is no
corresponding `apMetric(b0[t])` loop.

**Implementation approach.** Paired-bar rows: one row per tier containing two bars (model, B0)
sharing a scale, model first, B0 second, both `--viz-series` grey (UIUX §2.4 — no categorical
rainbow), distinguished by a solid/hatched fill and an inline label, exactly as CostCurve
distinguishes π₀/π₁ by dash rather than hue. `b0.roc_auc` and the model's ROC-AUC render in the
verdict line.

**Dependencies.** FIX-M-001.

**Tests.** `FE-T-B1-13..18`:
- all four B0 `ap_raw` values render (`0.9998`, `0.9987`, `0.9815`, `0.9583` at 3 dp →
  `1.000`/`0.999`/`0.982`/`0.958` — **assert the exact formatted strings**, and note `0.9998`
  formats to `1.000`, which the test pins deliberately so a precision change is caught).
- the verdict paragraph is present in the accessible text of the block.
- **fairness test:** the model bar and the B0 bar for the same tier use the same `max`, so bar
  widths are directly comparable — asserted by computing both widths from the DOM.

**Verification.** Browser: a reviewer reading only Block 1 must be able to say "B0 wins on all
four tiers".

**Regression risk.** None functional. The risk is *social* — a later change that reorders or
de-emphasises the B0 series. The verdict-text test and the equal-scale test guard it.

**Acceptance criteria.**
1. Eight AP bars (4 tiers × 2 series) in each of 1b and 1c.
2. The verdict names B0 as stronger at every tier.
3. Model and B0 bars for a tier share a scale (asserted numerically).

---

### FIX-M-016 — The evasive tier is labelled with its split

**Related findings:** M-016, M-009
**Priority:** Medium
**Files:** `eval/d6.py::_block1_per_tier` (emit `split`), `components/metrics/Block1PerTier.jsx`
**Current behavior.** `easy/medium/hard` come from `temporal_test` (821+701+603 = 2125 = the
whole split); `evasive`'s 390 samples come from the separate `tier_e` split. The UI says
nothing, and the split name is displayed nowhere.

**Required behavior.** Each tier row carries its split. The evasive row is labelled
**`tier_e — adversarial split`**. Per UIUX §6.13 the bar itself still gets **no special
treatment** — no red, no warning icon, no apology, "simply the fourth bar, at whatever height
it is". The label is metadata in the row, not a decoration on the bar.

**Implementation approach.** Backend: `_block1_per_tier` records `report.split_name` /
`te.split_name` per tier. Frontend: render as a small monospace suffix in the tier label
column; when a block's tiers do not all share one split, the block heading additionally reads
"3 tiers from temporal_test · 1 from tier_e".

**Tests.** `FE-T-B1-19`: the evasive row's accessible name contains `tier_e`; the easy row's
contains `temporal_test`; **and** the evasive bar's fill colour token equals the other three
(no special treatment) — a direct UIUX §6.13 conformance assertion.

**Acceptance criteria.** Split visible per tier; evasive bar styling identical to the others.

---

### FIX-M-015 / FIX-M-028 — Caption matches the render; the null state stops looking like a bar

**Related findings:** M-015, M-028, and audit §18.2
**Priority:** Medium
**Files:** `components/charts/BarRow.jsx`, `components/metrics/UnavailableGroup.jsx` **(NEW)**

**Current behavior.** The caption promises "the evasive bar… at whatever height it is" directly
above eight rows that draw **no bar at all**. Each unresolvable row keeps its full-width
`--tg-surface-2` rounded track, which reads pre-attentively as a **100% bar**, and repeats a
40-character caps-lock sentence eight times.

**Required behavior.**
- The caption describes what actually renders.
- The null state is **not bar-shaped**: replace the filled track with a **dashed 1 px baseline
  rule** spanning the column at 50 % height (a rule is not a magnitude), plus the muted label.
  A rule cannot be misread as a filled quantity.
- Eight identical explanations collapse into **one grouped statement** rendered once above the
  group: *"recall @ FPR 1e-3 is not resolvable on these splits — 221–316 negatives against the
  1 000 a 1e-3 false-positive rate requires. Per-tier negative counts are shown in each row."*
  The **denominator stays in every row** (`n_neg=221`) — the brief is explicit that it must not
  be hidden.

**Implementation approach.** `BarRow` gains an `unavailable` render branch that emits no track
element. `UnavailableGroup` wraps N rows sharing one reason and renders the reason once.

**Tests.** `FE-T-B1-20..23`: no element with a background fill token inside an unavailable row's
bar cell; the reason string appears exactly **once** for the group; `n_neg` appears in **every**
row; the caption contains no claim about a bar height.

**Acceptance criteria.** Zero filled rectangles in unavailable rows; one grouped reason; four
per-row denominators retained.

---

## 12. Block 2 Plan — Negative-control false positives

### FIX-M-007-FE — Render model and B0 FP rows; re-type the episode denominator

**Related findings:** M-007, M-017, M-024 (table semantics)
**Priority:** High
**Files:** `components/metrics/Block2NegativeControls.jsx` **(NEW)**, `lib/metricsModel.js`
**Backend counterpart:** FIX-BE-02

**Current behavior.** A 28-row table (7 scenarios × 4 sanity scorers), `scenario` rendered only
on the first row of each group via `{i === 0 ? scenario : ""}` — an **empty `<td>` used as a
visual rowspan**, so a screen reader announces 21 rows with no scenario. Every episode cell
reads `0/1` or `1/1`. `n=1` and `n=720` are typographically identical.

**Required behavior.**

| Column | Semantics | Treatment |
|---|---|---|
| scenario | grouping | real `rowSpan={6}` with `<th scope="row">` |
| scorer | series | `l1-lgbm-v1`, `rules-only-v0` first, then the four sanity scorers in a visually separated "harness floor" sub-group |
| **episode flagged** | **boolean** (structurally — §1(B)) | `yes` / `no`, **not** `0/1` |
| attempt FP | rate over **legitimate attempts only** | `n_fp / n_attempts`, with the denominator basis in the column header |
| power | statistical adequacy | explicit badge — see below |

**Underpowered-sample treatment.** The brief requires that `0/1` must not look statistically
equivalent to `0/720`. Three devices:
1. A **`n` column** rendered at full weight, never elided.
2. A **power badge** on rows where `n_attempts < 30`: `retry_storm` (n=5) and `shared_ip_legit`
   (n=1) carry `underpowered — n=5` / `single sample — n=1` in `--tg-text-mute`, and their
   attempt-FP **rate is not rendered as a percentage at all** (a percentage of 1 sample is
   meaningless). They render as a bare count: `0 of 1`.
3. A **Wilson interval** on the attempt-FP proportion for rows with `n >= 30`, reusing the
   project's existing convention. For `n < 30` the interval is suppressed and the badge shown
   instead — an interval on n=1 is `[0, 0.79]`, which is technically correct and practically
   noise.

**The `shared_ip_legit` note.** Eval Protocol §4/V4 calls this "the F14 case", conceptually the
most important FP trap, and it is evaluated on **one** legitimate attempt (60 of its 61 samples
are the attacker's — verified §2.3). The block must say this in one line, because a reader who
does not know it will over-read a `0 of 1`. **This is a genuine evaluation limitation being
disclosed, not a defect being fixed** — the corpus construction is what it is.

**Root cause.** Backend gap (rows) + presentational gap (denominator semantics, power).

**Implementation approach.** Semantic `<table>` with `<caption>`, `<th scope="col">` on all
headers, `<th scope="row" rowSpan>` for the scenario, `<tbody>` per scenario. θ_challenge from
`block2_theta_challenge` rendered in the caption (never hardcoded).

**Dependencies.** FIX-BE-01, FIX-BE-02, FIX-FE-01/02/03.

**Tests.** `FE-T-B2-01..10`:
- a row exists whose scorer cell is `l1-lgbm-v1` for every one of the 7 scenarios.
- `episode_flagged` renders as `yes`/`no`, and the string `0/1` appears **nowhere** in the block.
- `shared_ip_legit` renders `0 of 1` **and** a badge containing `single sample`.
- `flash_sale` renders `n = 720` and **does** carry an interval.
- `getByRole("table")` has an accessible name; the scenario cell has `rowspan="6"`;
  `queryAllByRole("cell", {name: ""})` returns zero empty grouping cells.
- the θ_challenge shown equals `block2_theta_challenge` to 6 dp.

**Verification.** Browser + screen-reader pass: every row announces its scenario.

**Regression risk.** The table grows from 28 to 42 rows — check the responsive strategy (§22)
handles it; this is the widest table on the page.

**Acceptance criteria.**
1. 42 rows, 6 per scenario, model and B0 first.
2. No `x/1` episode fraction anywhere.
3. n=1 and n=5 rows visually and semantically distinguished from n=720.
4. Sanity scorers retained and labelled as the harness floor.

---

## 13. Block 3 Plan — Discriminability audit

### FIX-M-013 — Rank and flag on |AUC − 0.5|; show direction separately

**Related findings:** M-013, M-012
**Priority:** Medium
**Files:** `components/charts/AuditBars.jsx` (rewritten), `lib/metricsModel.js`
**Backend counterpart:** FIX-BE-05 (`separability`, `direction`, `flagged_two_sided`)

**Current behavior.** `flagged = auc >= 0.95`, rows sorted by `auc` descending. `card_seen_24h`
at AUC 0.225 has separability 0.275 — **the third most discriminative non-excluded feature on
the split** — and renders as the weakest row on the page. A hypothetical feature at AUC 0.02
would be a near-perfect inverted discriminator, sort dead last with a 2 % bar, and never be
flagged — defeating the block's stated purpose.

**Required behavior.**
- **Sort** by `separability = |AUC − 0.5|` descending.
- **Bar length** encodes `separability` (0 → 0.5), not raw AUC. This is the honest encoding:
  the block's question is "how separable is this feature alone", and separability is that
  quantity.
- **Direction** is a separate, non-length channel: a small `↑`/`↓` glyph plus the word
  `inverted` for AUC < 0.5, with the raw AUC always printed as the numeric value so nothing is
  hidden.
- **Threshold** rendered at `0.45` on the separability scale (= `0.95 − 0.5`), read from
  `block3_audit.univariate_auc_threshold`, **never hardcoded** (M-012).
- **Flag** read from `flagged_two_sided` in the artifact — the frontend performs **no
  comparison of its own** (M-012, and the `>` / `>=` drift found in planning).

**Why bar-length = separability rather than AUC.** Under raw-AUC encoding, an inverted
near-perfect discriminator is drawn as a *short* bar, which is exactly backwards for a block
whose purpose is to surface suspiciously-separable features. Separability encoding makes both
tails long. The raw AUC remains printed on every row, so no information is lost and the
transformation is stated in the block's caption.

**Root cause.** RC-4 (one-sided model of a two-sided quantity) + RC-2 (duplicated threshold).

**Dependencies.** FIX-BE-05.

**Tests.** `FE-T-B3-01..08`:
- `card_seen_24h` renders above `bin_entropy_5m` in DOM order (0.275 > 0.211).
- `card_seen_24h` renders the text `0.225` **and** a direction indicator whose accessible text
  contains `inverted`.
- the threshold rule's left offset equals `(threshold − 0.5) / 0.5 * 100`%, derived from the
  artifact value, and a fixture with `univariate_auc_threshold: 0.90` moves it — the drift test.
- **no `0.95` literal in `AuditBars.jsx`** (source scan; legitimate absence assertion).
- every rendered `flagged` state equals the artifact's `flagged_two_sided` for all 24 features.

**Acceptance criteria.** Sorted by separability; both inverted features surfaced; threshold and
flag both read from the artifact; no hardcoded 0.95.

---

### FIX-M-006 — Un-fed constant features stop being presented as measurements

**Related findings:** M-006
**Priority:** High
**Files:** `components/charts/AuditBars.jsx`, `components/metrics/UnavailableGroup.jsx` (NEW)

**Current behavior.** `eval/metrics.py::roc_auc` resolves all-tied scores to exactly 0.5 by the
tie convention — mathematically correct. The artifact records `constant: true` and
`reason: "constant 0.0 -- un-fed slot, Decision 43"`. **`AuditBars` reads neither field.** All
14 render as `0.500` with a grey bar at exactly 50 % width, typographically and visually
identical to a genuine measurement. **Fourteen of twenty-four rows** in the block App Flow calls
"the most persuasive thing on the screen" are placeholders presented as measurements.

**Required behavior.** Three groups, in this order:

| Group | n | Treatment |
|---|---:|---|
| **Flagged — generator artifacts** | 6 | amber `--viz-flag`, bars, **one group header** reading `6 features excluded as probable generator artifacts`, then each feature's own `reason` from the artifact |
| **Measured** | 4 | grey bars, separability encoding, direction glyph |
| **Not fed — no measurement** | 14 | **no bars at all**, collapsed by default behind a disclosure showing the count, with the shared reason stated once and each feature's `reason` available on expand |

The 14 render with **no bar**, exactly as `BarRow` already does for unresolvable recall — the
same null-state primitive, one mechanism for one concept.

**M-006 is the direct instance of the brief's rule** "a mathematically undefined metric must not
silently become zero" — here it silently becomes 0.500.

**The repeated-label problem (audit §18.2).** `FLAGGED — GENERATOR ARTIFACT` is currently
absolutely positioned at `top: -15px`, so each of six labels sits in the previous row's space —
six repetitions of the same 27-character string in one column. Replaced by a single group
header; per-feature justification comes from the artifact's own `reason`, which is more
informative and never repeats.

**Root cause.** RC-1 — `AuditBars` maps only `univariate_auc` and `excluded`; `constant` and
`reason` are dropped. Note `test_discriminability_audit.py` explicitly asserts every excluded
feature *has* a reason: **the backend contract is enforced, the frontend contract is not.**

**Dependencies.** FIX-FE-03.

**Tests.** `FE-T-B3-09..16`:
- the 14 constant features render **zero** bar elements (query for the fill element returns 0).
- the string `0.500` appears **zero** times in the block.
- each of the 6 flagged features renders its own distinct `reason` text.
- the group header states the count `14`.
- **negative test:** a fixture where a constant feature has `univariate_auc: 0.5` must not
  produce a 50 %-width element.

**Verification.** Browser: the block must read as "6 excluded, 4 measured, 14 not fed", not as
24 measurements.

**Regression risk.** UIUX §6.13 mandates amber-flag styling and the `FLAGGED — GENERATOR
ARTIFACT` annotation. Moving it to a group header is a **deviation** — justified because the
spec did not anticipate six simultaneous flags stacking into the rows above. Record in
`Decisions.md`. The amber token and the "measurement suspect" meaning are preserved.

**Acceptance criteria.** No bar and no `0.500` for any constant feature; reasons rendered;
three labelled groups.

---

### FIX-M-025 — The feature-name column stops overlapping the bar

**Related findings:** M-025, M-035
**Priority:** Medium
**Files:** `components/charts/AuditBars.jsx`

**Current behavior.** `gridTemplateColumns: "200px 1fr 64px"`.
`store_decline_rate_deviation_sigma` measures **235 px** at 11 px IBM Plex Mono in a **200 px**
cell with `overflow: visible`, `white-space: normal` and no break opportunity in an
underscore-joined token, so **23 px of text sits on top of the bar** at the default 1536 px
desktop width.

**Required behavior.** `minmax(clamp(160px, 22ch, 260px), max-content) 1fr 72px`, plus
`overflow-wrap: anywhere` and `word-break: break-word` so underscore tokens can break, plus a
`title` attribute carrying the full name. Combined with the §22 container widening (M-035
removes the 900 px cap), the longest name fits without truncation at ≥1280 px.

**Tests.** Playwright at all four viewports: the feature-name element's right edge is strictly
less than the bar track's left edge for **all 24 rows** — a computed-geometry assertion, not a
screenshot.

**Acceptance criteria.** Zero overlap at 1536/1280/768/390 px.

---

## 14. Block 4 Plan — Cost curves

This is the largest single piece of work. The audit is unambiguous that the data is exact and
the geometry is unusable.

### 14.1 What the data actually is (measured, not assumed)

`curve_pi0`, all 10 hull vertices, from the committed artifact:

| # | FPR | TPR | cost (minor) |
|---:|---:|---:|---:|
| 0 | 0.0 | 0.0 | 52 000 |
| 1 | **0.0** | **0.46891** | **27 616.68** ← cost-optimal **and** F1-optimal |
| 2 | 0.0013193 | 0.49744 | 49 856.09 |
| 3 | 0.1754617 | 0.76591 | 3 167 325.68 |
| 4 | 0.3456464 | 0.91002 | 6 220 093.11 |
| 5 | 0.5092348 | 0.96416 | 9 158 924.62 |
| 6 | 0.6517150 | 0.97805 | 11 720 281.03 |
| 7 | 0.8733509 | 0.99854 | 15 704 672.39 |
| 8 | 0.9986807 | 1.0 | 17 958 277.04 |
| 9 | 1.0 | 1.0 | 17 982 000 |

Four properties drive the design, and every one of them defeats the current chart:

1. **The interesting region is `FPR ≤ 0.0013` — 0.13 % of a linear [0,1] axis.** Vertices 0–2
   occupy 0.5 px of horizontal space in the current 360 px plot.
2. **Two distinct hull vertices sit at exactly `FPR = 0.0`** (rows 0 and 1). No FPR-axis
   transformation can separate them — they are genuinely a vertical segment. **The optimum
   really is at FPR = 0.** So M-004 cannot be fixed by moving the marker; it must be fixed by
   *inset* and by drawing a **point** rather than a full-height line identical to the y-axis.
3. **Dynamic range within `curve_pi0` alone is 651×** (27 617 → 17 982 000). A shared linear
   y-axis destroys the minimum even before `curve_pi1` (which peaks at ≈46 800 000, a further
   ~900× against π₀'s minimum) is added.
4. **All costs are strictly positive** (min 27 616.68). **A log y-axis is therefore safe** — no
   zero, no negative, no symlog needed on y.

### 14.2 The chosen approach, and why

**Three panels + an operating-point table.** Not one chart.

| Panel | Domain | Scales | Answers |
|---|---|---|---|
| **A — Decision region, π₀** | FPR ∈ [0, `decision_region_fpr_max`] (≈0.002) | x linear (inset), **y log** | "Where should we operate, and what does it cost?" |
| **B — Full range, π₀ (context)** | FPR ∈ [0, 1] | x linear, **y log** | "What does the whole curve look like, and where is Panel A in it?" — Panel A's window drawn as a shaded band |
| **C — Full range, π₁** | FPR ∈ [0, 1] | x linear, **y log, its own scale** | "Under attack, where does the optimum move to, and what is the saving?" |
| **Table** | — | — | The exact numbers, and the chart's accessible data alternative |

**Why these and not the alternatives:**

| Alternative | Verdict |
|---|---|
| Bigger chart | **Rejected** — the brief forbids it and 0.13 % of a 4× wider axis is still 0.5 % |
| Shared linear y | **Rejected** — this is the defect (M-003) |
| Log x | **Rejected** — `FPR = 0.0` is a real, and the *optimal*, data point; log cannot represent it |
| Symlog x | **Considered, rejected** — it would work, but a symlog axis needs its `linthresh` explained to the reader, and it still cannot separate the two vertices at exactly 0. Focus+context achieves the same legibility with an axis a payments reviewer reads without instruction |
| Two y-axes on one plot | **Rejected** — dual-axis plots invite false visual correlation between two quantities that share no scale |
| Rank/index x-axis | **Rejected** — distorts the data by discarding the metric meaning of FPR |
| **Per-regime panels + log y + decision-region focus** | **Chosen** — every value preserved, every transform disclosed on its axis, the minimum visible, the regimes never falsely compared on one scale |

**Log scale is a disclosed monotone transform, not a distortion.** Each y-axis is labelled
`expected cost, ₹ per 10 000 attempts (log scale)` and carries decade ticks. The underlying
values are unchanged and are printed exactly in the table.

### 14.3 FIX-M-003 / FIX-M-004 / FIX-M-034 / FIX-M-037 — Rebuild `CostCurve`

**Related findings:** M-003, M-004, M-034, M-037, M-021, M-014
**Priority:** High
**Files:** `services/dashboard/src/components/charts/CostCurve.jsx` (rewritten),
`services/dashboard/src/components/charts/costCurveGeometry.js` **(NEW — pure, testable)**,
`services/dashboard/src/components/metrics/OperatingPointTable.jsx` **(NEW)**
**Symbols:** `CostCurve`, `rupees` (deleted → `format.inr`), new
`buildPanelGeometry({curve, xDomain, yDomain, size})`, `ribbonEnvelope(ribbon)`,
`markerLayout(points)`

**Current behavior.**
- `maxCost` spans `curve_pi0 ∪ curve_pi1 ∪ ribbon`; one linear y-axis. The cost-optimal minimum
  renders **0.12 px above the x-axis**; all three decision-relevant points sit within 0.107 px
  vertically and 0.5 px horizontally.
- `cox = f1x = M.left = 64`, so the marker `<line x1=64 y1=16 x2=64 y2=220>` is
  **byte-identical to the y-axis line** emitted four lines earlier. `coincident` suppresses
  F1-optimal's *line* but **still renders its text label**, so two labels stack in the top-left
  corner pointing at what looks like a tinted y-axis.
- The rotated y-axis label is clipped at the top of the viewBox.
- The chart never states its series (`l1-lgbm-v1`), tier (`challenge`) or split
  (`temporal_test`), all of which are in `block4_cost`.
- `π₀=0.001 · π₁=0.9` is a hardcoded string (M-021).
- `rupees()` uses locale-free `toLocaleString()` (M-014).

**Required behavior.** As §14.2. Specifically for markers:

- Each optimum is a **filled circle marker** (r=4) with a short leader line and a callout placed
  by a simple collision-avoidance pass (`markerLayout`), **not** a full-height rule.
- The x-scale carries an **8 px inset** so `FPR = 0` maps clear of the y-axis line; the axis
  still carries an explicit `0` tick. This is disclosed layout inset, not data transformation.
- **Coincident optima → exactly one marker and one label**, reading
  `cost-optimal = F1-optimal · FPR 0.0000 · TPR 0.469 · ₹276`, driven by
  `block4_cost.optima_coincident` from the backend (**not** a `Math.abs(f1x-cox) < 1` pixel
  comparison, which is a rendering coincidence masquerading as a fact).
- The y-axis label is **horizontal, above the axis**, not rotated at the viewBox edge (M-034).
- A subtitle states `series l1-lgbm-v1 · tier challenge · split temporal_test`, read from the
  artifact (M-037).
- π₀/π₁ values in every label come from `block4_cost.pi0`/`pi1` (M-021).

**Root cause.** RC-4 and RC-2.

**Dependencies.** FIX-BE-06 (`optima_coincident`, `ribbon_envelope`,
`decision_region_fpr_max`), FIX-FE-02 (`inr`).

**Tests.** `FE-T-B4-*` — geometry, not screenshots (§23.6). Highlights:
- **Marker/axis separation:** the cost-optimal marker's `cx` is **≥ 6 px** from the y-axis
  line's `x1`. This is the direct M-004 regression test.
- **Minimum visibility:** the vertical distance between the y-pixel of the minimum cost and the
  y-pixel of the maximum cost in Panel A is **≥ 40 px**. Direct M-003 test.
- **Label collision:** for every pair of rendered `<text>` callouts, bounding boxes computed
  from `x`, `y`, `font-size` and text length **do not intersect**. Direct M-004/M-034 test.
- **No clipping:** every `<text>` element's computed bounding box lies within the `viewBox`.
- **Exactly one optimum marker** when `optima_coincident` is true; **exactly two** in a fixture
  where it is false.
- **Headline value:** the block renders the exact string `₹2,32,145` (§23.5).

**Verification.** Browser at all four viewports; a reviewer must be able to point at the minimum.

**Regression risk.** High — this is a full rewrite of the most spec-constrained component.
UIUX §6.13 mandates "two lines, same colour, solid = steady state, dashed = under attack, each
labelled inline at its right terminus" and "the rupee gap set between them". Panels B and C
preserve the solid/dashed, same-colour, right-terminus-label treatment. **The "rupee gap set
between them" instruction is unsatisfiable** — the two optima coincide, so there is no
"between". This is recorded as a spec deviation forced by the data, with the coincidence stated
explicitly instead (see FIX-M-039).

**Acceptance criteria.**
1. The cost-optimal point is visually identifiable and ≥ 6 px from the y-axis.
2. Panel A's minimum is ≥ 40 px from its maximum.
3. Zero overlapping text callouts; zero text outside the viewBox.
4. Series/tier/split/units all stated; π values read from the artifact.
5. `₹2,32,145` renders under any host locale.

---

### FIX-M-005 — A mathematically valid sensitivity ribbon

**Related findings:** M-005
**Priority:** High
**Files:** `eval/d6.py::_block4_cost` (emit `ribbon_envelope`),
`components/charts/costCurveGeometry.js` (NEW, `ribbonEnvelope`)

**Current behavior.** The path is `lo` forward + `hi` reversed + `Z`, where `lo` is the
π = 1e-4 curve and `hi` is π = 1e-2. **These two curves cross.** At FPR = 0 the FN term
dominates and `hi` is above `lo`; at FPR = 1 the FP term dominates and `lo` is above `hi`. The
sign flips at ≈FPR 0.30, producing a **self-intersecting bowtie polygon** filled under the
default `nonzero` rule — a shape with no defined meaning. Maximum thickness anywhere is 2.24 px
in a 204 px plot.

**Required behavior.** A true **per-x envelope** across *all* ribbon π values:

```
for each hull index i:
    lo_i = min(cost(pi, i) for pi in ribbon_pis)     # ribbon_pis = (1e-4, 1e-3, 1e-2)
    hi_i = max(cost(pi, i) for pi in ribbon_pis)
```

All three ribbon curves share the same hull x-coordinates (`_curve` maps the same
`hull_points`), so per-index min/max is well defined and `hi_i >= lo_i` **by construction** —
the polygon cannot self-intersect. Emitted from the backend as
`block4_cost.ribbon_envelope = [[fpr, lo, hi], …]` so the frontend does no envelope arithmetic.

**Placement.** The ribbon is drawn on **Panel A and Panel B only** (the π₀ panels). π₀ = 0.001
lies inside [1e-4, 1e-2]; π₁ = 0.9 does not, so drawing the band on Panel C would imply a
sensitivity range that does not contain that panel's prevalence. **The current chart draws it
across a single shared plot containing both regimes — a second, unreported correctness issue.**

**Extent.** On a log y-axis over the decision region the band has real vertical extent (the
π = 1e-4 and π = 1e-2 costs at the optimum differ by orders of magnitude), which resolves the
2.24 px invisibility without any styling change.

**Tests.** `FE-T-B4-RIBBON-01..04`:
- **Geometric validity:** `hi_i >= lo_i` for every i (backend test on the artifact).
- **Simple polygon:** the rendered path's forward and reverse edge sets contain **no crossing
  pair** — a segment-intersection check over the emitted path `d`. This is the explicit test the
  brief requires proving the polygon is valid.
- **Non-degenerate:** the band's maximum pixel thickness in Panel A is **≥ 8 px**.
- **Not on Panel C:** Panel C contains no element with `fill: var(--viz-ribbon)`.

**Acceptance criteria.** Envelope emitted by the backend; rendered polygon proven simple by
test; band visible; not drawn on the π₁ panel.

---

### FIX-M-039 — The ₹0 gap is stated as structural, not empirical

**Related findings:** M-039
**Priority:** Low
**Files:** `eval/d6.py::_block4_cost`, `components/charts/CostCurve.jsx`

**Current behavior.** `₹0` is presented as an empirical finding. In fact at π₀ = 0.001 precision
≈ 1.0 only at FPR = 0, so F1-argmax and cost-argmin coincide **almost by construction** (F1
falls from 0.638 at FPR = 0 to 0.353 at the next hull vertex).

**Required behavior.** The backend emits `rupee_gap_is_structural: true` plus a
`rupee_gap_note`, and the UI states it:

> At a steady-state prevalence of 0.001, precision collapses away from FPR = 0, so the
> F1-optimal and cost-optimal operating points coincide. The ₹0 gap is a structural consequence
> of that prevalence, not a coincidence of this model.

**Implementation.** In `_block4_cost`, set the flag when `f1_optimal` and `cost_optimal` are the
same hull vertex, and compute the F1 at the next vertex to substantiate the note.

**Tests.** Backend: flag is `true` for the current artifact and the note is non-empty. Frontend:
the block's text contains "structural" and the `₹0` figure is not presented without it.

**Acceptance criteria.** The ₹0 headline never appears without its structural explanation.

---

## 15. Block 5 Plan — Calibration

### FIX-M-010 — The complete calibration section

**Related findings:** M-010, M-036, M-021, M-022
**Priority:** High
**Files:** `components/metrics/Block5Calibration.jsx` **(NEW)**,
`components/charts/ReliabilityDiagram.jsx` **(NEW)**, `lib/metricsModel.js`
**Backend counterpart:** FIX-BE-04

**Current behavior.** A 2×4 table: Brier Platt, Brier Platt+prior, ECE Platt, ECE Platt+prior.
The values shown are correct — the audit recomputed both ECE figures from the artifact's own
reliability bins and matched to 10 decimal places. What is missing:

| Required by App Flow §5 D6 #5 / Eval §3.4 | Status |
|---|---|
| Brier {Platt, Platt+prior} | ✅ shown |
| **Brier {raw}** | ❌ `brier_raw` = 0.1193 / 0.1403 **in the artifact, discarded** |
| **ECE {raw}** | ❌ **never computed** |
| **Reliability diagram, both regimes** | ❌ 2 × 10 bins **fully computed and discarded** |
| ECE gap / verdict | ❌ neither computed nor stated |

Plus: no units, no direction ("lower is better"), no threshold; `ECE 0.3955` is styled
identically to `ECE 0.0007`; the regime labels `π₀ = 0.001 (steady state)` are **hardcoded
strings** (M-021).

**Required behavior — the section design.** Not "another table". Three parts:

**5a — The verdict, first.** One sentence, derived from
`prior_correction_helped_at_pi1`, answering Eval §3.4's own stated test:

> **Prior correction works at both regimes.** At the under-attack prevalence π₁ = 0.9 it reduces
> expected calibration error from 0.3955 to 0.2807. Eval Protocol §3.4 makes this the pass
> condition: if prior correction did not improve ECE at π₁, the calibrator would be broken.

with the failing variant pre-written and selected by the flag, so the page states the true
result either way. Direction is stated once, prominently: **lower is better for both Brier and
ECE**.

**5b — The 2 × 6 metric table.** Rows = regimes (labels read from `block4_cost.pi0`/`pi1`, not
hardcoded). Columns = `Brier raw · Brier Platt · Brier Platt+prior · ECE raw · ECE Platt ·
ECE Platt+prior`. Each regime row carries `n = 2125`, `effective_n` (759.5 at π₀ / 1650.9 at
π₁), and `raw_prevalence = 0.6433` — because a reweighted metric on an effective sample of 759.5
against a nominal 2125 is a materially different claim (M-022). The best value in each metric
family is marked with a subtle indicator; **magnitude is encoded** (a small inline bar) so
0.3955 and 0.0007 are not typographically identical (M-036).

**5c — Reliability diagrams, both regimes, side by side.** The canonical calibration
visualisation, named first by the spec, currently discarded. A scatter of
(`mean_predicted`, `observed_rate`) per bin against the y = x identity line, with **point area
proportional to bin `weight`** — essential here, because at π₀ bin 0 carries weight 2124.04 of
2125 and the other nine carry ≈1 in total. Without weight encoding, nine near-empty bins would
dominate the picture and misrepresent the calibration. **Empty bins** (`mean_predicted: null`,
weight 0 — 6 of the 20) are **omitted from the plot and their count stated**, never plotted at
the origin.

**Root cause.** Frontend discard (RC-1) for brier_raw and the diagrams; a genuine backend gap
for `ece_raw`.

**Dependencies.** FIX-BE-04, FIX-FE-01/02/03.

**Tests.** `FE-T-B5-01..12`:
- renders `0.1193` (`brier_raw` at π₀) and `0.1403` (π₁).
- renders `ece_raw` for both regimes from a fixture with known values.
- renders `0.0703`/`0.0007` (π₀ ECE Platt / Platt+prior) and `0.3955`/`0.2807` (π₁) — exact
  formatted strings at 4 dp.
- the verdict text contains `0.3955` and `0.2807` and the word `reduces`.
- a fixture with `prior_correction_helped_at_pi1: false` renders the failing verdict, and the
  word `reduces` does **not** appear.
- the reliability diagram renders **4** points at π₀ (10 bins − 6 empty across both regimes;
  exact per-regime count asserted from the fixture) and the empty-bin count is stated in text.
- point radius is a monotone function of `weight` (asserted over the rendered `r` values).
- regime labels contain `0.001`/`0.9` sourced from the artifact — a fixture with
  `pi0: 0.002` changes the label (the M-021 drift test).

**Verification.** Browser: a reviewer must be able to answer "did calibration help, and at which
regime?" from 5a alone.

**Regression risk.** Low. All four currently-displayed values must remain byte-identical —
asserted directly.

**Acceptance criteria.**
1. Raw, Platt and Platt+prior columns present for both Brier and ECE.
2. Both reliability diagrams render with weight-proportional points and no empty bins plotted.
3. The verdict states the π₁ result and the direction convention.
4. `effective_n` and `n` both shown.
5. No hardcoded π literal remains in the block.

---

## 16. Block 6 Plan — Baseline comparison

### FIX-M-008 — A baseline comparison that has a subject

**Related findings:** M-008, M-038, M-026, M-002 (companion)
**Priority:** High
**Files:** `components/metrics/Block6Baselines.jsx` **(NEW)**, `lib/metricsModel.js`
**Backend counterpart:** FIX-BE-03

**Current behavior.** Four rows: `B0 — live rules` (recall `n/a`), `B0 — average precision`,
`B1 — decline-velocity`, `B2 — BIN-concentration`. **Three failures:** no model row (the section
named "Baseline comparison" has no subject); no B3 sanity floor, though
`sanity_recall_at_b1_fpr` and `sanity_recall_at_b2_fpr` are in the artifact; and not per-tier,
though App Flow §5 D6 #6 requires "beside the model, **on every tier**". Separately, the B0 row's
value text `recall n/a · n_neg=758` overflows the 168 px value column and wraps, giving that row
36 px against ~22 px for its neighbours (M-026).

**Required behavior.** A comparison matrix that answers "what does the model do compared with
the baselines?" without the reviewer reconstructing it:

| | model `l1-lgbm-v1` | B0 rules | B1 decline-velocity | B2 BIN-concentration | B3 sanity floor |
|---|---|---|---|---|---|
| **Overall** — AP, ROC-AUC, recall@1e-3 | ✅ new | ✅ | ✅ (TPR at its own operating point) | ✅ | ✅ new |
| **Per tier** ×4 | ✅ new | ✅ new | ✅ new | ✅ new | — |

with three caveats preserved verbatim in meaning:

1. **B1** — *"needs completed outcomes the pre-auth path never has at decision time."* The audit
   verified this caption accurate against `eval/baselines.py` (B1 requires
   `outcome_visible_ms = t_ms + 340 ms`). **Preserved.**
2. **B2** — *"shares R3's statistic, so B0 already contains it."* Verified accurate: B2 issues
   the identical `WindowRequest` to `compute.py:203`. **Preserved, and the phrasing must
   continue to make clear B2's contribution is not independent of B0's** — Eval §8 requires this
   explicitly. A test asserts the text contains both "B0" and a non-independence claim.
3. **B0 vs B1 are never reported as one** (Eval §8). Separate rows, separate captions.
   **Preserved.**

**B3 / M-038.** `sanity_recall_at_*.always_positive` is `null` — correct per `recall_at_fpr`'s
"unreachable" branch, because a constant scorer has ≤ 2 distinct ROC points. It currently has no
reason field and is never rendered, so its display behaviour is untested. FIX-BE-03 attaches the
reason; the UI renders `unreachable — constant scorer has no intermediate operating point`, not
`n/a` and certainly not `0`.

**M-026 (wrapping).** Value text moves to a two-line cell structure (value on line 1, qualifier
on line 2) inside a fixed-height row, so `recall n/a` and `n_neg=758` no longer compete for one
168 px line. Row heights become uniform by construction.

**Root cause.** Backend for the model row and per-tier; frontend for B3; layout for M-026.

**Dependencies.** FIX-BE-03, FIX-FE-01/02/03.

**Tests.** `FE-T-B6-01..12`:
- a row whose label contains `l1-lgbm-v1` exists and renders a numeric AP.
- B3 renders for both b1 and b2 anchors; `always_positive` renders its reason text and **no
  number**.
- `0.075` (B1 TPR) and `0.718` (B2 TPR) render exactly — the audit verified these as
  `103/(103+1264)` and `982/(982+385)`.
- B0 AP renders `0.997`.
- the B2 caption contains `B0` and a non-independence statement (Eval §8 conformance).
- **uniform row height:** every row's `offsetHeight` is equal (the M-026 regression test).
- per-tier: 4 tiers × 4 series = 16 cells present.

**Verification.** Browser: a reviewer must answer "how does the model compare to B0/B1/B2/B3?"
from this block alone, and it must agree with Block 1's verdict.

**Regression risk.** Medium. The B1/B2 captions are verified-accurate prose; rewording risks
breaking a claim the audit confirmed true. Mitigation: the caption text is treated as **fixed
copy**, moved verbatim, with only the internal-ID cleanup of M-032 applied.

**Acceptance criteria.**
1. A model row exists with real numbers.
2. B3 sanity floor rendered with reasons for its nulls.
3. Per-tier comparison present for all four tiers.
4. B1 and B2 caveats preserved; B2's non-independence explicit.
5. All rows equal height.

---

## 17. Provenance / Staleness Plan

### 17.1 What is true today (evidence, not assumption)

| Check | Artifact | Recomputed today | Verdict |
|---|---|---|---|
| `config_hash` | `a7db8c6118…` | `a7db8c6118…` | ✅ **MATCH** — configs unchanged since generation |
| `fixture_sha256` | `5672a0e683…` | `5672a0e683…` | ✅ **MATCH** |
| `build_hash` | `9141a8ecc4…` | `36d0cc4817…` | ❌ **DIVERGED** |
| `generated_at` | **absent** | — | ❌ no timestamp exists at all |
| corpus / model identity | **not recorded** | — | ❌ **UNVERIFIABLE from the file** |

`build_hash` covers `git rev-parse HEAD` + a dirty flag + the baseline-profile SHA + the fixture
SHA (`eval/provenance.py:93-101`). HEAD has moved and the tree is dirty, so divergence is
*expected* and the artifact is correctly labelled with its generation build. **The defect is
presentational plus a genuine gap:** the header prints `build 9141a8ecc41b` with no temporal
qualifier, and the file records neither when it was generated nor against which corpus or model.

### 17.2 FIX-M-029 — Provenance completeness and honest staleness disclosure

**Related findings:** M-029, M-009, M-022
**Priority:** High
**Files:** `eval/d6.py::_provenance`, `components/metrics/ProvenanceHeader.jsx` **(NEW)**,
`components/metrics/MethodologyPanel.jsx` **(NEW)**

**Required behavior — the six Eval §9 attributes, always visible.** Eval Protocol §9 is
verbatim: *"Every reported figure carries, in the artifact itself: `seed`, `config_hash`,
`model_version`, `policy_version`, `π_eval`, and the split name. **A number that cannot state
those six things does not go on a slide.**"* All six render in the page header. Three are
currently missing (`policy_version` = 1, `eval_prevalence` = 0.01, split name) and **all three
are already in the artifact.**

**Split, specifically.** The split name is **not global** — Block 1 mixes `temporal_test` and
`tier_e`. The header states the primary split and a per-block/per-row split label appears
wherever a block differs (FIX-M-016). A test asserts that no block renders without a split
attribution reachable from it.

**Single-seed disclosure (M-022).** `seeds_used = 1` renders in the header, and the Methodology
panel states that every figure is a single-seed point estimate. Values printed to 3–4 decimals
with no interval imply a precision one seed cannot support; saying so once, prominently, is the
honest fix. `effective_n` appears in Block 5 (FIX-M-010).

**Staleness disclosure — the design.** The artifact is an intentionally committed snapshot
(`.gitignore:28` carries `!eval/outputs/d6.json` deliberately, and `test_d6_artifact.py` guards
that exception). The UI must therefore **not** claim the numbers describe the current tree, and
must **not** cry stale merely because HEAD moved. Three states, computed at build time by a Vite
`define` that injects the *current* `config_hash` and HEAD:

| State | Condition | UI |
|---|---|---|
| **Snapshot, configs match** | artifact `config_hash` == current | `evaluation snapshot · generated 2026-08-30 20:11 UTC · configs unchanged since` — neutral |
| **Configs changed** | artifact `config_hash` != current | **prominent warning:** `configs have changed since this evaluation was generated — regenerate before relying on these numbers`, with both hashes shown |
| **Unknown** | current hash unavailable (e.g. a bare production build) | `snapshot; freshness not verifiable in this build` — never a false "current" |

**`build_hash` divergence alone is deliberately NOT treated as staleness.** HEAD moves on every
commit and the tree is nearly always dirty during development; a warning that is always on is a
warning nobody reads. `config_hash` + the new corpus/model SHAs are the signals that actually
imply the numbers moved. `build_hash` and `head_at_generation` are shown in the Methodology
panel as identity, not as an alarm. **This is a deliberate deviation from a naive reading of
M-029 and is justified here so it is not "fixed" back later.**

**Implementation approach.** `_provenance` gains `generated_at` (UTC ISO-8601),
`generation_command` (`" ".join(sys.argv)`), `head_at_generation`, `tree_dirty_at_generation`,
`corpus_db_sha256` (streamed SHA-256 of the `--corpus-db` file), and `model_files_sha256`
(`{name: sha256}` over `models/*.json` and `*.txt`). All reuse `hashlib`; `eval/provenance.py`
already has `_sha_file_first_token` for the fixture pattern.

**Tests.**
- Backend: `generated_at` parses as ISO-8601 UTC and is within a plausible range;
  `corpus_db_sha256` matches a directly computed SHA of the corpus file.
- Frontend `FE-T-PROV-01..08`: all six Eval §9 attributes render; `seeds_used` renders;
  a fixture with a mismatched `config_hash` renders the warning state and one with a matching
  hash does not; the `unknown` state never renders the word "current".

**Acceptance criteria.**
1. Six Eval §9 attributes visible without interaction.
2. `generated_at` present and rendered as a human date.
3. Config-mismatch fixture produces a visible warning; matching fixture does not.
4. The page never asserts the artifact reflects the current tree.

### 17.3 Safe regeneration and the verification of corpus provenance

**This closes the audit's §5.5 UNVERIFIED item.** The audit could not verify that the committed
artifact reflects `data/corpus/tollgate.db` + `models/l1-lgbm-v1` because regenerating would
overwrite `eval/outputs/d6.json`. **`eval/harness.py:496` already provides the escape:**

```bash
# 1. Back up, belt and braces (the --out flag alone is sufficient, but this is free)
cp eval/outputs/d6.json /tmp/d6.committed.json

# 2. Regenerate into a scratch directory. NOTHING under eval/outputs/ is touched.
python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db \
    --model-dir models \
    --out "$SCRATCH/d6-verify"

# 3. Structural diff, ignoring fields that MUST differ
python scripts/diff_d6.py \
    eval/outputs/d6.json "$SCRATCH/d6-verify/d6.json" \
    --ignore provenance.build_hash \
    --ignore provenance.generated_at \
    --ignore provenance.head_at_generation \
    --ignore provenance.tree_dirty_at_generation
```

`scripts/diff_d6.py` is **NEW** — a leaf-wise structural diff with float tolerance, reporting
added / removed / changed paths. It is small, reusable for every later verification, and is the
tool that makes each backend change's blast radius observable before anything is committed.

**Interpretation of the Phase-0 baseline run** (performed *before* any code change):

| Result | Meaning | Action |
|---|---|---|
| Only ignored fields differ | **The committed artifact is verified** against the current corpus, model and configs. The audit's J-class unknown is closed. | Record the evidence in the implementation log; proceed |
| Other fields differ | The committed artifact is **genuinely stale**. | **Stop and report the exact diff.** Do not silently regenerate. Whether to re-commit is the user's call — it changes published numbers |

**Rules that hold for the whole implementation:**
1. `python -m eval.harness` is **never** run without `--out` pointing outside `eval/outputs/`
   until the final, deliberate regeneration step.
2. Every backend change is followed by a scratch regeneration + `diff_d6.py` against the
   committed artifact, and the diff is **explained** before proceeding. An unexplained changed
   value is a bug, not a refresh.
3. The committed artifact is replaced **exactly once**, at the end of Phase 1, as an explicit
   reviewed step (§28), with the full diff attached.
4. A pytest marker `@pytest.mark.regen` guards any test that would invoke the harness, and it is
   excluded from the default run so no test run can ever overwrite the artifact.

---

## 18. Schema Validation Plan

### 18.1 Why a schema, and why a hand-rolled one

The artifact is the **entire contract** between a Python evaluation harness and a React page —
`schema_version: 1`, ~200 leaf fields, **zero validation anywhere**: not at generation, not at
build, not at render. `test_d6_artifact.py` checks presence and non-emptiness of 6 blocks and 8
provenance fields; it validates no types, no nullability, no leaf.

**No `jsonschema` dependency.** `eval/` is deliberately dependency-clean —
`eval/metrics.py`'s docstring opens "pure stdlib metrics, no new dependencies", and
`pyproject.toml` keeps even LightGBM out of the base install so the rules-only fallback runs
without a compiled dependency. A declarative spec plus a ~120-line walker in
`eval/d6_schema.py` **(NEW)** costs less than the dependency and reads better in review.

### 18.2 Schema shape

```python
# eval/d6_schema.py  (NEW) -- illustrative shape, not final code
NUM   = FieldSpec(type=float, nullable=False)
NUM_N = FieldSpec(type=float, nullable=True)          # explicit null is legal
UNAVAILABLE = FieldSpec(shape={                        # the RC-3 envelope
    "value": NUM_N, "available": BOOL, "reason": STR_N,
})
RECALL = FieldSpec(shape={                             # the existing rich object, unchanged
    "value": NUM_N, "n_neg": INT, "resolvable": BOOL,
    "ci_low": NUM_N, "ci_high": NUM_N,                 # deprecated aliases, still required at v2
    "fpr_ci_low": NUM_N, "fpr_ci_high": NUM_N,
    "ci_basis": STR,
})
```

The spec declares, per leaf: **type · required · nullable · the "unknown" encoding in use ·
the schema version that introduced it**. Wildcards (`block1_per_tier.*.*`) cover the
model-version and tier dimensions.

### 18.3 Where validation runs — three boundaries

| Boundary | When | Behaviour on failure |
|---|---|---|
| **Generation** — `eval/d6.py::write_artifact` | every harness run | **Raise; do not write.** An invalid artifact never reaches disk |
| **CI / contract test** — `tests/acceptance/test_d6_schema.py` **(NEW)** | every pytest run | Fail with the full list of violations |
| **Render** — `services/dashboard/src/lib/d6Contract.js` | module init at build time | Throw `ArtifactContractError`, caught by `MetricsErrorBoundary` (§19.3) |

The frontend validator is **structural, not exhaustive** — it checks `schema_version`, the
presence of the six blocks plus provenance, and the shape of anything it dereferences. Full
leaf validation is the backend's job; duplicating it in JS would recreate RC-2.

### 18.4 The field-coverage contract (the RC-1 remedy)

Distinct from the schema, and the more important of the two. The schema answers *"is the
artifact well-formed?"*; coverage answers *"does the UI actually use it?"* — which is the
question that would have caught all 23 discarded values.

`services/dashboard/src/lib/d6FieldCoverage.js` **(NEW)** maps every leaf path to
`RENDERED` | `RENDERED_IN_METHODOLOGY_PANEL` | `OMITTED(reason)`. The test walks the **real
committed artifact** and fails on:
- a leaf present in the artifact and absent from the map (a field was added and forgotten);
- a path in the map and absent from the artifact (the map is stale);
- an `OMITTED` entry with a reason shorter than 20 characters (escape-hatch abuse).

### 18.5 Malformed-artifact fixtures

`services/dashboard/src/__fixtures__/` **(NEW)** — derived programmatically from the real
artifact at test time, **never by editing `eval/outputs/d6.json`**:

| Fixture | Construction | Expected behaviour |
|---|---|---|
| `missingProvenance` | `delete a.provenance` | `ArtifactContractError` naming `provenance`; boundary renders; rest of app alive |
| `missingBlock` | `delete a.block3_audit` | error names `block3_audit` |
| `malformedCurve` | `a.block4_cost.curve_pi0 = []` | error names `curve_pi0`; **no NaN reaches the DOM** |
| `missingCalibration` | `delete a.block5_calibration.pi0` | Block 5 renders "not measured in this artifact" (the existing correct guard, preserved) |
| `wrongSchemaVersion` | `a.schema_version = 99` | error names the version and the regeneration command |
| `explicitNulls` | set several leaves to `null` | rendered as unavailable-with-reason, **never `0`** |
| `v1Artifact` | the current committed file | parses; v2-only sections show "requires artifact v2" |

**Tests.** `FE-T-ERR-01..07`, one per fixture, each asserting (a) the specific error identity,
(b) that the surrounding application still renders, (c) that no `0`, `0.000` or `NaN` appears in
the Metrics region.

**Acceptance criteria.** Schema validates the real artifact; each fixture produces a distinct,
named failure; no fixture blanks the app; the coverage test passes with zero unlisted leaves.

---

## 19. Routing / Architecture Plan

### 19.1 FIX-M-018 — Hash routing, deep links, document title, nav semantics

**Related findings:** M-018, M-024 (aria-current)
**Priority:** Medium
**Files:** `services/dashboard/src/App.jsx`, `services/dashboard/src/hooks/useHashRoute.js`
**(NEW)**, `services/dashboard/index.html`
**Symbols:** `App`, `NAV`, `useState("live")` → `useHashRoute()`

**Current behavior.** `const [route, setRoute] = useState("live")` — no router. Verified in the
browser: clicking **Metrics** leaves the URL at `http://localhost:5174/`; refresh returns to
**Live**; back/forward do nothing; `document.title` stays `Tollgate — Live Monitor`
(`index.html:5`) on the Metrics page; nav buttons carry no `aria-current`. The evaluation page —
the one App Flow calls "the track's stated bar" and the one most likely to be linked to a
reviewer — is not addressable.

**Required behavior.** `#/live`, `#/incident`, `#/metrics`. Refresh preserves the route. Back and
forward work. `document.title` follows the route. `aria-current="page"` on the active nav item.

**Chosen approach: a ~30-line `useHashRoute` hook. No router dependency.**

Justified by repository evidence, not preference: UIUX §10's Day-1 exclusion list names
"no router" explicitly; `tokens.css` records the same discipline for CSS frameworks; there are
**three** routes with no params, no nesting and no guards. `react-router-dom` would add a
dependency and a mental model for a three-entry switch. Hash routing additionally needs **no
dev-server or production rewrite rules**, which matters because the dashboard is served by
`vite` in the demo and history-API routing would 404 on a direct load.

```
useHashRoute()
  -> reads location.hash, normalises to a known route id (unknown -> "live")
  -> subscribes to "hashchange"
  -> returns [route, navigate]  (navigate sets location.hash)
  -> a useEffect sets document.title from a ROUTE_TITLES map
```

**Tests.** `FE-T-ROUTE-01..06`: `#/metrics` renders D6 on first paint; an unknown hash falls back
to live **without throwing**; `hashchange` switches route; `document.title` becomes
`Tollgate — Metrics & Evaluation`; the active nav item has `aria-current="page"` and the others
do not. Playwright: load `http://localhost:5174/#/metrics` directly, reload, assert D6 still
renders; press Back and assert the previous route returns.

**Regression risk.** Low; D1/D3 render identically. Any existing deep-link-free bookmark
(`http://localhost:5174/`) still lands on Live.

**Acceptance criteria.** Direct load, refresh and back/forward all work for `#/metrics`; title
correct; `aria-current` present.

### 19.2 FIX-M-031 — Isolate live subscriptions from the static Metrics route

**Related findings:** M-031
**Priority:** Medium
**Files:** `services/dashboard/src/App.jsx`, `services/dashboard/src/components/LiveShell.jsx`
**(NEW)**
**Symbols:** `App`, `useEventStream`, `useReplayStatus`, `useIncidents`, `StreamRail`,
`ThreatBand`, `SystemBanner`, `DemoControlStrip`

**Current behavior.** `App.jsx:48-52` calls all three hooks **unconditionally, before the route
switch**. While Metrics is displayed the app keeps an `EventSource` open and polls
`/v1/replay/status`; the audit observed one `/v1/stream/recent` fetch during a 5-second idle
dwell. Every incoming event re-renders `App` and with it D6's 24-row audit and the inline SVG.
This contradicts App Flow §5 D6's "Static render. No live computation on stage." at the screen
level, even though `D6Metrics` itself is genuinely static.

**Required behavior.** The three hooks move into `LiveShell`, mounted only for `live` and
`incident`. On `#/metrics` no `EventSource` is opened and no polling timer is armed. React
unmounts `LiveShell` on navigation, and the existing hooks' cleanup closes the connection.

**The spec tension, stated plainly.** UIUX §11 open decision 2 resolves "Stream Rail on **every
screen**… it is what stops the app feeling like separate pages", and App Flow §5 D0 puts the
rail, threat band and banner on every screen. Suspending the subscription removes the rail's
data source on Metrics.

**Recommended resolution** (carried to §32 as an open question, with a default so implementation
is not blocked): on the Metrics route, render the Stream Rail in the **static snapshot form it
already supports** — `StreamRail.jsx` guards on `matchMedia("prefers-reduced-motion")` and
renders a static snapshot, so the code path exists. The threat band renders its last-known state
with an explicit `as of <time>` qualifier. **The Demo Control Strip is hidden on Metrics** — it
is a live-control affordance (`TIER / SPEED / Launch / Stop / Reset`) on a static evaluation
report, and showing controls that act on a system the current screen does not display is worse
than the spec deviation. The shell's visual continuity is preserved; only the live data path is
suspended.

**Tests.** `FE-T-ARCH-01..04`: with a mocked `EventSource` constructor, rendering `#/metrics`
constructs **zero** instances; navigating live → metrics calls `close()` on the open instance;
no `setInterval` remains armed (fake timers); the Demo Control Strip is absent on `#/metrics`
and present on `#/live`. Playwright: 10-second idle dwell on `#/metrics` records **zero**
network requests.

**Regression risk.** Medium — the run-id reset signal (`AUDIT-015`, documented in `App.jsx:31`)
flows from `useReplayStatus` and every event-derived surface reinitialises on it. Unmounting
`LiveShell` discards the event buffer, so returning to `#/live` re-fetches
`/v1/stream/recent` and re-subscribes. That is correct behaviour but changes the observed
buffer contents across a navigation round-trip; `tests/acceptance/test_demo_lifecycle.py` and
`test_sse.py` must be checked.

**Acceptance criteria.** Zero network requests during a 10 s dwell on Metrics; `EventSource`
closed on navigation; live routes unchanged.

### 19.3 FIX-M-019 — Error boundary and graceful failure

**Related findings:** M-019
**Priority:** Medium
**Files:** `services/dashboard/src/components/MetricsErrorBoundary.jsx` **(NEW)**,
`services/dashboard/src/App.jsx`

**Current behavior.** `grep` for `componentDidCatch|ErrorBoundary|getDerivedStateFromError`
across `services/dashboard/src` returns **no matches**. Five of six blocks dereference artifact
fields with no guard. Any one throws during render and, with no boundary, React unmounts the
**entire application** — the whole dashboard blanks, not just the Metrics section. Only `Block5`
guards (`if (!cb || !cb.pi0) return …`) and `tier_e` (`|| {}`).

**Required behavior.** A class error boundary wrapping **only the Metrics route content**, so a
bad artifact degrades one screen and never the shell. The fallback is actionable, not an
apology:

> **The evaluation artifact could not be read.**
> `eval/outputs/d6.json` declares `schema_version 99`; this build supports 1–2.
> Regenerate it with:
> `python -m eval.harness --split all --seed 42 --corpus-db data/corpus/tollgate.db --model-dir models`

Per UIUX §8 ("Errors say what happened and what to do. They don't apologise").

**Development vs production.** In dev (`import.meta.env.DEV`) the boundary additionally renders
the stack and the offending path. In production it renders the message and the regeneration
command but not the stack. **It never swallows the error** — `componentDidCatch` always
`console.error`s the original, so the failure remains visible to anyone with a console. "Do not
hide real errors" is satisfied by *always* logging and *always* naming the cause.

**Placement.** Around the Metrics route only. **Not** a global boundary: a global one would mask
genuine failures in D1/D3, whose live data paths have their own error states
(`SSE: …` in the nav, `listError` in D3).

**Tests.** `FE-T-ERR-01..07` (§18.5), plus: a component that throws inside the Metrics subtree
leaves the nav and Stream Rail mounted; `console.error` is called with the original error.

**Acceptance criteria.** Every malformed fixture renders the fallback with a specific cause; the
shell survives; the original error is always logged.

---

## 20. UI / UX Redesign Plan

### 20.1 What is preserved

The audit's §18.1 identifies genuine strengths. These are **design assets, not incidental**, and
the redesign is constrained by them:

- The restrained dark palette and real design tokens (`tokens.css`, transcribed from UIUX §2.2/§2.4).
- Grey-by-default series colour; **amber reserved for exactly one meaning**, and that meaning
  stated (UIUX §6.13 — "the only place in the product where amber is not threat state").
- Tabular figures (`.tg-num`) preventing digit reflow — UIUX §3.4 calls this "the single
  highest-leverage detail in the spec".
- The `resolvable:false` treatment: no bar, muted text, in-track explanation. **The audit calls
  it "exemplary" and "the behaviour the rest of the page should be measured against."**
- Clean heading hierarchy; the six-block argument order (App Flow §5 D6 orders the blocks "as
  the argument should be delivered").
- `prefers-reduced-motion` support (`base.css:28`).
- The sticky bottom strip's 36 px clearance at maximum scroll — measured, no occlusion.

### 20.2 Information hierarchy — the chosen structure

The brief proposes a 9-section structure. **This plan keeps App Flow §5 D6's six-block order
instead**, for a documented reason: App Flow states the blocks are ordered "as the argument
should be delivered", and the audit confirms the current order is correct and legible. Reordering
would break a spec conformance the page currently passes (audit §10: "Six blocks in argument
order — ✅ PASS") to satisfy a generic template.

What is added is a **layer above** the six blocks, which is what the brief is actually reaching
for:

```
┌─ Page header ─────────────────────────────────────────────────┐
│  Metrics & Evaluation                                          │
│  Eval §9 identity line: seed · config · model · policy ·       │
│  π_eval · split    +   snapshot freshness state (§17.2)        │
├─ Executive summary  (NEW) ────────────────────────────────────┤
│  4–6 sentences answering, in order:                            │
│   • what was measured, on which split, at what prevalence      │
│   • how the model compares with B0  (the M-002 verdict)        │
│   • which headline metric is unavailable and why (recall@1e-3) │
│   • what the cost analysis concludes                           │
│   • what calibration did                                       │
│   • the two standing caveats (single seed; 4 live features)    │
├─ 1. Per-tier performance      (§11)                            │
├─ 2. Negative-control false positives  (§12)                    │
├─ 3. Discriminability audit    (§13)                            │
├─ 4. Cost curves               (§14)                            │
├─ 5. Calibration               (§15)                            │
├─ 6. Baseline comparison       (§16)                            │
├─ Tier E footer (retained, extended with the unrendered fields) │
└─ Methodology & provenance  (NEW, expandable) ─────────────────┘
```

**The executive summary is the single highest-leverage addition.** It is what lets a reviewer
answer the brief's success-condition questions without reading source. It is **generated from
the artifact**, not hand-written prose: each sentence is a template with artifact values
substituted, so it **cannot drift** from the numbers below it. A test asserts every number in
the summary matches the corresponding artifact field.

Critically, the summary is where the M-002 finding lands first: **the reader learns that B0
beats the model before they see any bar.** That is the opposite of the current page, and it is
what "its job is not to make the model look good" means in layout terms.

### 20.3 The Methodology panel

Expandable, collapsed by default, holding what belongs on the page but not in the argument:
`build_hash`, `head_at_generation`, `fixture_sha256`, `calibrator_version`, `corpus_db_sha256`,
`model_files_sha256`, `generation_command`, `seeds_used`, `base_seed`, `n_bins`, `pi_t`,
`raw_prevalence`, the `tier_e` converged parameters not currently shown (`distinct_cards` 286,
`episode_duration_s` 704, `amount_quantile_band` [0, 26]), and the split composition table.

This is how the **G-class "intentional omission"** values stop being omissions: they are
present, addressable and testable, just not competing with the argument.

### 20.4 Copy corrections

| Finding | Current | Becomes |
|---|---|---|
| **M-032** | `(UIUX v2 SS6.13)`, `(Eval Protocol SS4/V2)` — note `SS` is a mangled `§` | **Removed from all user-facing copy.** Spec references move to source-code comments, where they belong and already exist |
| **M-033** | CSS uppercases `L1-LGBM-V1`, `BRIER PLATT` while the provenance line stays lowercase | `.tg-label`'s `text-transform: uppercase` is **not applied to identifiers**. Model versions render exactly as the artifact spells them (`l1-lgbm-v1`) — they are identifiers, not labels |
| **M-036** | ECE 0.3955 and 0.0007 in identical type, no units, no direction | Direction stated once per metric family; magnitude encoded inline (§15) |
| **M-015** | Caption promises bars that do not render | Rewritten to describe what renders (§11) |
| Repeated caps-lock | `NOT RESOLVABLE AT THESE NEGATIVE COUNTS` ×8; `FLAGGED — GENERATOR ARTIFACT` ×6 | One grouped statement each (§11, §13) |

**Voice conformance (UIUX §8).** All new copy follows "say what a number is conditional on" —
`₹2,32,145 saved per 10,000 attempts, at under-attack prevalence π₁ = 0.9`, never the bare
figure. A copy-review checklist item verifies every rendered quantity carries its condition.

### 20.5 Null / unavailable design

The current `n/a · n_neg=221` logic is preserved in substance and improved in form:

| Principle | Implementation |
|---|---|
| Communicate *"not measurable under this evaluation constraint"*, not *"the value is zero"* | Copy says "not resolvable at these negative counts"; **never** `0`, `0.000` or `—` alone |
| Never bar-shaped | Dashed rule, not a filled track (FIX-M-028) |
| Never hide the denominator | `n_neg=221` stays in **every** row |
| Group shared reasons | One statement above N rows sharing a cause (`UnavailableGroup`) |
| One visual language for all null states | The same primitive serves unresolvable recall, un-fed features, and model-unavailable rows — a reader learns it once |

Three distinct null semantics, three distinct renderings, all non-numeric:

| Semantic | Example | Rendering |
|---|---|---|
| **Unresolvable** (measured, cannot be resolved) | recall@1e-3, n_neg=221 | `not resolvable · n_neg=221` |
| **Unreachable** (undefined for this scorer) | `always_positive` sanity recall | `unreachable — constant scorer has no intermediate operating point` |
| **Unavailable** (not computed in this run) | model rows without `--model-dir` | `not computed — harness run without a model bundle` |

### 20.6 Number formatting, semantic colour, density

Formatting policy: §10 FIX-FE-02. Semantic colour is unchanged from tokens: grey `--viz-series`
by default, amber `--viz-flag` for "measurement suspect" only, indigo `--viz-threshold` for
operating thresholds and reference markers only. **No new hue is introduced** (UIUX §2.1: indigo
"and only indigo"; §9 forbids more than one accent hue).

Density: block spacing rises from `marginBottom: 28` to a token-based rhythm
(`--tg-space-8` between blocks, `--tg-space-4` within), and each block gains a hairline rule
above its heading so the six-part argument structure is visible at a glance.

---

## 21. Accessibility Plan

The audit measured every item below; each fix targets a measured failure, not a guess.

### 21.1 FIX-M-023 — Contrast

**Measured against the page background `rgb(11,13,16)`:**

| Class | Size | Colour | Ratio | AA |
|---|---|---|---:|---|
| `tg-caption` | 12 px | `rgb(110,120,133)` | **4.34** | ❌ |
| `tg-mono-caption` | 11 px | `rgb(110,120,133)` | **4.34** | ❌ |
| `tg-mono-data tg-num` | 13 px | `rgb(110,120,133)` | **4.34** | ❌ |
| SVG axis labels | 9 px | `rgb(110,120,133)` | **4.34** | ❌ |
| SVG optima labels | 9 px | `rgb(99,102,241)` | **4.36** | ❌ |
| `tg-label` / `tg-body` | 12/14 px | `rgb(167,176,188)` | 8.88 | ✅ |

**The `--tg-text-mute` token (`#6E7885`) is the single cause of all five failures**, and it is
applied to exactly the honesty-critical text — every caption, the provenance line, both axis
labels, and **every `n/a · n_neg=` value**. The muted styling meant to signal "this is a caveat"
pushes the caveat below legibility.

**Fix.** Lighten `--tg-text-mute` from `#6E7885` to **`#8B95A3`** (ratio ≈ **5.9:1**), a change
confined to `tokens.css`. This is a **token change affecting the whole dashboard**, not just D6 —
which is correct, since the failure is the token's, and it makes D1 and D3 compliant too. The
token keeps its role as the lowest step in the text hierarchy (`#F2F5F8` > `#A7B0BC` > `#8B95A3`),
so no visual hierarchy is lost.

SVG label sizes rise from `font-size="9"` to 11, and the optima label colour moves from
`--viz-threshold` (4.36:1) to `--tg-text` for the text with the indigo reserved for the marker.

**Tests.** A contrast unit test computing WCAG ratios from the token values for every
(foreground token, background token) pair the page uses, asserting **≥ 4.5:1** for all body and
caption roles. Runs in the JS suite — no browser needed, since the tokens are the source of
truth. Playwright verifies computed styles resolve to the expected tokens.

### 21.2 FIX-M-024 — Semantic structure

| Failure (measured) | Fix |
|---|---|
| **No `scope` on any of 9 `<th>`**, both tables | `scope="col"` on every column header; `scope="row"` + `<th>` for the scenario cell |
| **No `<caption>` on either table** | A real `<caption>` naming the table and its conditions (θ_challenge, denominator basis) |
| **Empty `<td>`s as a visual rowspan** — `{i === 0 ? scenario : ""}` — so a screen reader announces 21 of 28 rows with no scenario | Real `rowSpan={6}` on a single `<th scope="row">` |
| **32 bar rows are `<div>` grids**; label, bar and value are unassociated siblings with no `role` or `aria-label` | Each row becomes a `role="group"` with an `aria-label` composing label + value + condition, e.g. `"easy, average precision 0.789, at tier prevalence 0.731, n=821"`. The bar element itself is `aria-hidden` — it is a redundant visual encoding of text already present. **This is deliberately not `role="progressbar"`**: these are measurements, not progress |
| **SVG has `role="img"` + `aria-label` but no `<title>`/`<desc>`** and no tabular alternative | `<title>` + `<desc>` on every panel, plus the **operating-point table** (§14.2) which is the chart's genuine data alternative — real text, not a caption |
| **No `aria-current` on nav** — active state is colour + a 2 px border only | `aria-current="page"` (FIX-M-018) |
| **0 focusable elements in `<main>`** | The Methodology panel's disclosure and the Block-3 group disclosures are real `<button>`s, so the page has meaningful keyboard targets. Static content stays non-focusable — correct; a focus stop on a paragraph is noise |

**Screen-reader treatment of null values — explicitly designed, not incidental.** An
unavailable row's `aria-label` reads `"easy, recall at false-positive rate 1e-3: not resolvable,
221 negatives against the 1000 required"`. It must **never** read `"easy, 0"`. A test asserts no
unavailable row's accessible name matches `/\b0(\.0+)?\b/`.

**Tests.** `FE-T-A11Y-01..12` using Testing Library's role queries plus `axe-core` via
`vitest-axe`: zero violations on the full page render; `getByRole("table")` returns tables with
accessible names; every bar row is reachable by `getByRole("group", {name: /easy/})`; the null
accessible-name negative test above.

### 21.3 Keyboard and focus

`base.css:18-25` already implements UIUX §2.5's focus ring (`2px solid var(--tg-primary)` at
`2px` offset, never `outline: none`) — **preserved unchanged**. New interactive elements
(disclosures, nav) inherit it. Tab order follows DOM order; no focus traps; no `tabindex > 0`.

---

## 22. Responsive Design Plan

### 22.1 The measured problem

No `@media` query exists anywhere in `services/dashboard/src/styles/` except
`prefers-reduced-motion`. Layout is fixed-column at every width:
`gridTemplateColumns: "200px 1fr 168px"` (`BarRow`) and `"200px 1fr 64px"` (`AuditBars`), inside
a `maxWidth: 900` container.

| Container | Bar track | Table | Verdict |
|---:|---:|---:|---|
| 900 (default) | 508 px | 852 | ✅ intended |
| 768 | 432 px | 720 | ✅ |
| 600 | 264 px | 552 | ⚠️ cramped |
| 480 | **144 px** | 432 | ❌ a 0.5 bar is 72 px |
| **390** | **54 px** | **429 — overflows by 39** | ❌ **broken** |

At 390 px the 200 px label and 168 px value columns consume 368 px of a 342 px grid, so the
**data-bearing element is squeezed to 54 px while the chrome keeps full width** — exactly
backwards. The tables have **no `overflow-x` container**, so they overflow the document
horizontally. At 1536 px the opposite problem: `maxWidth: 900` leaves **~40 % of the viewport
empty** while Block 3's label column is simultaneously too narrow for its longest feature name
(M-035 + M-025 in the same row).

### 22.2 The strategy

**Fluid columns with intrinsic minimums, plus two breakpoints. Container-driven, not
device-driven.**

```css
/* metrics.css (NEW) -- the first real responsive layer in the dashboard */
.tg-metrics            { max-width: 1280px; margin-inline: auto; padding: var(--tg-space-6); }
.tg-metric-row         { display: grid; gap: var(--tg-space-3); align-items: center;
                         grid-template-columns:
                           minmax(9rem, 14rem)      /* label  - shrinks, never below 9rem */
                           minmax(6rem, 1fr)        /* bar    - always the flex element    */
                           minmax(7rem, max-content);/* value - sized to its content       */ }

@media (max-width: 768px) {                  /* tablet: value moves under the label */
  .tg-metric-row { grid-template-columns: 1fr auto; grid-template-areas: "label value" "bar bar"; }
}
@media (max-width: 480px) {                  /* mobile: single column, bar full width */
  .tg-metric-row { grid-template-columns: 1fr; grid-template-areas: "label" "value" "bar"; }
}
```

**The key inversion:** the bar is `1fr` with a `6rem` floor and the *chrome* columns shrink
first. The data element can no longer be the one that collapses.

| Concern | Resolution |
|---|---|
| `maxWidth: 900` wastes 40 % of a 1536 px viewport (M-035) | Raise to **1280 px**, centred. Not full-bleed: line lengths beyond ~1280 px hurt the caption text, and the page is a report, not a dashboard grid |
| Tables overflow the document at 390 px (M-027) | Each table wrapped in `overflow-x: auto` with `role="region"`, `tabindex="0"` and an accessible name — **a keyboard-scrollable region**, which is the accessible way to do a scrolling table |
| Block 2 grows to 42 rows | On mobile the table becomes **one card per scenario** with the six scorer rows stacked as label/value pairs — the standard responsive-table pattern, and legible at 390 px |
| Feature names overlap bars (M-025) | `minmax(9rem, 14rem)` + `overflow-wrap: anywhere` + `title` (§13) |
| Value text wraps and breaks row alignment (M-026) | Two-line value cell with fixed row height (§16) |
| Cost-curve panels at 390 px | The three panels stack vertically; the SVG uses `viewBox` + `width: 100%` (already) with a **minimum height** so labels never fall below 11 px effective |
| Sticky strip occlusion | Already passing (36 px clearance measured). The Demo Control Strip is **hidden on Metrics** (§19.2), so the concern largely disappears; the check is retained in the Playwright gate |

### 22.3 Verification

Playwright at **1536×960, 1280×800, 768×1024, 390×844**, asserting per viewport:

1. `document.documentElement.scrollWidth <= window.innerWidth` — **no horizontal overflow**.
2. For all 24 Block-3 rows and all Block-1/6 rows: the label element's right edge < the bar
   track's left edge — **no text-over-bar collision**.
3. Every row in a group has equal `offsetHeight` — **no alignment-breaking wrap**.
4. Every SVG `<text>` has a computed font size ≥ 11 px and its bounding box lies inside the
   `viewBox` — **no clipped or sub-legible labels**.
5. All six block headings are present and reachable by scrolling.
6. The sticky strip (where rendered) does not overlap the last content element at maximum scroll.
7. Zero console errors and zero console warnings.

These are **computed-geometry assertions, not screenshots** — they fail deterministically in CI
rather than requiring a human to compare images.

---

## 23. Frontend Test Infrastructure Plan

**This is the most important section of the plan.** The audit's verdict is that "a green suite
does not indicate a correct Metrics page" — all 40 findings are invisible to CI and it is green.

### 23.1 The existing stack (inspected, not assumed)

`services/dashboard/package.json`:

```json
{ "type": "module",
  "scripts": { "dev": "vite --port 5174" },
  "dependencies":    { "react": "^18.3.1", "react-dom": "^18.3.1",
                       "@fontsource/ibm-plex-mono": "^5.3.0", "@fontsource/ibm-plex-sans": "^5.3.0" },
  "devDependencies": { "vite": "^5.4.0", "@vitejs/plugin-react": "^4.3.1" } }
```

One script. No runner, no `*.test.*`, no `*.spec.*`. `services/storefront/` has the same shape.

### 23.2 Chosen stack, and why

| Tool | Version | Why this one |
|---|---|---|
| **Vitest** | `^2.1` | The Vite-native runner. Reuses `vite.config.js` — including `server.fs.allow: ["..","../.."]`, **which is what makes the build-time `import` of `eval/outputs/d6.json` resolve in tests exactly as it does in the app.** Jest would need a separate transform pipeline and a module mock for the JSON import, reintroducing the very gap between "what is tested" and "what ships" that this plan exists to close. Vitest 2.x is the line that pairs with Vite 5.4 |
| **@testing-library/react** | `^16.0` | Role- and text-based queries. Its API makes accessibility assertions the default way to query, which serves §21 at no extra cost. v16 is the React 18/19-compatible line |
| **@testing-library/jest-dom** | `^6.5` | `toHaveAccessibleName`, `toBeVisible` matchers |
| **jsdom** | `^25` | Chosen over happy-dom for **SVG element and attribute fidelity** — Block 4's tests read `<path d>`, `<circle cx>`, `<text x y>`. happy-dom is faster but its SVG support is thinner |
| **vitest-axe** | `^0.1` | `axe-core` bound to Vitest for the §21 automated a11y gate |
| **@playwright/test** | `^1.48` | Real layout, real viewports, real console. **The only tool that can verify §22** |

**Total: 6 devDependencies.** Justified against the repo's demonstrated conservatism (UIUX §10's
Day-1 exclusion list; `tokens.css`'s refusal of Tailwind) by the fact that **frontend test
coverage is currently zero and the brief makes it a hard requirement**. No runtime dependency is
added — the shipped bundle is unchanged.

### 23.3 The jsdom limitation, stated honestly

**jsdom does not perform layout.** `getBoundingClientRect()` returns zeros; `offsetHeight` is 0;
computed styles do not reflect cascade-driven geometry. This is a real constraint and it
determines the division of labour:

| Assertion type | Where it runs | Why |
|---|---|---|
| Text content, exact numeric strings | **Vitest + jsdom** | DOM text is fully faithful |
| Roles, accessible names, ARIA, table semantics | **Vitest + jsdom** | Accessibility tree is faithful |
| SVG **attribute** geometry (`d`, `cx`, `x`, `y`, `width` %) | **Vitest + jsdom** | Attributes are what the component emits; assert them directly |
| **Pure geometry functions** (`ribbonEnvelope`, `buildPanelGeometry`, `markerLayout`) | **Vitest, no DOM** | Extracted deliberately (§14.3) so geometry is unit-testable without layout |
| **Rendered layout** — overlap, overflow, row heights, computed font size | **Playwright only** | Requires a real engine |

**A plan that claimed to test "no text overlaps the bar" in jsdom would be repeating the
original sin of the grep tests: an assertion that cannot fail for the reason it claims.**
Overlap, overflow and height assertions live exclusively in §25.

### 23.4 Configuration and scripts

**NEW** `services/dashboard/vitest.config.js` — merges `vite.config.js` (inheriting
`server.fs.allow`, the React plugin and the JSON import), adds:

```js
test: {
  environment: "jsdom",
  setupFiles: ["./src/test/setup.js"],       // NEW: jest-dom + vitest-axe matchers
  include: ["src/**/*.test.{js,jsx}"],
  coverage: { provider: "v8", include: ["src/lib/**", "src/components/metrics/**",
                                        "src/components/charts/**", "src/screens/D6Metrics.jsx"],
              thresholds: { lines: 85, functions: 85, branches: 80 } },
}
```

**NEW** `services/dashboard/playwright.config.js` — four viewport projects, `webServer` running
`vite --port 5174`.

`package.json` scripts:

```json
"test":        "vitest",
"test:run":    "vitest run",
"test:cov":    "vitest run --coverage",
"test:e2e":    "playwright test",
"test:all":    "vitest run --coverage && playwright test"
```

**CI invocation.** A `tests/acceptance/test_frontend_suite.py` **(NEW)** marked
`@pytest.mark.slow` shells out to `npm --prefix services/dashboard run test:run` and asserts exit
0, so **one `pytest` invocation covers both suites** and the JS tests cannot be forgotten. This
mirrors how the repo already treats subprocess-backed tests (`pyproject.toml` declares a `slow`
marker for exactly this). Playwright stays a separate, explicitly-invoked gate — it needs a
browser download and a running server, which does not belong in the default unit run.

### 23.5 Fixture strategy

```
services/dashboard/src/__fixtures__/            (NEW)
├── realArtifact.js        -> re-exports the committed eval/outputs/d6.json unmodified
├── mutate.js              -> pure helpers: deepDelete(path), deepSet(path, value)
├── malformed.js           -> the 7 fixtures of §18.5, built via mutate.js at import time
└── synthetic.js           -> hand-built minimal artifacts with KNOWN values for maths tests
```

**Two fixture classes, deliberately:**

1. **The real artifact**, unmodified. Tests asserting the page shows the truth must run against
   the truth. `₹2,32,145`, `0.789`, `0.731`, `0.9998` are asserted against the real file.
2. **Synthetic artifacts** with hand-computed expected values, for testing *behaviour* under
   inputs the real artifact does not contain — a resolvable recall, a non-coincident optimum, a
   `flagged_two_sided` boundary at exactly 0.95, a `prior_correction_helped_at_pi1: false`.
   Without these, whole branches ship untested because the current data never exercises them.

**No fixture is created by editing `eval/outputs/d6.json`.** Mutations are applied in memory to a
structural clone. A test asserts the committed artifact is byte-identical before and after the
suite runs.

### 23.6 Test inventory

**`src/lib/` — pure, no DOM**

| ID | Assertion |
|---|---|
| `FE-T-CONTRACT-01..09` | The 9 missing-value cases (§6): `resolvable:false`, `constant:true`, absent optional field, explicit `null`, empty dataset, mathematically undefined metric, missing backend metric, malformed artifact, schema-version mismatch. **Each asserts `available === false` with a reason — never a number.** |
| `FE-T-CONTRACT-10` | No `\|\| 0` / `?? 0` in `d6Contract.js` (source scan — a legitimate absence assertion) |
| `FE-T-CONTRACT-11` | Both `schema_version` 1 and 2 parse |
| `FE-T-FMT-01` | **`inr(23214508.206055675) === "₹2,32,145"`** — the mandatory headline test |
| `FE-T-FMT-02` | `inr()` output is identical under `en-US` and `en-IN` host locales |
| `FE-T-FMT-03..08` | Precision policy per quantity (§10 table) |
| `FE-T-COVERAGE-01..03` | Field coverage: no unlisted leaf, no stale path, every `OMITTED` has a reason |
| `FE-T-GEOM-01..06` | `ribbonEnvelope`: `hi >= lo` at every index; the emitted polygon is **simple** (no crossing edge pair); a crossing-curve input still yields a valid envelope |
| `FE-T-GEOM-07..10` | `markerLayout`: coincident points yield one marker; non-coincident yield two; callout boxes never intersect |

**Component rendering tests — the block inventory the brief requires**

| Block | IDs | Key assertions (exact values from the real artifact) |
|---|---|---|
| **1** | `FE-T-B1-01..23` | renders model; renders `ap_at_eval_prevalence` **0.018 / 0.978 / 0.744 / 0.411**; renders `ap_raw` **0.789 / 0.998 / 0.935 / 0.814**; renders prevalence **0.731 / 0.685 / 0.476 / 0.433**; renders `π_eval 0.010`; renders **B0 AP** for all four tiers; renders tier labels easy/medium/hard/evasive; renders the unavailable recall state; **asserts no recall renders as a number**; reference-marker offset == prevalence; evasive row names `tier_e`; grouped null reason appears once; `n_neg` appears in every row |
| **2** | `FE-T-B2-01..10` | renders `l1-lgbm-v1` and `rules-only-v0` FP rows for all 7 scenarios; renders the 4 sanity scorers; `0/1` appears nowhere; `shared_ip_legit` renders `0 of 1` + `single sample`; `flash_sale` renders `n = 720` + an interval; `rowspan="6"`; zero empty grouping cells; θ_challenge from the artifact |
| **3** | `FE-T-B3-01..16` | all 24 features present; **14 constants render zero bars and the string `0.500` appears zero times**; `flagged` read from the artifact for all 24; `card_seen_24h` sorts above `bin_entropy_5m` and renders `inverted`; each of 6 flagged features renders its own `reason`; threshold read from the artifact (drift fixture moves it); no `0.95` literal in the source |
| **4** | `FE-T-B4-01..18` | both `curve_pi0` and `curve_pi1` render as paths with 10 vertices; both regimes labelled with artifact π values; **one** optimum marker when coincident, **two** in a non-coincident fixture; marker `cx` ≥ 6 px from the axis; Panel-A min-to-max vertical span ≥ 40 px; no two callout boxes intersect; every `<text>` inside the `viewBox`; ribbon polygon simple; ribbon absent from the π₁ panel; **renders `₹2,32,145`**; renders `₹0` **with** the word `structural`; series/tier/split rendered |
| **5** | `FE-T-B5-01..12` | renders `brier_raw` **0.1193 / 0.1403**; renders `ece_raw` (synthetic fixture, exact); renders Platt **0.0703 / 0.3955** and Platt+prior **0.0007 / 0.2807**; renders both reliability diagrams; empty bins not plotted and their count stated; point radius monotone in `weight`; verdict text contains both π₁ ECE values; a `helped:false` fixture flips the verdict; regime labels from the artifact |
| **6** | `FE-T-B6-01..12` | renders a **model** row with a numeric AP; renders B0 AP **0.997**, B1 TPR **0.075**, B2 TPR **0.718**; renders B3 sanity floor with a reason on `always_positive` and **no number**; renders per-tier data for 4 tiers × 4 series; B1 and B2 caveats present; B2 caveat names B0 and states non-independence |
| **Provenance** | `FE-T-PROV-01..08` | all six Eval §9 attributes render; `seeds_used` renders; `generated_at` renders as a date; config-mismatch fixture shows the warning; matching fixture does not; the "unknown" state never says "current" |
| **Errors** | `FE-T-ERR-01..07` | the 7 fixtures of §18.5: specific named cause, shell survives, and **no `0`, `0.000` or `NaN` in the Metrics region** |
| **A11y** | `FE-T-A11Y-01..12` | zero `axe` violations; tables have accessible names; every bar row reachable by role+name; **no unavailable row's accessible name matches `/\b0(\.0+)?\b/`** |
| **Routing** | `FE-T-ROUTE-01..06` | `#/metrics` renders on first paint; unknown hash falls back without throwing; title changes; `aria-current` |
| **Architecture** | `FE-T-ARCH-01..04` | zero `EventSource` constructions on `#/metrics`; `close()` called on navigation away; no armed timers; DC strip absent on Metrics |
| **Summary** | `FE-T-SUM-01..04` | every number in the executive summary matches its artifact field; the B0-beats-model claim is present |

### 23.7 The standard every test must meet

| Forbidden | Required |
|---|---|
| `assert "foo" in source` as evidence of rendering | render → query DOM → assert text/role/attribute |
| `expect(value).toBeGreaterThanOrEqual(0)` | independently derived exact expected value |
| `expect(container.querySelector("svg")).toBeTruthy()` | assert path geometry, marker separation, label bounds |
| Snapshot tests as the primary assertion | explicit assertions; snapshots only as a supplementary diff aid |

---

## 24. Backend Test Plan

### 24.1 Preserved unchanged

The audit is explicit that backend unit tests are "genuinely good" — 25 tests with real analytic
assertions (Wilson CI bracketing, degenerate→`None`, hull-minimum vs brute force, hull convexity,
B2 equals `distinct_cards_per_bin_5m` event-by-event, B1's 340 ms bitemporal gap, planted-
discriminator detection, prior correction reduces ECE at π₁). **None is rewritten.**

### 24.2 Strengthened

**`tests/acceptance/test_d6_cost_gap.py` — the mandatory numeric upgrade.**
`test_regime_switch_saving_is_non_negative` currently asserts only `>= 0` on the largest number
on the page. Replaced with an exact independent recomputation from the same hardcoded
anti-circularity anchors the file already uses (`C_FN = 5200`, `C_FP = 1800`):

```
stay_cost_pi1 = _cost(cost_optimal.fpr, cost_optimal.tpr, pi1)          -> 24 855 010.972933434
best_cost_pi1 = min(_cost(fpr, tpr, pi1) for fpr, tpr, _ in curve_pi1)  ->  1 640 502.7668777597
expected      = stay_cost_pi1 - best_cost_pi1                           -> 23 214 508.206055675
assert b4["regime_switch_saving_minor"] == pytest.approx(expected, abs=1e-6)
assert round(expected / 100) == 232145        # the displayed rupee figure
```

The final line is the anchor that ties the **backend number to the exact string the UI must
render**, and `FE-T-FMT-01` asserts the other half. Together they make the ₹2,32,145 headline
untouchable without a deliberate, visible change.

Also added to that file: exact assertions on the cost-optimal point `(0.0, 0.46891002194586684)`,
the F1-optimal point and its `f1 = 0.6384462151394422`, and every one of the 20 curve costs
recomputed from the formula.

### 24.3 New backend tests

| File | Covers |
|---|---|
| `tests/acceptance/test_d6_schema.py` **(NEW)** | `validate()` accepts the committed artifact; rejects each malformed mutation with a named error; every leaf has a spec entry |
| `tests/acceptance/test_d6_negative_controls_model_rows.py` **(NEW)** | FIX-BE-02: model and B0 rows per scenario; denominators equal the sanity rows'; `attempts` equals the count of `is_attack=False` samples; `episode_flagged` consistent with `episode_fp > 0` |
| `tests/acceptance/test_d6_block6_completeness.py` **(NEW)** | FIX-BE-03: model/b0/b1/b2 present; per-tier confusion counts **sum exactly** to the overall counts (the bitemporal-regression guard); sanity floor with reasons |
| `tests/acceptance/test_d6_audit_derivations.py` **(NEW)** | FIX-BE-05: `separability == abs(auc-0.5)` ×24; `direction` correct for the 2 inverted features; `observed_max_univariate_auc ≈ 0.9975874` and **≠ 0.95**; boundary at exactly 0.95; **`models/audit.json` SHA unchanged** |
| `tests/acceptance/test_d6_provenance.py` **(NEW)** | FIX-BE-06/M-029: `generated_at` parses as ISO-8601 UTC; `corpus_db_sha256` matches a directly computed SHA; all six Eval §9 attributes present and non-placeholder |
| `tests/acceptance/test_frontend_suite.py` **(NEW, `slow`)** | shells out to the JS suite; exit 0 |

### 24.4 Extended existing tests

| File | Extension |
|---|---|
| `test_calibration.py` | `ece_raw` present at both regimes; a hand-computed 4-sample `ece()` unit test; `prior_correction_helped_at_pi1` agrees with the ECE comparison |
| `test_cost_thresholds.py` | `theta_challenge()` == `1800/(1800+5200)` exactly; **no `0.257` literal in `eval/`** |
| `test_discriminability_audit.py` | derived fields agree with its independently recomputed AUCs |
| `test_d6_artifact.py` | delegates leaf validation to `test_d6_schema.py`; keeps the gitignore guard (a genuinely valuable protection against the "renders on a dev machine, empty on a clean clone" failure) |

### 24.5 Demoted

`test_d6_static.py` keeps **only** `test_no_runtime_data_path_in_d6_or_its_charts` (a real
architectural invariant: no `fetch(`/`EventSource`/`XMLHttpRequest` in D6 or its charts) and
`test_d6metrics_reaches_the_artifact_by_static_import`. Its module docstring is rewritten to say
explicitly:

> This file asserts **architectural invariants only**. It is not, and must never be treated as,
> evidence that any value is rendered. Rendering is covered by
> `services/dashboard/src/**/*.test.jsx`.

`test_all_six_blocks_are_referenced` and `test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap`
are **deleted**, and their intent is carried by `FE-T-B4-*` and the coverage contract.
`test_ui_contracts.py::TestD6Resolvability` is **deleted** once `FE-T-B1-*` and
`FE-T-CONTRACT-01` are green — see §26 for the ordering rule.

---

## 25. Browser / E2E Test Plan

`services/dashboard/e2e/metrics.spec.js` **(NEW)**, four viewport projects:
**1536×960 · 1280×800 · 768×1024 · 390×844**.

| # | Check | Assertion |
|---|---|---|
| 1 | Metrics loads directly | `goto("/#/metrics")`; the `Metrics & Evaluation` heading is visible on first paint |
| 2 | Refresh survives | `reload()`; still on Metrics |
| 3 | Back/forward | navigate live → metrics → back; route returns |
| 4 | Full page scrolls | scroll to bottom; the last element is reachable |
| 5 | **No console errors** | zero `console.error`; the page's own boundary logging is asserted absent on the happy path |
| 6 | **No console warnings** | zero `console.warn` (React key warnings et al.) |
| 7 | **No horizontal overflow** | `scrollWidth <= innerWidth` |
| 8 | All six blocks present | six `<h2>`s with the expected names |
| 9 | Important metrics visible | `₹2,32,145`, `0.789`, `0.731`, B0's AP, both ECE values are all in the viewport after scrolling |
| 10 | Null states understandable | every `not resolvable` row also shows an `n_neg` |
| 11 | Chart readable | every SVG `<text>` computed font-size ≥ 11 px and inside the `viewBox` |
| 12 | Tables readable | each table's wrapper is keyboard-focusable when it scrolls |
| 13 | Sticky controls do not obscure | at max scroll, the last content element's bottom < any sticky element's top |
| 14 | **No text over bars** | for every metric row: label right edge < bar left edge |
| 15 | Row alignment | all rows in a group have equal `offsetHeight` |
| 16 | **Zero network requests on Metrics** | 10 s idle dwell records no request (the M-031 gate) |
| 17 | Contrast | computed colours of caption/mono-data/axis text resolve to the corrected token |
| 18 | Keyboard | Tab reaches every disclosure; focus ring visible |

**Screenshots are captured as artifacts for human review but are never the assertion.** Every
gate above is a computed value, so it fails deterministically and names its cause.

---

## 26. Migration / Compatibility Plan

### 26.1 Artifact migration (v1 → v2)

Additive only (§8). Sequence:

1. Land `eval/d6_schema.py` describing **v1** and validate the committed artifact — proves the
   validator before it can block anything.
2. Add v2 fields behind the schema, bump `SCHEMA_VERSION` to 2.
3. Frontend accepts `[1, 2]` from day one; v2-only sections render "requires artifact v2" under
   a v1 artifact — **never a zero, never an empty chart**.
4. Regenerate the committed artifact **once**, at the end of Phase 1, with the full `diff_d6.py`
   output attached to the change (§17.3).

**No downgrade path is provided** and none is needed: the artifact is committed and versioned in
git; `git checkout` recovers any prior version.

### 26.2 Test migration — the ordering rule

**The rule: a Python source-string test is deleted only after its JS replacement is green.**
This prevents a coverage gap in the middle of the work — the exact failure mode that let 40
findings ship green.

| Existing test | Replacement | Delete when |
|---|---|---|
| `test_d6_static.py::test_all_six_blocks_are_referenced` | `FE-T-COVERAGE-01` + per-block render tests | all six block test suites green |
| `test_d6_static.py::test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap` | `FE-T-B4-01..18` | Block 4 suite green |
| `test_ui_contracts.py::TestD6Resolvability::test_barrow_reads_resolvable` | `FE-T-B1-20..23` | Block 1 null-state tests green |
| `test_ui_contracts.py::TestD6Resolvability::test_d6_passes_metric_objects_not_bare_values` | `FE-T-CONTRACT-01` | contract suite green |
| `test_ui_contracts.py::TestD6Resolvability::test_no_unresolvable_entry_can_reach_a_tofixed_path` | `FE-T-B1-*` negative test (no recall renders as a number) | Block 1 suite green |
| `test_ui_contracts.py::TestD6Resolvability::test_a_resolvable_alternative_is_shown` | `FE-T-B1-01..12` | Block 1 suite green |
| `test_d6_static.py::test_no_runtime_data_path_*` | — | **NEVER — kept, it is a real invariant** |
| `test_d6_static.py::test_d6metrics_reaches_the_artifact_by_static_import` | — | **NEVER — kept** |

**Deletion is a separate, explicitly-reviewed commit** so the removal of a safety net is visible
in history rather than buried in a feature change.

### 26.3 Component compatibility

`BarRow` is used by both `D6Metrics` and (via `metricText`) Block 6. Its new props
(`referenceMarker`, `unavailable` branch) are **additive with defaults**, so no call site breaks.
`AuditBars` is used only by D6. `CostCurve` is used only by D6. `grep` confirms no other screen
imports `components/charts/*`.

### 26.4 Dashboard-wide impact

Two changes reach beyond D6 and are called out so they are reviewed as such:

1. **`--tg-text-mute` lightens** (`#6E7885` → `#8B95A3`, §21.1). Affects D1, D3 and the shell.
   This is correct — the token was failing AA everywhere — but D1/D3 need a visual check.
2. **`App.jsx` routing and hook placement** (§19.1, §19.2). D1 and D3 must be verified unchanged
   in behaviour; `test_demo_lifecycle.py`, `test_sse.py` and `test_incident_api.py` are the
   relevant existing gates.

---

## 27. Dependency Graph

```
PHASE 0  ── verify the artifact (§17.3) ──┐
            diff_d6.py (NEW)              │  gates everything: if the artifact is stale,
                                          │  every "expected value" in every test is wrong
                                          ▼
PHASE 1  FIX-BE-06 (schema + provenance) ─────┐
              │                               │
              ├─ FIX-BE-01 (θ derived) ──► FIX-BE-02 (Block 2 model rows)
              ├─ FIX-BE-04 (ece_raw)          │        [independent of BE-01 only in
              ├─ FIX-BE-03 (Block 6)          │         computation; needs its threshold]
              └─ FIX-BE-05 (CI label,         │
                            separability)     │
                                              ▼
                       REGENERATE ARTIFACT ONCE (reviewed, diffed)
                                              │
PHASE 2  ────────────────────────────────────┤
         FIX-FE-01 (d6Contract)  ──┬──► FIX-FE-03 (metricsModel + coverage)
         FIX-FE-02 (format)      ──┘            │
                                                ▼
PHASE 3  ── Block work, parallelisable once Phase 2 lands ──
         FIX-M-001 ──► FIX-M-002        (Block 1: 002 needs 001's structure)
         FIX-M-015 / FIX-M-016 / FIX-M-028      (Block 1 companions)
         FIX-M-007-FE                            (Block 2 — needs FIX-BE-02)
         FIX-M-013 ──► FIX-M-006                 (Block 3: grouping needs the new sort)
         FIX-M-003 ──► FIX-M-005 ──► FIX-M-039   (Block 4 — needs FIX-BE-06 fields)
         FIX-M-010                                (Block 5 — needs FIX-BE-04)
         FIX-M-008                                (Block 6 — needs FIX-BE-03)
         FIX-M-029                                (provenance header)
                                                │
PHASE 4  ── page architecture (independent of block work) ──
         FIX-M-018 (routing) ──► FIX-M-031 (live isolation)
         FIX-M-019 (error boundary — needs FIX-FE-01's typed error)
                                                │
PHASE 5  ── UI/UX, a11y, responsive (needs all blocks to exist) ──
         §20 hierarchy + exec summary ──► §21 a11y ──► §22 responsive
                                                │
PHASE 6  ── test infrastructure ──
         §23 runner+config ──► (runs alongside Phase 3 from the start)
         §26 grep-test deletion  ← ONLY after replacements are green
                                                │
PHASE 7  ── §25 Playwright gates ──► §31 final verification
```

**Two dependencies that are easy to get wrong:**

- **The JS runner (§23.4) must be stood up at the START of Phase 3, not in Phase 6.** Writing
  the block work first and the tests afterwards would reproduce the original failure mode. The
  runner is scaffolding for Phase 3, not a deliverable after it.
- **Phase 0 gates everything.** Every exact expected value in every test (`0.789`, `₹2,32,145`,
  `0.9998`) is read from the committed artifact. If that artifact is stale, the tests pin the
  wrong numbers into place permanently.

---

## 28. Implementation Order

### Phase 0 — Verify before touching anything

1. `cp eval/outputs/d6.json` to a backup outside the repo.
2. Write `scripts/diff_d6.py` **(NEW)** — leaf-wise structural diff with float tolerance.
3. Regenerate to a scratch dir (§17.3) and diff against the committed artifact.
4. **Decision gate:** only ignored fields differ → the artifact is verified, the audit's J-class
   unknown is closed, proceed. Anything else differs → **stop and report the diff**; whether to
   re-commit changes published numbers and is the user's call.
5. Record the outcome in the implementation log with the command and the diff.

### Phase 1 — Backend data completeness (one regeneration at the end)

6. `FIX-BE-06` — `eval/d6_schema.py`, validate the **v1** artifact first, then v2 fields +
   provenance additions.
7. `FIX-BE-01` — derive θ_challenge. **Scratch-regenerate; diff; explain any Block-2 movement.**
8. `FIX-BE-04` — `ece_raw`, ECE gap, verdict flag. Scratch-regenerate; **assert the four existing
   calibration numbers are byte-identical.**
9. `FIX-BE-05` — CI relabel (`eval/load.py` + `eval/report.py`), `separability`/`direction`/
   `flagged_two_sided`, `univariate_auc_threshold`, `observed_max_univariate_auc`. Assert
   `models/audit.json` SHA unchanged.
10. `FIX-BE-03` — Block 6 model row, B3 floor with reasons, per-tier baselines. **Assert per-tier
    counts sum to overall.**
11. `FIX-BE-02` — Block 2 model + B0 rows, `episode_flagged`, `denominator_basis`.
12. Backend tests for all of the above (§24).
13. **Regenerate the committed artifact once**, reviewed, with the full diff attached.

### Phase 2 — Frontend foundations + test runner

14. `§23.4` — Vitest, Testing Library, jsdom, config, scripts, `src/test/setup.js`. **First**, so
    every subsequent step is testable as written.
15. `FIX-FE-01` — `d6Contract.js` + `FE-T-CONTRACT-*`.
16. `FIX-FE-02` — `format.js` + `FE-T-FMT-*` (including `₹2,32,145`).
17. `FIX-FE-03` — `metricsModel.js`, `d6FieldCoverage.js` + `FE-T-COVERAGE-*`.
18. `§18.5` — malformed fixtures + `FE-T-ERR-*`; `FIX-M-019` error boundary.

### Phase 3 — Blocks, in audit-severity order

19. **Block 1** (CRITICAL): `FIX-M-001` → `FIX-M-002` → `FIX-M-015`/`016`/`028`. Tests with each.
20. **Block 4**: `FIX-M-003` → `FIX-M-005` → `FIX-M-039`, with `costCurveGeometry.js` extracted
    first so geometry is unit-testable.
21. **Block 3**: `FIX-M-013` → `FIX-M-006` → `FIX-M-025`.
22. **Block 5**: `FIX-M-010` + `ReliabilityDiagram.jsx`.
23. **Block 6**: `FIX-M-008` (+ `FIX-M-026` row heights).
24. **Block 2**: `FIX-M-007-FE`.
25. **Provenance**: `FIX-M-029` header + Methodology panel.

### Phase 4 — Page architecture

26. `FIX-M-018` — `useHashRoute`, titles, `aria-current`.
27. `FIX-M-031` — `LiveShell`, subscription isolation.

### Phase 5 — Presentation

28. `§20` — hierarchy, executive summary (generated from the artifact), copy corrections
    (M-032/033/036).
29. `§21` — token contrast fix, table semantics, ARIA, SVG `title`/`desc`.
30. `§22` — `metrics.css`, fluid columns, table overflow regions, 1280 px container.

### Phase 6 — Test migration

31. Verify every replacement is green, then **delete the grep tests in a separate reviewed
    commit** (§26.2), and rewrite `test_d6_static.py`'s docstring.

### Phase 7 — Acceptance

32. `§25` Playwright at four viewports.
33. `§31` full verification procedure and the audit re-run.

---

## 29. Per-Finding Remediation Matrix

All 40 findings. Every one has a disposition; none is deferred without saying so.

| Finding | Sev | Root cause | Fix layer | Files | Plan step | Test | Acceptance |
|---|---|---|---|---|---|---|---|
| **M-001** | CRIT | RC-1 — frontend curates | Frontend (all data present) | `screens/D6Metrics.jsx`, `components/metrics/Block1PerTier.jsx` **(NEW)**, `lib/metricsModel.js`, `components/charts/BarRow.jsx` | FIX-M-001 | `FE-T-B1-01..12` | `ap_at_eval_prevalence` (0.018/0.978/0.744/0.411), `prevalence` (0.731/0.685/0.476/0.433) and `π_eval 0.010` all render; 1b labelled comparable, 1c labelled not |
| **M-002** | CRIT | RC-1 | Frontend | `components/metrics/Block1PerTier.jsx` **(NEW)** | FIX-M-002 | `FE-T-B1-13..18` | 4 B0 AP bars render on a shared scale with the model; verdict text names B0 as stronger at every tier |
| **M-003** | HIGH | RC-4 — one linear scale for 900×-apart series | Frontend viz | `components/charts/CostCurve.jsx`, `components/charts/costCurveGeometry.js` **(NEW)** | FIX-M-003 | `FE-T-B4-01..06`, E2E #11 | Panel A min-to-max vertical span ≥ 40 px; log y disclosed on the axis |
| **M-004** | HIGH | RC-4 — no axis-collision handling | Backend flag + frontend | `eval/d6.py::_block4_cost`, `components/charts/CostCurve.jsx` | FIX-BE-06, FIX-M-003 | `FE-T-B4-07..12`, `FE-T-GEOM-07..10` | Marker `cx` ≥ 6 px from the y-axis; exactly **one** marker+label when `optima_coincident` |
| **M-005** | HIGH | RC-4 — assumed non-crossing envelopes | Backend envelope + frontend | `eval/d6.py::_block4_cost`, `costCurveGeometry.js` **(NEW)** | FIX-M-005 | `FE-T-GEOM-01..06` | `hi >= lo` at every index; **rendered polygon proven simple** (no crossing edge pair); band ≥ 8 px; absent from the π₁ panel |
| **M-006** | HIGH | RC-1 — `constant`/`reason` dropped | Frontend | `components/charts/AuditBars.jsx`, `components/metrics/UnavailableGroup.jsx` **(NEW)** | FIX-M-006 | `FE-T-B3-09..16` | 14 constants render **zero** bars; the string `0.500` appears **zero** times; each flagged feature shows its own `reason` |
| **M-007** | HIGH | **B — backend missing** | Backend | `eval/d6.py::_block2_negative_controls`, `eval/harness.py::HarnessRun` | FIX-BE-02 | `test_d6_negative_controls_model_rows.py`, `FE-T-B2-01..02` | 42 rows (7 × 6); model + B0 present for every scenario; sanity scorers retained |
| **M-008** | HIGH | **B — backend missing** + RC-1 | Backend + frontend | `eval/d6.py::_block6_baselines`, `eval/harness.py::_baseline_summary`, `components/metrics/Block6Baselines.jsx` **(NEW)** | FIX-BE-03, FIX-M-008 | `test_d6_block6_completeness.py`, `FE-T-B6-01..12` | Model row present; B3 floor rendered with reasons; per-tier 4 × 4; per-tier counts **sum** to overall |
| **M-009** | HIGH | RC-1 | Frontend | `components/metrics/ProvenanceHeader.jsx` **(NEW)** | FIX-M-029 | `FE-T-PROV-01..06` | All six Eval §9 attributes visible without interaction |
| **M-010** | HIGH | **B (ece_raw)** + RC-1 (rest) | Backend + frontend | `eval/harness.py::_regime`, `components/metrics/Block5Calibration.jsx` **(NEW)**, `components/charts/ReliabilityDiagram.jsx` **(NEW)** | FIX-BE-04, FIX-M-010 | `test_calibration.py`, `FE-T-B5-01..12` | Raw column for Brier **and** ECE; both reliability diagrams render; verdict states the π₁ result |
| **M-011** | MED | RC-3 — misnomer | Backend naming | `eval/d6.py::_augment_audit_block` | FIX-BE-05 | `test_d6_audit_derivations.py` | `observed_max_univariate_auc ≈ 0.9976` and **≠** `univariate_auc_threshold` (0.95); old key retained |
| **M-012** | MED | RC-2 — duplicated constant + recomputed flag (**and a `>` vs `>=` drift found in planning**) | Frontend | `components/charts/AuditBars.jsx` | FIX-M-013 | `FE-T-B3-01..08` | No `0.95` literal in the component; `flagged` read from the artifact for all 24; a threshold-drift fixture moves the rule |
| **M-013** | MED | RC-4 — one-sided model of a two-sided quantity | Backend derive + frontend | `eval/d6.py`, `components/charts/AuditBars.jsx` | FIX-BE-05, FIX-M-013 | `FE-T-B3-01..08` | Sorted by `\|AUC−0.5\|`; `card_seen_24h` above `bin_entropy_5m`; both inverted features marked `inverted` with raw AUC still printed |
| **M-014** | MED | No formatting policy | Frontend | `lib/format.js` **(NEW)**, `components/charts/CostCurve.jsx` | FIX-FE-02 | `FE-T-FMT-01..02` | `₹2,32,145` renders identically under `en-US` and `en-IN`; no locale-free `toLocaleString` remains |
| **M-015** | MED | Copy not updated with FIX-019 | Frontend copy | `components/metrics/Block1PerTier.jsx` | FIX-M-015 | `FE-T-B1-23` | Caption describes what renders; no claim about a bar height |
| **M-016** | MED | Data labelling (split hidden) | Backend emit + frontend | `eval/d6.py::_block1_per_tier`, `Block1PerTier.jsx` | FIX-M-016 | `FE-T-B1-19` | Evasive row names `tier_e`; easy names `temporal_test`; **evasive bar styling identical to the other three** (UIUX §6.13) |
| **M-017** | MED | **Boolean rendered as a rate** (structural — §1(B)) | Backend re-type + frontend | `eval/d6.py`, `components/metrics/Block2NegativeControls.jsx` **(NEW)** | FIX-BE-02, FIX-M-007-FE | `FE-T-B2-03..06` | `0/1` appears nowhere; `shared_ip_legit` shows `0 of 1` + `single sample`; `flash_sale` shows `n = 720` + an interval |
| **M-018** | MED | RC-5 — `useState` navigation | Frontend | `App.jsx`, `hooks/useHashRoute.js` **(NEW)**, `index.html` | FIX-M-018 | `FE-T-ROUTE-01..06`, E2E #1–3 | `#/metrics` loads directly, survives refresh, back/forward work, title correct, `aria-current` set |
| **M-019** | MED | No boundary + unguarded dereferences | Frontend | `components/MetricsErrorBoundary.jsx` **(NEW)**, `lib/d6Contract.js` **(NEW)** | FIX-FE-01, FIX-M-019 | `FE-T-ERR-01..07` | Each of 7 malformed fixtures renders a **named** cause; the shell survives; the original error is always logged |
| **M-020** | MED | RC-2 — rounded duplicate | Backend | `eval/report.py`, `eval/d6.py` | FIX-BE-01 | `test_cost_thresholds.py` | `theta_challenge() == 1800/(1800+5200)` exactly; **no `0.257` literal in `eval/`**; any Block-2 movement enumerated |
| **M-021** | MED | RC-2 — hardcoded π strings | Frontend | `components/charts/CostCurve.jsx`, `Block5Calibration.jsx` | FIX-M-003, FIX-M-010 | `FE-T-B5-12`, `FE-T-B4-04` | A fixture with `pi0: 0.002` changes every rendered π label |
| **M-022** | MED | RC-1 | Frontend | `ProvenanceHeader.jsx`, `Block5Calibration.jsx` | FIX-M-029, FIX-M-010 | `FE-T-PROV-07`, `FE-T-B5-08` | `seeds_used = 1` visible; `effective_n` (759.5 / 1650.9) shown beside nominal `n = 2125` |
| **M-023** | MED | `--tg-text-mute` fails AA | Design token | `styles/tokens.css` | FIX-M-023 | `FE-T-A11Y-01..04`, E2E #17 | Every text role ≥ **4.5:1**; contrast computed from tokens in a unit test |
| **M-024** | MED | Non-semantic markup | Frontend | all `components/metrics/*`, `charts/*` | FIX-M-024 | `FE-T-A11Y-05..12` | Zero `axe` violations; `th scope` + `caption` on both tables; real `rowSpan`; bar rows have accessible names; SVG `title`/`desc` + table alternative |
| **M-025** | MED | Fixed 200 px label column | Responsive | `components/charts/AuditBars.jsx`, `styles/metrics.css` **(NEW)** | FIX-M-025, §22 | E2E #14 | Label right edge < bar left edge for **all 24 rows at all four viewports** |
| **M-026** | MED | Value text wraps | Layout | `components/metrics/Block6Baselines.jsx` | FIX-M-008 | `FE-T-B6-11`, E2E #15 | All rows in a group have equal `offsetHeight` |
| **M-027** | MED | No media queries at all | Responsive | `styles/metrics.css` **(NEW)** | §22 | E2E #7 | `scrollWidth <= innerWidth` at 1536/1280/768/390; tables in focusable overflow regions |
| **M-028** | MED | Null state is bar-shaped | Frontend | `components/charts/BarRow.jsx`, `UnavailableGroup.jsx` **(NEW)** | FIX-M-028 | `FE-T-B1-20..22` | Unavailable rows contain **zero** filled elements; grouped reason once; `n_neg` in every row |
| **M-029** | MED | **H — no timestamp, no corpus identity** | Backend + frontend | `eval/d6.py::_provenance`, `ProvenanceHeader.jsx` | FIX-BE-06, FIX-M-029 | `test_d6_provenance.py`, `FE-T-PROV-08` | `generated_at` present and rendered; three freshness states; **the page never claims the artifact reflects the current tree** |
| **M-030** | MED | **RC-6 — no runner** | Test infrastructure | `services/dashboard/package.json`, `vitest.config.js` **(NEW)**, `playwright.config.js` **(NEW)**, `src/test/setup.js` **(NEW)** | §23 | the entire JS suite | `npm run test:run` executes real React rendering tests; `pytest` invokes them via `test_frontend_suite.py`; coverage ≥ 85 % lines on D6 paths |
| **M-031** | MED | RC-5 — hooks above the route switch | Frontend | `App.jsx`, `components/LiveShell.jsx` **(NEW)** | FIX-M-031 | `FE-T-ARCH-01..04`, E2E #16 | **Zero** network requests during a 10 s dwell on Metrics; `EventSource.close()` on navigation; DC strip hidden on Metrics |
| **M-032** | LOW | Build-log text in product copy | Frontend copy | `screens/D6Metrics.jsx`, `charts/AuditBars.jsx` | §20.4 | source scan + `FE-T-*` | No `SS6.13`, `UIUX v2`, `Eval Protocol §` strings in rendered output; references live in code comments |
| **M-033** | LOW | `.tg-label` uppercases identifiers | Frontend copy | `styles/type.css` usage in metric components | §20.4 | `FE-T-B1-*` | `l1-lgbm-v1` renders lowercase as the artifact spells it |
| **M-034** | LOW | Rotated label at the viewBox edge | Frontend viz | `components/charts/CostCurve.jsx` | FIX-M-003 | `FE-T-B4-14`, E2E #11 | Every `<text>` bounding box lies inside the `viewBox`; y-axis label horizontal above the axis |
| **M-035** | LOW | `maxWidth: 900` | Layout | `styles/metrics.css` **(NEW)** | §22 | E2E #7 | Container 1280 px centred; no wasted 40 % at 1536 px; label columns fit |
| **M-036** | LOW | No units, direction or magnitude encoding | Frontend | `components/metrics/Block5Calibration.jsx` | FIX-M-010 | `FE-T-B5-04..07` | "lower is better" stated once per family; magnitude encoded so 0.3955 and 0.0007 are not identical |
| **M-037** | LOW | RC-1 | Frontend | `components/charts/CostCurve.jsx` | FIX-M-003 | `FE-T-B4-18` | Chart states `series l1-lgbm-v1 · tier challenge · split temporal_test` from the artifact |
| **M-038** | LOW | RC-3 — bare `null` with no reason | Backend + frontend | `eval/d6.py::_block6_baselines`, `Block6Baselines.jsx` | FIX-BE-03, FIX-M-008 | `FE-T-B6-03` | `always_positive` renders `unreachable — constant scorer has no intermediate operating point`, **not a number** |
| **M-039** | LOW | Structural fact presented as empirical | Backend flag + copy | `eval/d6.py::_block4_cost`, `charts/CostCurve.jsx` | FIX-M-039 | `FE-T-B4-16` | `₹0` never appears without the word `structural` and its explanation |
| **M-040** | LOW | RC-3 / I — CI mislabelled (**also present in `eval/report.py::_fmt_recall`, which the audit did not find**) | Backend + frontend | `eval/load.py::_recall_json`, `eval/report.py::_fmt_recall`, `charts/BarRow.jsx` | FIX-BE-05 | `test_d6_provenance.py`, `FE-T-B1-*` | Interval labelled "95% CI on achieved FPR" in **both** the markdown report and the UI; `fpr_ci_*` keys emitted; `ci_basis` present |

**Disposition summary:** 40 findings — **40 FIXED**, 0 deferred, 0 not-applicable.
Two are fixed with a **documented deviation** from the audit's suggested remedy:
- **M-001** — no `lift` metric is minted; the trivial-classifier floor is rendered as a reference
  marker instead (§11, "Deliberately NOT done").
- **M-029** — `build_hash` divergence alone is **not** treated as staleness; `config_hash` plus
  the new corpus/model SHAs are the signals (§17.2).

Two carry **forced spec deviations**, recorded for `Decisions.md`:
- **UIUX §6.13's "rupee gap set between them"** is unsatisfiable — the optima coincide (§14.3).
- **UIUX §6.13's per-row `FLAGGED — GENERATOR ARTIFACT` annotation** becomes a group header;
  six stacked absolutely-positioned labels overlap the rows above (§13).

---

## 30. Acceptance Criteria

The implementation is **not** complete because pytest passes, npm test passes, the page loads, or
the screenshot looks better. It is complete when every gate below passes **with evidence**.

### 30.1 DATA

| # | Gate | Evidence |
|---|---|---|
| D1 | Every artifact leaf is rendered or explicitly declared omitted with a reason | `FE-T-COVERAGE-01..03` green; zero unlisted leaves |
| D2 | No unjustified missing value | The audit's 23 discarded values all render; the coverage map documents the rest |
| D3 | **The 9 correctly-unresolvable recalls remain `n/a`** | `FE-T-B1-*` negative test: no `resolvable:false` entry renders a number |
| D4 | **No undefined metric becomes zero** | `FE-T-CONTRACT-01..09` + `FE-T-ERR-*`: no `0`, `0.000` or `NaN` in the Metrics region for any null fixture |
| D5 | No backend-required metric is fabricated in the frontend | `d6Contract.js` contains no `\|\| 0` / `?? 0` (test); model-unavailable rows render a reason |
| D6 | **Model-vs-baseline truth is visible** | B0's four AP values render; the verdict names B0 as stronger at every tier; it appears in the executive summary **above** the blocks |

### 30.2 CALCULATIONS

| # | Gate | Evidence |
|---|---|---|
| C1 | All existing correct mathematics preserved | `eval/metrics.py` and `eval/cost.py` **unchanged**; `git diff --stat` on those files is empty |
| C2 | `ece_raw` independently tested | Hand-computed 4-sample `ece()` unit test; both regimes present |
| C3 | Cost calculations independently tested | `test_d6_cost_gap.py` recomputes both optima, the gap, all 20 curve costs, **and the regime-switch saving = 23 214 508.206055675** from `C_FN=5200`/`C_FP=1800` |
| C4 | Threshold derived correctly | `theta_challenge() == 1800/(1800+5200)`; no `0.257` literal in `eval/` |
| C5 | Discriminability semantics correct | `separability == abs(auc−0.5)` for all 24; boundary at exactly 0.95 pinned |
| C6 | The four calibration numbers unchanged | Byte-identical to the pre-change artifact |
| C7 | `models/audit.json` untouched | SHA-256 identical before and after |

### 30.3 FRONTEND

| # | Gate | Evidence |
|---|---|---|
| F1 | Actual React rendering tests exist | `vitest run` executes ≥ 120 tests that mount components |
| F2 | **No source-string-only frontend contract** | `test_d6_static.py` reduced to architectural invariants with an explicit docstring; `TestD6Resolvability` deleted after replacement |
| F3 | Exact numeric assertions | `₹2,32,145`, `0.789`, `0.731`, `0.018`, `0.9998`, `0.0007`, `0.2807`, `0.075`, `0.718` all asserted as exact strings |
| F4 | Missing-value tests | All 9 cases of §6 covered |
| F5 | Malformed-artifact tests | All 7 fixtures of §18.5 covered |
| F6 | Chart geometry tests | Ribbon simplicity, marker separation, label non-intersection, viewBox containment |
| F7 | Coverage | ≥ 85 % lines / 85 % functions / 80 % branches on `lib/`, `components/metrics/`, `components/charts/`, `screens/D6Metrics.jsx` |

### 30.4 VISUAL

| # | Gate | Evidence |
|---|---|---|
| V1 | Cost curve legible | Panel A min-to-max ≥ 40 px; marker ≥ 6 px from the axis |
| V2 | No overlapping labels | Pairwise callout bounding-box test; E2E label check |
| V3 | No self-intersecting ribbon | Segment-intersection proof over the emitted path |
| V4 | Null states visually distinct | Zero filled elements in unavailable rows |
| V5 | Constant/un-fed features distinct | Zero bars, `0.500` absent |
| V6 | Consistent number formatting | One `format.js`; no bare `.toFixed(` outside it |
| V7 | Responsive at all four viewports | E2E gates #7, #11, #14, #15 |

### 30.5 ACCESSIBILITY

| # | Gate | Evidence |
|---|---|---|
| A1 | WCAG AA text contrast | Token contrast unit test ≥ 4.5:1 for every text role; E2E computed-style check |
| A2 | Semantic tables | `caption` + `th scope` on both; real `rowSpan`; zero empty grouping cells |
| A3 | Accessible bars | Every bar row has an accessible name composing label + value + condition |
| A4 | Accessible SVG | `title` + `desc` per panel + the operating-point table as the data alternative |
| A5 | Nav semantics | `aria-current="page"` |
| A6 | Keyboard / focus | Disclosures reachable; focus ring visible; overflow regions focusable |
| A7 | **Screen-reader null semantics** | No unavailable row's accessible name matches `/\b0(\.0+)?\b/` |
| A8 | Automated scan | Zero `axe-core` violations on a full-page render |

### 30.6 ARCHITECTURE

| # | Gate | Evidence |
|---|---|---|
| R1 | Metrics does not subscribe to live monitoring | Zero `EventSource` constructions; zero network requests in a 10 s dwell |
| R2 | Direct route works | `goto("/#/metrics")` renders D6 on first paint |
| R3 | Refresh works | `reload()` stays on Metrics |
| R4 | Document title correct | `Tollgate — Metrics & Evaluation` |
| R5 | Artifact provenance visible | Six Eval §9 attributes + `generated_at` + `seeds_used` |
| R6 | Stale artifacts detectable | Config-mismatch fixture renders the warning; matching fixture does not |
| R7 | Malformed artifact does not blank the app | Shell survives all 7 fixtures |

---

## 31. Final Verification Procedure

Run in order. **Every step produces an artifact of evidence that is attached to the completion
report.** A step that "looks fixed" is not done.

**1 — Full backend suite**
```bash
python -m pytest tests/ -q
```
Evidence: pass count, and a diff of the test inventory vs. the pre-change baseline showing what
was added and what was deleted (and why).

**2 — Frontend suite with coverage**
```bash
npm --prefix services/dashboard run test:cov
```
Evidence: pass count, coverage table, and confirmation that ≥ 120 tests mount components.

**3 — Backend metric tests, explicitly**
```bash
python -m pytest tests/acceptance/test_d6_cost_gap.py tests/acceptance/test_calibration.py \
    tests/acceptance/test_metrics_resolution.py tests/acceptance/test_discriminability_audit.py \
    tests/acceptance/test_d6_audit_derivations.py -v
```
Evidence: the exact `regime_switch_saving` assertion passing against `23214508.206055675`.

**4 — Artifact / schema tests**
```bash
python -m pytest tests/acceptance/test_d6_schema.py tests/acceptance/test_d6_artifact.py \
    tests/acceptance/test_d6_provenance.py -v
```
Evidence: validator accepts the real artifact; each malformed mutation produces a named error.

**5 — Browser acceptance**
```bash
npm --prefix services/dashboard run test:e2e
```
Four viewports × 18 checks. Evidence: the Playwright HTML report plus screenshots **as
supporting material, not as the assertion**.

**6 — Responsive checks** — E2E gates #7, #11, #14, #15 at 1536×960, 1280×800, 768×1024, 390×844.
Evidence: per-viewport pass table.

**7 — Accessibility checks** — `FE-T-A11Y-*` plus E2E #17/#18. Evidence: the `axe` report showing
zero violations, and the computed contrast table.

**8 — Numerical recomputation, independent of the code**
Re-derive by hand, from `config/cost_model.yaml` and the artifact, and compare against the
rendered DOM:
`C_FN = 200 + 5000 = 5200` · `C_FP(challenge) = 120000 × 0.30 × 0.05 = 1800` ·
`cost(TPR,FPR,π) = 10000 × (π(1−TPR)·C_FN + (1−π)·FPR·C_FP)` · cost-optimal
`(0.0, 0.46891002194586684, 27616.67885881492)` · F1-optimal identical, `f1 = 0.6384462151394422`
· `rupee_gap = 0.0` · `regime_switch_saving = 24855010.972933434 − 1640502.7668777597 =
23214508.206055675` → **₹2,32,145** · ECE(Platt+prior) @ π₀ `= 0.0007305349387266664` and @ π₁
`= 0.2806765620747161` recomputed from the artifact's own reliability bins · Wilson upper for
0/221 `= 0.017085189007591345` · `n_neg` per tier `221/221/316`, summing to `758` ·
`821+701+603 = 2125 = block5.n = b0.n`.
Evidence: a recomputation table with a Δ column, every Δ exactly 0.

**9 — Provenance / staleness verification**
```bash
python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db --model-dir models --out "$SCRATCH/final-verify"
python scripts/diff_d6.py eval/outputs/d6.json "$SCRATCH/final-verify/d6.json" \
    --ignore provenance.build_hash --ignore provenance.generated_at \
    --ignore provenance.head_at_generation --ignore provenance.tree_dirty_at_generation
```
Evidence: the diff output, expected to be empty. **`eval/outputs/d6.json` must be byte-identical
before and after this step** — verified by SHA.

**10 — Re-run the audit methodology**
Repeat `METRICS-AUDIT-2026-09-02.md`'s method: static trace of every value from config → metric
function → artifact → JSX → live DOM; independent recomputation of every checkable quantity;
live browser inspection with SVG geometry computed to sub-pixel precision and cross-checked
against the rendered DOM.

Produce `METRICS-AUDIT-VERIFICATION-<date>.md` giving each of the 40 findings one of exactly
three dispositions, **each with evidence**:

| Disposition | Required evidence |
|---|---|
| **FIXED** | The test ID that now fails if it regresses **and** the observed DOM/value proving the fix |
| **INTENTIONALLY RETAINED** | The justification, the spec or Decisions.md citation, and the test pinning the retained behaviour |
| **NOT APPLICABLE** | The evidence showing the precondition no longer exists |

**Forbidden in that document:** "probably fixed", "looks fixed", or "test passes" as the sole
evidence for a visual or semantic finding.

**11 — The reviewer test.** A person who has not read the source opens `#/metrics` and answers,
out loud, the twelve success-condition questions: what was measured · on which split · at what
prevalence · with which model · with which seed/config/policy · how the model compares with
B0/B1/B2/B3 · which metrics are unavailable and exactly why · which features are real
measurements vs un-fed slots · what the cost curve says · what calibration improved · the
important caveats · how trustworthy each number is. **Any question they cannot answer from the
page is a defect**, recorded and fixed. This is the gate the current page fails despite being
green, and it is the one that matters.

---

## 32. Risks / Open Questions

### 32.1 Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | **Phase 0 reveals the committed artifact is stale.** Every exact expected value in every test would be pinning wrong numbers | Medium | **Critical** — invalidates the test suite's premise | Phase 0 is a hard gate before any code change. If stale, stop and report; re-committing changes published numbers and is the user's decision |
| R-2 | **θ_challenge derivation moves Block-2 numbers.** `0.257` → `0.2571428…` reclassifies any score in that band | Medium | Medium | Scratch-diff after FIX-BE-01; enumerate and explain every changed cell before proceeding |
| R-3 | **Per-tier B1 breaks bitemporal correctness** by re-running `b1_decline_velocity` per tier instead of slicing | Medium | **High** — silently credits the detector with information it never had | The summed-counts test (§16) fails loudly; `test_baselines_single_source.py` retained unmodified |
| R-4 | **Log-scale y is read as distortion** by a reviewer | Low | Medium | Axis explicitly labelled "(log scale)"; exact values printed in the operating-point table; decade ticks |
| R-5 | **`--tg-text-mute` change regresses D1/D3 visually** | Low | Low | Visual check of both screens; the change makes them *more* compliant |
| R-6 | **`LiveShell` unmount changes event-buffer behaviour** across a navigation round-trip | Medium | Medium | `test_demo_lifecycle.py`, `test_sse.py`, `test_incident_api.py` re-run; E2E navigation round-trip test |
| R-7 | **jsdom cannot verify layout**, tempting layout assertions that cannot fail for the stated reason | Medium | **High** — would repeat the grep-test failure mode | §23.3 assigns layout exclusively to Playwright; code review rejects any `getBoundingClientRect` assertion in a Vitest test |
| R-8 | **Six new devDependencies** against a repo that has deliberately refused frameworks | Certain | Low | No runtime dependency added; bundle unchanged; justified by a hard requirement and recorded in `Decisions.md` |
| R-9 | **Scope.** This plan touches ~35 files across two languages | Certain | Medium | Phase gates with independent value: Phase 1 alone fixes the backend gaps; Phase 3 alone fixes the critical findings. Work is stoppable at a phase boundary without leaving the page worse |
| R-10 | **The executive summary drifts** from the numbers below it | Low | High — it is the most-read text | It is **generated from the artifact**, not authored; `FE-T-SUM-01..04` assert every number matches its field |
| R-11 | **`OMITTED` becomes an escape hatch** in the coverage map | Medium | Medium | Reason ≥ 20 chars enforced by test; new `OMITTED` entries treated as decisions requiring justification |

### 32.2 Open questions — decisions the user should make

**Q1 — Stream Rail on the Metrics route.** UIUX §11 open decision 2 resolves "Stream Rail on
**every screen** — it is what stops the app feeling like separate pages", and App Flow §5 D0
puts the rail, threat band and banner on every screen. M-031 requires suspending the live
subscription there. These conflict.
**Default if unanswered:** render the rail in its existing static-snapshot form (the
`prefers-reduced-motion` path already implemented in `StreamRail.jsx`), keep the threat band with
an `as of <time>` qualifier, and **hide the Demo Control Strip** on Metrics. Visual continuity is
preserved; only the data path is suspended.

**Q2 — Regenerating the committed artifact.** Phase 1 ends with one deliberate regeneration.
If Phase 0 shows the current artifact is stale, the regenerated numbers will differ from those
published in the audit and in any existing screenshots or slides.
**This is the user's call and the plan will not make it silently.** Default if unanswered:
stop at the end of Phase 0 and report the diff.

**Q3 — Playwright.** It is the only tool that can verify §22 and the visual half of the
acceptance gate, but it adds a browser download to the dev setup.
**Default if unanswered:** include it, kept out of the default `pytest` run and invoked
explicitly. If rejected, §22 and E2E gates #7/#11/#14/#15 fall back to manual browser inspection
via the existing Chrome tooling — which is repeatable by a human but **not** by CI, and the
acceptance report must then say so rather than claiming automated coverage.

**Q4 — Block-3 constant-feature grouping and UIUX §6.13.** The spec mandates a per-bar
`FLAGGED — GENERATOR ARTIFACT` annotation. With six simultaneous flags the labels overlap the
rows above (measured: `top: -15px`). The plan moves it to a group header.
**Default if unanswered:** proceed with the group header and record the deviation in
`Decisions.md`. The amber token and its "measurement suspect" meaning are preserved.

**Q5 — Whether `recall @ FPR 1e-3` should be re-targeted.** The spec's designated cross-tier
comparator is unresolvable at every tier because no split reaches 1000 negatives. A larger
corpus, or a looser `target_fpr` (e.g. 1e-2, resolvable at 221 negatives), would make it
reportable.
**This plan does not do either** — both change the evaluation, not the page, and
`config/cost_model.yaml`'s `target_fpr` is provenanced to Eval Protocol §2.1. Raised because it
is the *real* reason Block 1 cannot show its headline metric, and it is a question the project
may want to answer separately.

---

## Appendix A — Files touched

**NEW — backend (3)**
`eval/d6_schema.py` · `scripts/diff_d6.py` · (tests below)

**MODIFIED — backend (5)**
`eval/d6.py` · `eval/harness.py` · `eval/report.py` · `eval/load.py` · `config/` *(none — configs
are unchanged; `config_hash` must not move)*

**NEW — frontend (14)**
`services/dashboard/vitest.config.js` · `playwright.config.js` · `src/test/setup.js` ·
`src/lib/d6Contract.js` · `src/lib/format.js` · `src/lib/metricsModel.js` ·
`src/lib/d6FieldCoverage.js` · `src/hooks/useHashRoute.js` · `src/components/LiveShell.jsx` ·
`src/components/MetricsErrorBoundary.jsx` · `src/components/metrics/*.jsx` (Block1PerTier,
Block2NegativeControls, Block5Calibration, Block6Baselines, ProvenanceHeader, MethodologyPanel,
UnavailableGroup, OperatingPointTable) · `src/components/charts/ReliabilityDiagram.jsx` ·
`src/components/charts/costCurveGeometry.js` · `src/styles/metrics.css` · `src/__fixtures__/*`

**MODIFIED — frontend (7)**
`src/screens/D6Metrics.jsx` · `src/App.jsx` · `src/components/charts/BarRow.jsx` ·
`src/components/charts/AuditBars.jsx` · `src/components/charts/CostCurve.jsx` ·
`src/styles/tokens.css` · `package.json` · `index.html`

**NEW — tests (7)**
`tests/acceptance/test_d6_schema.py` · `test_d6_negative_controls_model_rows.py` ·
`test_d6_block6_completeness.py` · `test_d6_audit_derivations.py` · `test_d6_provenance.py` ·
`test_frontend_suite.py` · `services/dashboard/e2e/metrics.spec.js` · plus
`services/dashboard/src/**/*.test.{js,jsx}`

**MODIFIED — tests (6)**
`test_d6_cost_gap.py` (strengthened) · `test_d6_artifact.py` (extended) ·
`test_calibration.py` · `test_cost_thresholds.py` · `test_discriminability_audit.py` ·
`test_d6_static.py` (**reduced to architectural invariants**)

**DELETED — tests (3, only after replacements are green)**
`test_d6_static.py::test_all_six_blocks_are_referenced` ·
`test_d6_static.py::test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap` ·
`test_ui_contracts.py::TestD6Resolvability` (whole class)

**NOT MODIFIED — deliberately**
`eval/metrics.py` · `eval/cost.py` · `eval/audit.py` · `eval/baselines.py` ·
`eval/provenance.py` · `scripts/train_l1.py` · `models/*` · `config/*.yaml` ·
`data/corpus/tollgate.db` · `tests/fixtures/*`

---

*Plan produced read-only against the repository at `day-2` / `8cf17d9`. No source file, test,
config, fixture or artifact was modified in producing it. Every file path, line number, function
name and numeric value cited was verified against the working tree; the feature-corpus coverage
in §2.3 and the harness `--out` behaviour in §17.3 were established by direct inspection, not
inferred.*









