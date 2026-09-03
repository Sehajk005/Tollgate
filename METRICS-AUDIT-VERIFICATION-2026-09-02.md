# Tollgate — D6 Metrics Audit: Verification Matrix (FINAL)

**Audit:** `METRICS-AUDIT-2026-09-02.md` · **Plan:** `METRICS-REMEDIATION-PLAN-2026-09-02.md`
**Evidence log:** `METRICS-IMPLEMENTATION-LOG-2026-09-02.md` · **Date:** 2026-09-02
(verified against the working tree; branch `day-2`, HEAD `8cf17d9`, uncommitted)

> This replaces the earlier checkpoint matrix. Phases 0–7 are complete. Each of the 40
> findings has one of three dispositions with evidence: **FIXED** (the regression-guard test
> ID + the observed DOM/value), **INTENTIONALLY RETAINED** (justification + citation + the
> test pinning it), **NOT APPLICABLE** (evidence the precondition is gone).
>
> **Result: 40 FIXED**, 0 intentionally-retained-unfixed, 0 not-applicable. Two are fixed
> with a **documented deviation** from the audit's suggested remedy (M-001, M-029); two carry
> a **forced spec deviation** recorded for `Decisions.md` (coincident optima; the
> flagged-feature group header).
>
> Suite state: backend `pytest tests/` → **619 passed, 2 xfailed, 0 failed**; frontend
> `vitest run` → **205 passed / 21 files**, 98.47 % line / 86.13 % branch / 97.79 % fn
> coverage; Playwright `playwright test` → **68 passed** (17 checks × 4 viewports).
> `eval/outputs/d6.json` SHA `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737`
> and `models/audit.json` SHA `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c`
> are unchanged; `git diff` on `eval/metrics.py` / `eval/cost.py` / `eval/audit.py` /
> `eval/baselines.py` / `eval/provenance.py` is empty.

---

## The 40 findings

| # | Sev | Disposition | Regression-guard test | Observed evidence |
|---|---|---|---|---|
| **M-001** AP shown at raw prevalence; π / `ap_at_eval_prevalence` discarded | CRIT | **FIXED** (documented deviation: no `lift` metric minted — a prevalence-floor reference marker instead, §11) | `Block1PerTier.test.jsx` FE-T-B1 (1b/1c value + heading), `metricsModel.test.js` (`apAtEvalPrevalence`), E2E #9 | Block 1 renders **1b** `ap_at_eval_prevalence` (model `0.018 / 0.978 / 0.744 / 0.411`) under "comparable · π_eval = 0.01" **and** **1c** `ap_raw` (`0.789 / 0.998 / 0.935 / 0.814`) under "not cross-tier", each with its own `prevalence` marker (`0.731 / 0.685 / 0.476 / 0.433`). |
| **M-002** B0 per-tier AP omitted; B0 beats the model | CRIT | **FIXED** | `Block1PerTier.test.jsx` (paired bars + verdict), `metricsModel.test.js` (`b0BeatsModelOnAllApTiers === true`), `D6Metrics.test.jsx` FE-T-SUM | B0 (`rules-only-v0`) AP bars render beside the model on a shared scale at all four tiers (`0.9998 / 0.9987 / 0.9815 / 0.9583` — each **>** the model). Executive summary leads "B0 outperforms the learned model…". |
| **M-003** cost decision-region is sub-pixel on a linear axis | HIGH | **FIXED** | `costCurveGeometry.test.js` FE-T-GEOM (Panel-A span ≥ 40 px), `CostCurve.test.jsx` FE-T-B4, E2E #11 | Three stacked panels, **log y** ("(log scale)" on every axis label). Panel A x-domain `[0, 0.001978891820580475]`; curve+ribbon span the panel height. |
| **M-004** cost-optimal marker sits on the y-axis | HIGH | **FIXED** | `CostCurve.test.jsx` (one marker when coincident; `cx` ≥ 6 px from axis), `costCurveGeometry.test.js` (markerLayout), `test_d6_cost_gap.py::test_optima_coincidence_is_a_backend_fact` | `optima_coincident: true` → **one** inset filled-circle marker + **one** callout; `markerLayout` insets it and, in Panel C, flips the callout left of the marker so no `<text>` leaves the viewBox (E2E #11 green ×4 viewports). |
| **M-005** self-intersecting sensitivity ribbon | HIGH | **FIXED** | `costCurveGeometry.test.js` FE-T-GEOM-01..06 (`hi ≥ lo ∀i`; rendered polygon simple), `test_d6_cost_gap.py::test_ribbon_envelope_is_a_valid_non_crossing_band` | `ribbon_envelope` = per-x min/max across `ribbon_pis`; monotone x + `hi ≥ lo` ⇒ simple polygon. Ribbon in Panels A/B, **absent** from Panel C. |
| **M-006** 14 un-fed constants render as a measured `0.500` | HIGH | **FIXED** | `AuditBars.test.jsx` FE-T-B3 (14 "not fed" rows, `0.500` absent), `metricsModel.test.js` (`groups.notFed.length === 14`) | Three groups — Flagged (6), Measured (4), Not fed (14, behind an `aria-expanded` disclosure → `UnavailableGroup`, **no bars**). `0.500` appears nowhere. |
| **M-007** Block 2 scores only the sanity scorers | HIGH | **FIXED** (backend) | `test_d6_negative_controls_model_rows.py`, `Block2NegativeControls.test.jsx` FE-T-B2 | `_block2_negative_controls` → **42 rows** (7 × 6): `l1-lgbm-v1`, `rules-only-v0` (at `theta_challenge()`), then the 4 sanity scorers. Denominators identical across all 6 rows/scenario. |
| **M-008** Block 6 has no model / B3 / per-tier | HIGH | **FIXED** | `test_d6_block6_completeness.py` (per-tier tp/fp/tn/fn sum to overall), `Block6Baselines.test.jsx` FE-T-B6 | Block 6 renders the **model row** (AP `0.945`, ROC-AUC `0.889`), B0 (`0.997`/`0.994`), B1 TPR `0.075`, B2 TPR `0.718`, a **B3 sanity floor**, and a **4-tier × 4-series** matrix. |
| **M-009** 3 of 6 Eval §9 provenance attrs missing | HIGH | **FIXED** | `ProvenanceHeader.test.jsx` FE-T-PROV-01..06, `test_d6_provenance.py` | Identity line, no interaction: `seed 42 · config a7db8c61189a · model l1-lgbm-v1 · policy 1 · π_eval 0.01 · split temporal_test · seeds_used 1`. |
| **M-010** no raw calibration column / no reliability diagrams | HIGH | **FIXED** (documented deviation: 5 non-empty bins at π₀, not the plan-prose "4" — the artifact's bin weights win) | `test_calibration.py` (hand `ece(…) == 0.225`; 4 anchors byte-identical), `Block5Calibration.test.jsx` FE-T-B5 | 2×6 grid — Brier & ECE × {raw, Platt, Platt+prior} per regime — with `effective_n` and an inline magnitude bar per cell. Two `<ReliabilityDiagram>`s: 5 non-empty bins at π₀ / 6 at π₁, "N empty bins omitted" stated. |
| **M-011** `max_univariate_auc` misnamed | MED | **FIXED** | `test_d6_audit_derivations.py::test_observed_max_is_the_real_maximum_not_the_threshold` | `univariate_auc_threshold = 0.95`, `observed_max_univariate_auc = 0.9975874252835037`; old key retained. |
| **M-012** AuditBars hardcodes the threshold and recomputes `flagged` | MED | **FIXED** | `AuditBars.test.jsx` (no `0.95` literal; marker moves with a `0.90` fixture), `D6Metrics.copy.test.jsx` | Threshold rule = `((threshold − 0.5)/0.5)` from `univariate_auc_threshold`; `flagged` read from `flagged_two_sided`; **no `0.95` literal** in `AuditBars.jsx`. |
| **M-013** one-sided discriminability flag | MED | **FIXED** | `test_d6_audit_derivations.py` (×24 `separability`, `direction`), `AuditBars.test.jsx` (`card_seen_24h` above `bin_entropy_5m`, `↓ inverted`) | Bar length = `separability = |auc − 0.5|`; `card_seen_24h` (AUC 0.225) renders `↓ inverted` with the raw AUC printed and sorts above `bin_entropy_5m`. |
| **M-014** ₹ headline is locale-dependent | MED | **FIXED** | `format.test.js` FE-T-FMT-01/02, E2E #9 | `inr(23214508.206055675) === "₹2,32,145"` via a module-scope `Intl.NumberFormat("en-IN")`; identical under `en-US` / `en-IN`; `₹2,32,145` visible on the live page. |
| **M-015** Block 1 caption describes bars that don't render | MED | **FIXED** | `Block1PerTier.test.jsx` (caption), `D6Metrics.copy.test.jsx` | Caption describes what renders (1a/1b/1c); no claim about an un-drawn bar height. |
| **M-016** evasive tier from a different split, unlabelled | MED | **FIXED** | `Block1PerTier.test.jsx` (evasive label + identical fill), `test_d6_provenance.py::test_split_name_is_reachable_per_block` | `block1_per_tier.*.evasive.split == "tier_e"` (others `temporal_test`); the evasive row is labelled `tier_e — adversarial split`, bar fill token identical to the other three. |
| **M-017** episode denominators are 1; n ≤ 5 scenarios unmarked | MED | **FIXED** | `test_d6_negative_controls_model_rows.py`, `Block2NegativeControls.test.jsx` FE-T-B2-03..06 | Episode-flagged renders `yes` / `no` — `0/1` appears nowhere. `shared_ip_legit` → `0 of 1` + `single sample — n=1`; `retry_storm` → `underpowered — n=5`; `flash_sale` → `n = 720` + a Wilson `95% CI`. |
| **M-018** no routing / deep link / title | MED | **FIXED** | `useHashRoute.test.js` FE-T-ROUTE, `LiveShell.test.jsx`, E2E #1–3 | `#/metrics` renders on first paint; `reload()` stays; back/forward restore; `document.title` follows the route; `aria-current="page"` on the active nav button. |
| **M-019** no error boundary | MED | **FIXED** | `MetricsErrorBoundary.test.jsx` FE-T-ERR-01..07, `d6Contract.test.js` FE-T-CONTRACT | `parseArtifact` throws a typed `ArtifactContractError` (message + `path`) caught by `<MetricsErrorBoundary>`; the fallback names the cause + the regen command; the original error is always `console.error`-logged; the shell survives. |
| **M-020** `THETA_CHALLENGE` a hardcoded rounded copy | MED | **FIXED** | `test_cost_thresholds.py::test_theta_challenge_accessor_equals_1800_over_7000_to_full_precision` | `theta_challenge()` = `1800/(1800+5200)` = `0.2571428571428571`; `grep 0\.257 eval/` → nothing; `block2_theta_challenge` emitted; no Block-2 FP movement. |
| **M-021** π₀ / π₁ hardcoded in 3 UI strings | MED | **FIXED** | `Block5Calibration.test.jsx` FE-T-B5-12 (`withDifferentPi`), `CostCurve.test.jsx` FE-T-B4-04 | Every π label is `format.pi(block4_cost.pi0 / pi1)`; `withDifferentPi()` moves every rendered π in the cost curve and the calibration block. |
| **M-022** single-seed estimates unqualified | MED | **FIXED** | `ProvenanceHeader.test.jsx` FE-T-PROV-07, `Block5Calibration.test.jsx` FE-T-B5-08 | `seeds_used 1` on the identity line; `effective n` column `759.5` / `1650.9` beside nominal `n = 2125`; exec summary says "Single-seed point estimate". |
| **M-023** captions / `n/a` fail AA contrast | MED | **FIXED** | `contrast.test.js` FE-T-A11Y-01..04, E2E #17 | `--tg-text-mute` `#6E7885` → `#8B95A3`. Recomputed WCAG ratios **6.42 / 5.99 / 5.52** on canvas / surface-1 / surface-2 (all ≥ 4.5; was 4.34 / 4.05 / 3.74). Live computed `--tg-text-mute` = `#8b95a3`. |
| **M-024** tables / bar rows lack semantic structure | MED | **FIXED** | `D6Metrics.a11y.test.jsx` FE-T-A11Y-05..12 (axe **zero violations**), `Block2NegativeControls.test.jsx` / `Block6Baselines.test.jsx` | Every `<table>` has `<caption>` + `<th scope="col">` + real `<th scope="row" rowSpan>`; bar rows are `role="group"` with a composed `aria-label`; every chart SVG has `<title>` + `<desc>` + the operating-point table alternative. axe: 0 violations, full page. |
| **M-025** feature name overflows into the bar | MED | **FIXED** | E2E #14 (label right edge < bar left edge, all rows × 4 viewports), `AuditBars.test.jsx` | `AuditBars` name column `minmax(clamp(10rem, 22ch, 16.25rem), max-content)` + `overflow-wrap: anywhere` + `title`; the row carries `.tg-metric-row` so it stacks below 480 px. E2E #14 green at 1536 / 1280 / 768 / 390. |
| **M-026** Block 6 value wraps, breaks row alignment | MED | **FIXED** | E2E #15 (equal `<tr>` height per body × 4 viewports), `Block6Baselines.test.jsx` FE-T-B6-11 | Two-line fixed-height `OpCell`; `.tg-scroll-x > table { min-width: max-content }` keeps the table natural-width and scrolls the region rather than compressing cells. E2E #15 green ×4. |
| **M-027** fixed-column layout, no media queries | MED | **FIXED** | E2E #7 (`scrollWidth ≤ innerWidth` × 4 viewports), E2E #12 | `styles/metrics.css` — the first `@media` layer in the dashboard: `.tg-metrics` 1280 px container, `.tg-metric-row` stack at 768 / 480, `.tg-scroll-x` focusable overflow regions. **No horizontal overflow** at 1536 / 1280 / 768 / **390** (was +118 px at 390 before the fix). |
| **M-028** null state renders as a full-width bar | MED | **FIXED** | `UnavailableGroup.test.jsx`, `Block1PerTier.test.jsx` (1a renders no number), `D6Metrics.a11y.test.jsx` (no `role=group` aria-label matches `/\b0(\.0+)?\b/`) | `UnavailableGroup` renders one shared reason + N `role="group"` rows with a **dashed 1px rule** (no filled track) and `· n_neg=221` per row; accessible name reads "…not resolvable · n_neg=221", never "…0". |
| **M-029** no timestamp; `build_hash` silently stale | MED | **FIXED** (documented deviation: `build_hash` divergence alone is **not** staleness — `config_hash` + corpus/model SHAs are the signal, §17.2) | `test_d6_provenance.py` (`corpus_db_sha256`, `model_files_sha256`, ISO-8601 `generated_at`), `ProvenanceHeader.test.jsx` FE-T-PROV-08 | Header renders `generated 2026-09-02 17:03 UTC` + a three-state freshness line (`config-mismatch` → `role="alert"` with both hash prefixes / `current` / `unknown` → "not verifiable", never a false "current"). `MethodologyPanel` exposes `build_hash`, `head_at_generation`, `tree_dirty_at_generation`, `fixture_sha256`, `corpus_db_sha256`, `model_files_sha256[*]`, `calibrator_version`, `generation_command`. |
| **M-030** no frontend test infrastructure | MED | **FIXED** | the entire JS suite | Vitest 2.1.9 + RTL 16 + jsdom 25 + vitest-axe + `@playwright/test`; `vitest run` → **205 passed / 21 files**, 98.47 % line coverage on the D6 surface; `playwright test` → 68 passed. |
| **M-031** static screen keeps SSE + polling | MED | **FIXED** | `LiveShell.test.jsx` FE-T-ARCH-01..04, E2E #16 | Live hooks are in `<LiveShell>`, mounted only for `live` / `incident`. On `#/metrics`: **zero `EventSource` constructions**, no poll timer, DC strip absent; a 10 s dwell records **no** `/v1/*` or `eventsource` request. Navigating away calls `EventSource.close()`. |
| **M-032** internal spec IDs in UI copy | LOW | **FIXED** | `D6Metrics.copy.test.jsx` FE-T-COPY (13 components, comment-stripped scan), `AuditBars.test.jsx` | No component authors `UIUX v2` / `SS<n>` / `Eval Protocol §` / `App Flow §` / `§<n>` in rendered text; the two `Eval Protocol §` occurrences are in code comments (permitted). A rendered artifact `reason` that cites the spec is data, not authored copy. |
| **M-033** CSS uppercases identifiers | LOW | **FIXED** | `D6Metrics.copy.test.jsx` FE-T-COPY (M-033) | `l1-lgbm-v1` / `rules-only-v0` render as literal lowercase and are **never** inside a `.tg-label` (the only `text-transform: uppercase` class). |
| **M-034** rotated y-axis label clipped at the viewBox edge | LOW | **FIXED** | `CostCurve.test.jsx` (no rotated `<text>`; every `<text>` ≥ 11 px inside the viewBox), E2E #11 | y-axis label horizontal above the axis; SVG label font-size 11; **E2E #11 green at all 4 viewports** after the Panel-C callout-flip fix (`markerLayout` `plotRight`). |
| **M-035** `maxWidth: 900` wastes viewport | LOW | **FIXED** | E2E #7, `metrics.css` | `.tg-metrics { max-width: 1280px; margin-inline: auto }`; no horizontal overflow at 1536; caption line-length capped for legibility. |
| **M-036** Block 5 has no units / direction / magnitude | LOW | **FIXED** | `Block5Calibration.test.jsx` FE-T-B5-04..07 | Verdict states "Lower is better for both Brier and ECE" once per family; each cell has an inline magnitude bar (`MAG_MAX = 0.4`) so `0.3955` ≠ `0.0007` typographically; best-in-family bolded. |
| **M-037** cost curve never states series / tier / split | LOW | **FIXED** | `CostCurve.test.jsx` FE-T-B4-18 | Subtitle renders `series l1-lgbm-v1 · tier challenge · split temporal_test` from `block4_cost.series / tier / split`. |
| **M-038** `always_positive: null` has no reason | LOW | **FIXED** | `test_d6_block6_completeness.py`, `Block6Baselines.test.jsx` FE-T-B6-03 | `b1/b2_sanity_floor.always_positive` → `{value: null, available: false, reason: "unreachable: a constant scorer …"}`; Block 6 renders "always_positive is unreachable — a constant scorer has no intermediate operating point …", **not a number**. |
| **M-039** ₹0 gap presented as empirical | LOW | **FIXED** | `test_d6_cost_gap.py::test_rupee_gap_is_flagged_structural_with_a_substantiating_note`, `CostCurve.test.jsx` FE-T-B4-16 | `rupee_gap_is_structural: true` + `rupee_gap_note`; copy reads "F1-vs-cost gap at π₀ = 0.01 is ₹0 — structural, not empirical. <note>". `₹0` never appears without "structural". |
| **M-040** CI mislabelled as CI-on-recall | LOW | **FIXED** | `test_d6_provenance.py`, `eval/report.py::_fmt_recall` | `_recall_json` emits `fpr_ci_low` / `fpr_ci_high` + `ci_basis: "wilson_on_achieved_fpr"`; both the markdown report (`"95% CI on achieved FPR"`) and the UI label the interval as being on the achieved FPR. |

---

## §31 step 8 — numerical recomputation (Δ table, independent of the code)

| Quantity | Re-derived by hand (from `config/cost_model.yaml` + the artifact) | Artifact / rendered | Δ |
|---|---|---|---|
| `C_FN` | `200 + 5000` | `5200` | 0 |
| `C_FP(challenge)` | `120000 × 0.30 × 0.05` | `1800` | 0 |
| cost-optimal `(FPR, TPR, cost)` | `(0.0, 0.46891002194586684, 27616.67885881492)` | identical | 0 |
| F1-optimal | identical to cost-optimal, `f1 = 0.6384462151394422` | `optima_coincident: true` | 0 |
| `rupee_gap` | `0.0` | `0.0` | 0 |
| `regime_switch_saving` | `24855010.972933434 − 1640502.7668777597 = 23214508.206055675` → **₹2,32,145** | `23214508.206055675` → `₹2,32,145` | 0 |
| ECE(Platt+prior) @ π₀ | `0.0007305349387266664` | `0.0007305349387266664` | 0 |
| ECE(Platt+prior) @ π₁ | `0.2806765620747161` | `0.2806765620747161` | 0 |
| Wilson upper for 0/221 | `0.017085189007591345` | `fpr_ci_high` (easy/med/evasive) `0.017085189007591345` | 0 |
| `n_neg` per tier | `221 / 221 / 316`, sum `758` | `221 / 221 / 316`, sum `758` | 0 |
| `821 + 701 + 603` | `2125` = `block5.n` = `b0.n` | `block5.n = 2125` | 0 |
| θ_challenge | `1800 / (1800 + 5200) = 0.2571428571428571` | `block2_theta_challenge = 0.2571428571428571` | 0 |
| `observed_max_univariate_auc` ≠ threshold | `0.9975874252835037 ≠ 0.95` | same | 0 |

Every Δ is **exactly 0**.

## §31 step 9 — provenance / staleness

Regenerated `python -m eval.harness --split all --seed 42 --corpus-db data/corpus/tollgate.db
--model-dir models --out <scratch>`; `scripts/diff_d6.py` against the committed artifact,
ignoring `provenance.build_hash`, `generated_at`, `head_at_generation`,
`tree_dirty_at_generation`, and `generation_command` (the last differs only because `--out`
names the scratch path) → **0 substantive differences [added 0, removed 0, changed 0]**.
`eval/outputs/d6.json` SHA `29edcb22…` **byte-identical before and after**;
`models/audit.json` SHA `ce75cb7f…` unchanged.

---

## Documented deviations (in force)

1. **M-001** — no `lift` metric minted; the trivial-classifier floor is a reference marker
   (§11). Pinned by `Block1PerTier.test.jsx` (marker offset == prevalence).
2. **M-029** — `build_hash` divergence alone is not staleness; `config_hash` + corpus/model
   SHAs are the signal (§17.2). Pinned by `metricsModel.test.js` (`freshness` state) and
   `ProvenanceHeader.test.jsx`.
3. **UIUX §6.13 "rupee gap set between the two optima"** — unsatisfiable; the optima coincide
   (`optima_coincident: true`). One marker, one callout. For `Decisions.md`.
4. **UIUX §6.13 per-row `FLAGGED — GENERATOR ARTIFACT` annotation** — becomes one group
   header in AuditBars (six stacked absolute labels would overlap the rows above). For
   `Decisions.md`.
5. **B0 hard-tier `ap_raw` renders `0.981`** (`0.9814576232319572`); plan prose §11/§29 says
   `0.982`. The verified artifact value wins (§23.5 / §23.7).
6. **Reliability diagram bin counts** — 5 non-empty at π₀ (prose says "4"), 6 at π₁. The
   artifact's bin weights are the source of truth.
7. **`BarRow.jsx` is superseded** — the block components have their own row renderers (§26.3).
   The file remains on disk (nothing imports it); removing it is source cleanup, not test
   migration.

## Test migration (§26.2, Phase 6 — applied, not yet committed)

Deleted after their real-rendering JS replacements went green:
`test_d6_static.py::test_all_six_blocks_are_referenced`,
`test_d6_static.py::test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap`,
`test_ui_contracts.py::TestD6Resolvability` (whole class, 4 tests).
`test_d6_static.py`'s docstring is rewritten to "architectural invariants only"; its two
surviving tests (static import, no runtime data path) are unchanged.

## §31 step 11 — the reviewer test

**Outstanding — requires a person.** Someone who has not read the source opens `#/metrics` and
answers the twelve success-condition questions aloud (what was measured · on which split · at
what prevalence · vs which baselines · with what uncertainty · …). The implementation cannot
self-certify this step.
