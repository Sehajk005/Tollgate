# Tollgate — Metrics Page QA / Data-Integrity / UI Audit

**Date:** 2026-09-02
**Scope:** D6 "Metrics & Evaluation" screen only
**Branch:** `day-2` · HEAD `8cf17d9` · working tree dirty
**Mode:** READ-ONLY. No repository file was modified, no test altered, no defect repaired.
**Artifact under audit:** `eval/outputs/d6.json` (26,897 bytes, committed, `schema_version: 1`)

---

## 1. Executive Summary

**Overall status: NOT READY.**

Every number on the Metrics page that I could independently recompute is **arithmetically
correct**. The cost model, the ROC hull, both optima, the rupee gap, the regime-switch
saving, the ECE values, the tier sample counts and the negative counts all reproduce
exactly from `config/cost_model.yaml` and from the artifact's own inputs. The frontend
renders the artifact faithfully: every displayed digit and every bar width matches the
JSON to the last decimal. There is no calculation error and no backend↔frontend value
mismatch anywhere on the page.

The page nevertheless fails, for a different reason: **it selects the wrong subset of a
correct artifact.** The evaluation harness computes an honest, well-hedged set of
measurements. The D6 screen then displays the flattering half of them, drops the half that
supplies the baseline or the caveat, and prints explanatory captions that describe charts
which are not on screen.

Four things drive the verdict:

1. **Block 1 shows average precision at each tier's own raw prevalence, with the
   prevalence omitted.** `easy = 0.789` is displayed as a 79% bar. At that tier's
   prevalence of 0.731, a constant classifier scores 0.731 — the model's lift is **1.08×**.
   The artifact also carries `ap_at_eval_prevalence` (0.0178), the prevalence-normalised
   figure that the Eval Protocol mandates. It is discarded. Both the Eval Protocol (§2.1)
   and the App Flow (§5 D6) require the prevalence to be printed beside the AP; it is not.
2. **The comparison that would expose this is present in the artifact and not rendered.**
   `rules-only-v0` per-tier AP is 0.9998 / 0.9987 / 0.9815 / 0.9583 — the **B0 rules
   baseline beats the learned model on all four tiers.** `Decisions.md` commits to
   reporting exactly that ("It is weaker than B0 overall … Reported 'in exactly that
   form' (Eval Protocol §8)"). Block 1 renders B0's recall bars, which are all `n/a`,
   and omits B0's AP, which is not.
3. **The cost curve is geometrically broken.** The cost-optimal minimum — the point that
   defines both headline rupee figures — renders **0.12 px above the x-axis**, and all
   three decision-relevant operating points occupy **0.5 px of horizontal space**. The
   cost-optimal marker line is drawn at coordinates identical to the y-axis. The
   sensitivity ribbon self-intersects and is at most 2.2 px thick.
4. **Nothing tests any of this.** There is no JavaScript test runner in the project. Every
   "frontend test" is a Python string-grep over JSX source. The ₹2,32,145 headline — the
   largest number on the page — is covered by a single assertion that it is `>= 0`.

**Counts:** 2 Critical · 8 High · 21 Medium · 9 Low = **40 findings.**

The strongest thing about the page is genuine and worth stating: the `resolvable:false`
handling (FIX-019) is exemplary. Eight recall figures that cannot be resolved at 221/316
negatives draw **no bar at all** and print `n/a · n_neg=221`. That is exactly right, and it
is the behaviour the rest of the page should be measured against.

---

## 2. Scope

**Audited:** the D6 route and everything it renders — `D6Metrics.jsx`, `BarRow.jsx`,
`AuditBars.jsx`, `CostCurve.jsx`, the committed artifact `eval/outputs/d6.json`, its
generator `eval/d6.py`, the metric implementations (`eval/metrics.py`, `eval/cost.py`,
`eval/audit.py`, `eval/baselines.py`, `eval/harness.py`, `eval/report.py`), the configs
(`config/cost_model.yaml`, `config/features.yaml`), the governing specifications
(`05-EVAL-PROTOCOL-v2.md`, `06-APPFLOW-v2.md`, `08-UIUX-SPEC-v2.md`), `Decisions.md`, and
the ten related test files.

**Method:** static trace of every value from raw config → metric function → artifact →
JSX → live DOM; independent recomputation of every arithmetically checkable quantity;
live browser inspection at `http://localhost:5174` with the scorer running on `:8080`;
SVG geometry computed to sub-pixel precision and cross-checked against the rendered DOM.

**Not audited:** D1 Live, D3 Incident, the storefront, the scorer's runtime scoring path.
Services started for this audit were stopped afterwards; they were not running before.

---

## 3. Architecture & Data Flow

The Metrics page is **not API-backed**. There is no fetch, no SSE, no runtime computation.

```
config/*.yaml + data/corpus/tollgate.db + models/
        │
        ▼
python -m eval.harness            ← run offline, manually, by a human
        │  HarnessRun{ eval_reports, baseline_summary,
        │              calibration_block, audit_block }
        ▼
eval/d6.py :: build_artifact()    ← pure serialiser over HarnessRun
        │                           (block 4 is the only new arithmetic)
        ▼
eval/outputs/d6.json              ← COMMITTED to git (.gitignore:28 exception)
        │
        ▼  ES-module `import` at BUILD time — Vite inlines it into the bundle
D6Metrics.jsx
        │
        ├─ Block1  → BarRow      (recall_at_target_fpr, ap_raw)
        ├─ Block2  → <table>     (block2_negative_controls)
        ├─ Block3  → AuditBars   (block3_audit.features)
        ├─ Block4  → CostCurve   (block4_cost)  ← inline SVG
        ├─ Block5  → <table>     (block5_calibration)
        └─ Block6  → BarRow      (block6_baselines)
        │
        ▼
DOM (491 nodes, 445 inside <main>)
```

**Consequences of this shape, all verified:**

- The artifact is a **hand-regenerated snapshot**. It becomes stale silently; nothing
  detects staleness at build or run time.
- `models/audit.json` is byte-identical to `block3_audit` — Block 3 comes from
  *model-training* time, one step further removed than the other five blocks.
- Only `block4_cost` is computed by `eval/d6.py` itself. Blocks 1/2/3/5/6 are pass-through
  serialisations of objects `eval/report.py` also formats.
- `block1_per_tier[*].evasive` is read from a **different split** (`tier_e`) than
  easy/medium/hard (`temporal_test`) — see METRICS-016.
- In dev the JSON arrives as `/@fs/D:/Projects/Tollgate/eval/outputs/d6.json?import`; in a
  production build it is inlined. Both are build-time in the sense that matters.
- The **shell** (`App.jsx`) is not static: while D6 is displayed it keeps an `EventSource`
  open, polls `/v1/replay/status`, and re-fetches `/v1/stream/recent`. Observed: 1 network
  request during a 5-second idle dwell on Metrics.

**Verified negatives:** `grep` for `fetch(`, `EventSource`, `XMLHttpRequest`, `axios`,
`WebSocket` across `D6Metrics.jsx` + `components/charts/` returns nothing. Console during a
full page visit contained **zero errors or warnings** (3 messages, all Vite/React dev
notices).

---

## 4. Complete Metric Inventory

Every value on the page. "Source verified" = traced from artifact to DOM.
"BE/FE match" = the DOM string is the faithful rendering of the artifact field.

### Header

| # | Metric | Displayed | Artifact field | Verified | Match | Status |
|---|---|---|---|---|---|---|
| 1 | build | `9141a8ecc41b` | `provenance.build_hash[:12]` | ✓ | ✓ | VERIFIED CORRECT (stale vs HEAD — M-029) |
| 2 | config | `a7db8c61189a` | `provenance.config_hash[:12]` | ✓ | ✓ | **VERIFIED CORRECT** — recomputed `config_hash()` today = exact match |
| 3 | seed | `42` | `provenance.seed` | ✓ | ✓ | VERIFIED CORRECT |
| 4 | model | `l1-lgbm-v1` | `provenance.model_version` | ✓ | ✓ | VERIFIED CORRECT |
| 5 | policy_version | **not shown** | `provenance.policy_version` = 1 | ✓ | — | **FRONTEND MISSING** (M-009) |
| 6 | π_eval | **not shown** | `provenance.eval_prevalence` = 0.01 | ✓ | — | **FRONTEND MISSING** (M-009) |
| 7 | split name | **not shown** | `block4_cost.split` = `temporal_test` | ✓ | — | **FRONTEND MISSING** (M-009) |
| 8 | fixture_sha256 | not shown | `provenance.fixture_sha256` | ✓ | — | INTENTIONAL OMISSION (matches disk) |
| 9 | calibrator_version | not shown | `platt-v1` | ✓ | — | INTENTIONAL OMISSION |
| 10 | seeds_used | **not shown** | `provenance.seeds_used` = **1** | ✓ | — | **FRONTEND MISSING** (M-022) |

### Block 1 — Per-tier performance (12 rows)

| # | Row | Displayed | Artifact | Verified | Status |
|---|---|---|---|---|---|
| 11 | l1 easy recall | `n/a · n_neg=221`, no bar | value 0.0, `resolvable:false`, n_neg 221 | ✓ | **VERIFIED UNRESOLVABLE** |
| 12 | l1 medium recall | `n/a · n_neg=221`, no bar | 0.9729, `resolvable:false` | ✓ | VERIFIED UNRESOLVABLE |
| 13 | l1 hard recall | `n/a · n_neg=316`, no bar | 0.7317, `resolvable:false` | ✓ | VERIFIED UNRESOLVABLE |
| 14 | l1 evasive recall | `n/a · n_neg=221`, no bar | 0.3905, `resolvable:false` | ✓ | VERIFIED UNRESOLVABLE (wrong split — M-016) |
| 15–18 | B0 easy/med/hard/evasive recall | 4× `n/a`, no bar | 0.9967/0.9854/0.1254/0.2840, all `resolvable:false` | ✓ | VERIFIED UNRESOLVABLE |
| 19 | l1 easy AP | `0.789`, bar 78.9228% | `ap_raw` 0.789228 | ✓ | **INCORRECTLY REPRESENTED** (M-001) |
| 20 | l1 medium AP | `0.998`, bar 99.7585% | `ap_raw` 0.997585 | ✓ | INCORRECTLY REPRESENTED (M-001) |
| 21 | l1 hard AP | `0.935`, bar 93.4856% | `ap_raw` 0.934856 | ✓ | INCORRECTLY REPRESENTED (M-001) |
| 22 | l1 evasive AP | `0.814`, bar 81.3749% | `ap_raw` 0.813749 | ✓ | INCORRECTLY REPRESENTED (M-001) |
| 23 | tier prevalence ×4 | **not shown** | `prevalence` 0.731/0.685/0.476/0.433 | ✓ | **FRONTEND MISSING** — spec-mandated (M-001) |
| 24 | `ap_at_eval_prevalence` ×4 | **not shown** | 0.0178/0.9782/0.7438/0.4105 | ✓ | **FRONTEND MISSING** (M-001) |
| 25 | B0 per-tier AP ×4 | **not shown** | 0.9998/0.9987/0.9815/0.9583 | ✓ | **FRONTEND MISSING** (M-002) |
| 26 | tier `n` ×4 | not shown | 821/701/603/390 | ✓ | FRONTEND MISSING (minor) |

### Block 2 — Negative controls (28 rows × 4 columns)

| # | Metric | Displayed | Verified | Status |
|---|---|---|---|---|
| 27 | 7 scenarios × 4 sanity scorers | e.g. `cgnat/perfect 0/1, 0/500` | ✓ all 28 rows match artifact | VERIFIED CORRECT |
| 28 | episode denominator | `1` for all 28 rows | ✓ `len(flagged_by_episode)` = 1 | **SUSPICIOUS-LEGITIMATE** (M-017) |
| 29 | `shared_ip_legit` attempts | `0/1` | ✓ 1 legitimate sample | **SUSPICIOUS-LEGITIMATE** (M-017) |
| 30 | `retry_storm` attempts | `0/5` | ✓ 5 legitimate samples | SUSPICIOUS-LEGITIMATE (M-017) |
| 31 | model / B0 FP rows | **absent entirely** | ✓ generator emits sanity scorers only | **BACKEND MISSING** (M-007) |
| 32 | θ_challenge threshold | not shown | `THETA_CHALLENGE = 0.257` hardcoded | **HARDCODED** (M-020) |

### Block 3 — Discriminability audit (24 rows)

| # | Metric | Displayed | Verified | Status |
|---|---|---|---|---|
| 33 | 6 flagged features | 0.998→0.990, amber, `FLAGGED — GENERATOR ARTIFACT` | ✓ bar widths = AUC to 4 dp | VERIFIED CORRECT |
| 34 | 2 real features | 0.711, 0.711 | ✓ | VERIFIED CORRECT |
| 35 | **14 constant features** | `0.500`, identical 50% grey bars | ✓ AUC=0.5 is the tie-degenerate value | **INCORRECTLY REPRESENTED** (M-006) |
| 36 | 2 inverted features | 0.289, 0.225, smallest bars, sorted last | ✓ | **INCORRECTLY REPRESENTED** (M-013) |
| 37 | threshold rule | 0.95, at 95% of every track | ✓ position exact | VERIFIED CORRECT / **HARDCODED** (M-012) |
| 38 | `constant: true` flag | **not shown** (14 features) | ✓ in artifact | **FRONTEND MISSING** (M-006) |
| 39 | `reason` string | **not shown** (24 features) | ✓ in artifact, test-asserted | **FRONTEND MISSING** (M-006) |
| 40 | `max_univariate_auc` | not shown (0.95 hardcoded instead) | ✓ field is the *threshold*, real max = 0.9976 | **SPECIFICATION MISMATCH** (M-011) |

### Block 4 — Cost curves

| # | Metric | Displayed | Recomputed independently | Status |
|---|---|---|---|---|
| 41 | rupee gap | `₹0` | 27616.67885881492 − 27616.67885881492 = **0.0** ✓ | **VERIFIED CORRECT** (structurally forced — M-039) |
| 42 | regime-switch saving | `₹232,145` / `₹2,32,145` | 24855010.972933434 − 1640502.7668777597 = **23214508.206055675** ✓ | **VERIFIED CORRECT** (locale-dependent — M-014) |
| 43 | cost-optimal point | marker at FPR 0 | argmin over `curve_pi0` = (0.0, 0.46891) ✓ | VERIFIED CORRECT / **invisible** (M-004) |
| 44 | F1-optimal point | label only | argmax F1 @ π₀ = (0.0, 0.46891), F1 = 0.638446 ✓ | VERIFIED CORRECT / line suppressed |
| 45 | `curve_pi0` (10 pts) | solid polyline | all 10 reproduce `10000·(π(1−TPR)·5200 + (1−π)·FPR·1800)` ✓ | VERIFIED CORRECT / **sub-pixel** (M-003) |
| 46 | `curve_pi1` (10 pts) | dashed polyline | all 10 reproduce ✓ | VERIFIED CORRECT |
| 47 | ribbon π∈[1e-4,1e-2] | filled band | ✓ values correct | **INCORRECTLY REPRESENTED** — self-intersecting (M-005) |
| 48 | C_FN | not shown | 200 + 5000 = 5200 ✓ = `inputs.c_fn_minor` | VERIFIED CORRECT |
| 49 | C_FP(challenge) | not shown | 120000 × 0.30 × 0.05 = 1800.0 ✓ | VERIFIED CORRECT |
| 50 | π₀ / π₁ on axis | `π₀=0.001 · π₁=0.9` | matches `b4.pi0`/`b4.pi1` | **HARDCODED** in JSX (M-021) |
| 51 | series / tier / split | **not shown** | `l1-lgbm-v1` / `challenge` / `temporal_test` | FRONTEND MISSING (M-037) |

### Block 5 — Calibration (2 rows × 4 columns)

| # | Metric | Displayed | Verified | Status |
|---|---|---|---|---|
| 52–55 | π₀ row | 0.0108 / 0.0007 / 0.0703 / 0.0007 | ✓ ECE recomputed from artifact's own reliability bins = 0.0007305349 (exact) | VERIFIED CORRECT |
| 56–59 | π₁ row | 0.3413 / 0.2020 / 0.3955 / 0.2807 | ✓ ECE recomputed = 0.2806765621 (exact) | VERIFIED CORRECT |
| 60 | `brier_raw` | **not shown** | 0.1193 / 0.1403 in artifact | **FRONTEND MISSING** — spec-mandated (M-010) |
| 61 | ECE raw | **not shown** | **never computed by backend** | **BACKEND MISSING** (M-010) |
| 62 | reliability diagrams | **not shown** | 2 × 10 bins fully computed | **FRONTEND MISSING** — spec-mandated (M-010) |
| 63 | `effective_n` | not shown | 759.5 / 1650.9 | FRONTEND MISSING (M-022) |
| 64 | `pi_t`, `raw_prevalence`, `n`, `n_bins` | not shown | 0.7251 / 0.6433 / 2125 / 10 | FRONTEND MISSING (minor) |
| 65 | regime labels | `π₀ = 0.001` / `π₁ = 0.9` | correct but **hardcoded strings** | HARDCODED (M-021) |

### Block 6 — Baseline comparison (4 rows)

| # | Metric | Displayed | Verified | Status |
|---|---|---|---|---|
| 66 | B0 recall | `recall n/a · n_neg=758`, no bar | value 0.7769, `resolvable:false` ✓ | VERIFIED UNRESOLVABLE (wraps — M-026) |
| 67 | B0 AP | `AP 0.997`, bar 99.6962% | 0.9969616 ✓ | VERIFIED CORRECT |
| 68 | B1 TPR | `TPR 0.075`, bar 7.53475% | 103/(103+1264) = 0.0753475 ✓ | VERIFIED CORRECT |
| 69 | B2 TPR | `TPR 0.718`, bar 71.8361% | 982/(982+385) = 0.7183614 ✓ | VERIFIED CORRECT |
| 70 | model row | **absent** | not in artifact | **BACKEND MISSING** — spec-mandated (M-008) |
| 71 | B3 sanity floor | **absent** | `sanity_recall_at_b*_fpr` in artifact | **FRONTEND MISSING** — spec-mandated (M-008) |
| 72 | per-tier baselines | **absent** | not in artifact | **BACKEND MISSING** — spec-mandated (M-008) |
| 73 | B0 `roc_auc` | not shown | 0.9943 | FRONTEND MISSING (M-002) |
| 74 | B1/B2 confusion matrix | not shown | tp/fp/tn/fn all present | FRONTEND MISSING (minor) |
| 75 | B2/B1 caption | shown | ✓ **verified accurate** against `eval/baselines.py` | VERIFIED CORRECT |

### Footer

| # | Metric | Displayed | Verified | Status |
|---|---|---|---|---|
| 76 | Tier E split n | `390` | = `block1.evasive.n` ✓ | VERIFIED CORRECT |
| 77 | Tier E prevalence | `0.433` | 0.43333 ✓ | VERIFIED CORRECT |
| 78 | converged params | `77 IPs, 19 BINs, 866/h` | from `config/attack_tiers.yaml:evasive` ✓ | VERIFIED CORRECT |
| 79 | `distinct_cards`, `episode_duration_s`, `amount_quantile_band` | not shown | 286 / 704 / [0,26] | FRONTEND MISSING (minor) |

**Totals:** 79 inventoried values — **34 verified correct**, **9 verified unresolvable**,
**0 incorrect renderings of a displayed field**, **6 incorrectly represented**,
**23 present in the artifact but never rendered**, **4 missing from the backend**,
**3 hardcoded in the frontend**.

---

## 5. Missing / Unavailable Values

### 5.1 Correctly unresolvable (9 values) — the page's best work

All eight per-tier `recall @ FPR 1e-3` figures plus B0's overall recall carry
`resolvable: false`. **This is mathematically correct and I verified the arithmetic:**

`eval/metrics.py:recall_at_fpr` sets `resolvable = n_neg >= 1/target_fpr`. At
`target_fpr = 1e-3` that requires **1000 negatives**. The splits carry:

| Split | n | prevalence | n_neg | ≥ 1000? |
|---|---:|---:|---:|:---:|
| temporal_test · easy | 821 | 0.7308 | **221** | no |
| temporal_test · medium | 701 | 0.6847 | **221** | no |
| temporal_test · hard | 603 | 0.4760 | **316** | no |
| tier_e · evasive | 390 | 0.4333 | **221** | no |
| temporal_test (all, B0) | 2125 | 0.6433 | **758** | no |

Cross-check: 821 + 701 + 603 = **2125** = `block5.n` = `b0.n`. 221 + 221 + 316 = **758** =
`b0.recall_at_target_fpr.n_neg`. Internally consistent to the sample.

Empirical FPR is quantised at 1/n_neg. With 221 negatives the finest achievable non-zero
FPR is 0.00452 — 4.5× the 1e-3 target. **The metric genuinely cannot be resolved.** The UI
prints `n/a · n_neg=221` and draws no bar. This is classification **A — correctly
unresolvable**, and it is the right call. Answering the brief's §9 test directly: there are
*not* sufficient negatives, so `resolvable:false` is not a defect.

Note the artifact still stores a `value` (e.g. B0 = 0.7769) — deliberately, so the report
can distinguish "unreachable" from "measured but unresolvable". The UI correctly refuses to
print it.

### 5.2 Incorrectly missing (23 values) — the page's worst work

Every one of these is **computed, serialised into the artifact, and thrown away by the
frontend**. None is a backend gap; all are classification **D/E — frontend mapping**.

| Value | Artifact path | Why it matters |
|---|---|---|
| tier prevalence ×4 | `block1_per_tier.*.*.prevalence` | **Spec-mandated.** Without it AP is uninterpretable (M-001) |
| `ap_at_eval_prevalence` ×4 | `block1_per_tier.l1-lgbm-v1.*.ap_at_eval_prevalence` | **Spec-mandated.** The comparable figure (M-001) |
| B0 per-tier AP ×4 | `block1_per_tier.rules-only-v0.*.ap_raw` | Reveals B0 > model on all 4 tiers (M-002) |
| `brier_raw` ×2 | `block5_calibration.pi*.brier_raw` | **Spec-mandated** {raw, Platt, Platt+prior} (M-010) |
| reliability bins ×20 | `block5_calibration.reliability_pi*` | **Spec-mandated** reliability diagram (M-010) |
| `sanity_recall_at_b1/b2_fpr` | `block6_baselines.*` | **Spec-mandated** B3 sanity floor (M-008) |
| B0 `roc_auc` | `block6_baselines.b0.roc_auc` = 0.9943 | The headline comparison number (M-002) |
| `policy_version`, `eval_prevalence`, split | `provenance.*`, `block4_cost.split` | **Spec-mandated** — 3 of the 6 §9 attributes (M-009) |
| `seeds_used` = 1 | `provenance.seeds_used` | Every figure is a single-seed point estimate (M-022) |
| `constant` flag ×14 | `block3_audit.features.*.constant` | Turns a fake 0.500 into an honest "un-fed" (M-006) |
| `reason` ×24 | `block3_audit.features.*.reason` | The per-feature justification for each flag (M-006) |
| `effective_n` ×2 | `block5_calibration.pi*.effective_n` | 759.5 / 1650.9 vs nominal n=2125 (M-022) |

### 5.3 Missing from the backend (4 values)

| Value | Classification | Evidence |
|---|---|---|
| ECE for the **raw** (uncalibrated) scores | **B — backend missing** | `eval/harness.py:_regime` computes `brier_raw` but no `ece_raw`. Eval Protocol §3.4 requires the ECE comparison |
| Model FP rows in Block 2 | **B — backend missing** | `eval/d6.py:_block2_negative_controls` iterates only `PerfectScorer, RandomScorer, InvertedScorer, AlwaysPositiveScorer` (M-007) |
| Model row in Block 6 | **B — backend missing** | `_block6_baselines` emits `b0/b1/b2/sanity_*` only — no `l1-lgbm-v1` entry (M-008) |
| Per-tier B1/B2 | **B — backend missing** | `baseline_summary` carries one overall operating point per baseline (M-008) |

### 5.4 Incorrectly represented (6 values)

| Value | Shown as | Should be |
|---|---|---|
| 14 un-fed constant features | `0.500` + a real 50% bar | "no measurement — feature never populated" (M-006) |
| 2 inverted features (0.289, 0.225) | Weakest bars, sorted last, unflagged | \|AUC − 0.5\| ranking; both are *more* separable than 0.711 (M-013) |
| `ap_raw` ×4 | Bare 0–1 bars implying "fraction of perfect" | Lift over the prevalence baseline (M-001) |
| 8 unresolvable recalls | Full-width grey track that reads as a filled bar | Visually distinct null state (M-028) |
| `episodes` = 1 | Fraction `0/1`, `1/1` | A boolean, or suppressed as under-powered (M-017) |
| ₹ gap `₹0` | An empirical finding | A structural consequence of F1 at π=0.001 (M-039) |

### 5.5 Unverified (2)

- **The corpus-level provenance of the numbers.** I did not re-run `eval.harness` — doing
  so would overwrite `eval/outputs/d6.json`, which the read-only constraint forbids. So
  "does the artifact actually reflect `data/corpus/tollgate.db` + `models/l1-lgbm-v1`" is
  **UNVERIFIED**. Everything downstream of the artifact is verified.
- **`sanity_recall_at_*.always_positive: null`.** Correct per `recall_at_fpr`'s
  "unreachable" branch (a constant scorer has ≤2 distinct ROC points), but never rendered,
  so its display behaviour is untested.

---

## 6. Numerical Correctness — independent recomputation

Recomputed **from `config/cost_model.yaml`**, not from the artifact:

```
C_FN            = auth_fee_minor + downstream_exposure_minor = 200 + 5000 = 5200      ✓
C_FP(challenge) = aov_minor × margin_pct × P(abandon|challenge)
                = 120000 × 0.30 × 0.05                       = 1800.0                 ✓
cost(TPR,FPR,π) = 10000 × (π(1−TPR)·C_FN + (1−π)·FPR·C_FP)
```

| Quantity | Artifact | Independently recomputed | Δ |
|---|---|---|---|
| all 10 `curve_pi0` costs | — | reproduce exactly | **0** |
| all 10 `curve_pi1` costs | — | reproduce exactly | **0** |
| cost-optimal | (0.0, 0.46891, 27616.67885881492) | argmin → identical | **0** |
| F1-optimal | (0.0, 0.46891), F1 0.6384462151394422 | argmax → identical | **0** |
| `rupee_gap_minor` | 0.0 | 27616.678858… − 27616.678858… = 0.0 | **0** |
| stay-cost @ π₁ | — | 24855010.972933434 | — |
| π₁-optimal | (0.87335, 0.99854, 1640502.7668777597) | argmin → identical | **0** |
| `regime_switch_saving_minor` | 23214508.206055675 | 24855010.972933434 − 1640502.7668777597 = 23214508.206055675 | **0** |
| displayed rupees | ₹232,145 | round(23214508.2061 / 100) = 232145 | **0** |
| ECE(Platt+prior) @ π₀ | 0.0007305349387266664 | Σ (wᵢ/Σw)·\|pred−obs\| over the artifact's bins = 0.0007305349 | **0** |
| ECE(Platt+prior) @ π₁ | 0.2806765620747161 | = 0.2806765621 | **0** |
| Wilson CI upper, 0/221 | 0.017085189007591345 | z=1.95996, 0/221 → 0.017085189 | **0** |
| n_neg per tier | 221/221/316 | n×(1−prevalence) → 221/221/316 | **0** |
| Σ tier n | — | 821+701+603 = 2125 = `block5.n` = `b0.n` | **0** |
| Σ tier n_neg | — | 221+221+316 = 758 = `b0.n_neg` | **0** |
| all bar widths | — | `width%` = value×100 to 4 dp on all 24 audit + 8 metric bars | **0** |

**Zero calculation errors.** Formulae in `eval/metrics.py` (Wilson, rank-based AP,
Mann-Whitney AUC, prevalence reweighting, ECE, reliability bins) match their documented
definitions. `roc_convex_hull` is a correct monotone-chain upper hull. Rounding is
display-only (`toFixed(3)` / `toFixed(4)`); no premature rounding in the pipeline.

The **only** numeric-formatting defect is locale (M-014).

---

## 7. Backend ↔ Frontend Consistency

**Matching (100% of rendered values).** Every DOM string equals the artifact field it
claims. No stale value, no wrong field mapping, no divergent denominator, no frontend
recomputation of a backend metric.

**Duplicated logic — 3 sites, all currently agreeing, all able to drift:**

| # | Backend / config | Frontend | Agree today? |
|---|---|---|---|
| 1 | `config/features.yaml: audit.max_univariate_auc = 0.95` → `block3_audit.max_univariate_auc` | `AuditBars.jsx: const THRESHOLD = 0.95` | ✓ (M-012) |
| 2 | `block3_audit.features.*.flagged` | `AuditBars.jsx` recomputes `auc >= 0.95 \|\| excluded` | ✓ all 24 (M-012) |
| 3 | `block4_cost.pi0 = 0.001`, `pi1 = 0.9` | hardcoded in `CostCurve` axis label **and** `Block5` row labels | ✓ (M-021) |

A fourth is backend-internal: `eval/report.py: THETA_CHALLENGE = 0.257` is a rounded copy
of the cost model's derivable `1800/(1800+5200) = 0.2571428…` (M-020).

**Ignored API fields:** 23 (see §5.2). This is the dominant backend↔frontend problem —
not disagreement, but **selective consumption**.

---

## 8. Data Freshness / Staleness

**Type:** build-time-generated, committed artifact. Regenerated only by a human running
`python -m eval.harness` and committing the result.

| Check | Artifact | Now | Verdict |
|---|---|---|---|
| `config_hash` | `a7db8c6118…` | `a7db8c6118…` | ✅ **MATCH** — configs unchanged since generation |
| `fixture_sha256` | `5672a0e683…` | `5672a0e683…` | ✅ **MATCH** |
| `build_hash` | `9141a8ecc4…` | `36d0cc4817…` | ❌ **DIVERGED** |

`build_hash` covers `git rev-parse HEAD` + a dirty flag + two SHAs. HEAD has moved and the
tree is dirty (50+ modified files), so divergence is expected and the artifact is correctly
*labelled* with its generation build. **The defect is presentational:** the header prints
`build 9141a8ecc41b` with no temporal qualifier, and a reader reasonably takes it for the
build they are looking at. Worse, **the artifact carries no timestamp at all** — top-level
keys are `block1…block6, provenance, schema_version, tier_e`. There is no way, from the
page or the file, to learn how old the numbers are (M-029).

`test_d6_artifact.py` verifies the file exists and is not gitignored — a real and valuable
guard against the "renders on a dev machine, empty on a clean clone" failure — but nothing
guards against **stale**.

---

## 9. Hard-coded / Static Data

The whole page is intentionally static (App Flow §5 D6: "Static render. No live
computation on stage."), and that is a **correct, documented design decision**, not a
defect. What is not defensible is hardcoding values the artifact already carries:

| Hardcoded | File | Artifact has it? | Verdict |
|---|---|---|---|
| `THRESHOLD = 0.95` | `AuditBars.jsx:12` | yes — `block3_audit.max_univariate_auc` | **DEFECT** (M-012) |
| `flagged` recomputation | `AuditBars.jsx:18` | yes — `features.*.flagged` | **DEFECT** (M-012) |
| `"π₀ = 0.001 (steady state)"` | `D6Metrics.jsx:Block5` | yes — `block4_cost.pi0` | **DEFECT** (M-021) |
| `"π₁ = 0.9 (under attack)"` | `D6Metrics.jsx:Block5` | yes — `block4_cost.pi1` | **DEFECT** (M-021) |
| `π₀=0.001 · π₁=0.9` axis label | `CostCurve.jsx` | yes | **DEFECT** (M-021) |
| `THETA_CHALLENGE = 0.257` | `eval/report.py:26` | derivable from cost model | **DEFECT** (M-020) |
| `TIERS = [easy, medium, hard, evasive]` | `D6Metrics.jsx:14` | keys of `block1_per_tier.*` | acceptable — ordering is semantic |
| `W/H/M` SVG geometry | `CostCurve.jsx` | n/a | acceptable — layout constants |
| `C_FN = 5200`, `C_FP = 1800` | `test_d6_cost_gap.py` | n/a | **correct by design** — anti-circularity anchor |

No screenshot-derived or fabricated numbers were found anywhere.

---

## 10. Specification Cross-check

| Spec requirement | Source | Implemented? |
|---|---|---|
| "Static render. No live computation on stage." | App Flow §5 D6 | ✅ **PASS** for D6 itself; ⚠️ the shell keeps SSE + polling alive (M-031) |
| Six blocks in argument order | App Flow §5 D6 | ✅ **PASS** — all six, correct order |
| B1 "recall @ FPR = 0.001 … side by side" | App Flow §5 D6 #1 | ⚠️ present but all `n/a`; **the spec's grouped bars do not render** (M-015) |
| B1 "PR-AUC … with that tier's prevalence printed beside it" | App Flow §5 D6 #1 · Eval §2.1 | ❌ **FAIL** — prevalence never printed (M-001) |
| "every tier's eval set is resampled to π_eval = 0.01 … both raw and resampled prevalence appear" | Eval §2.1 | ❌ **FAIL** — only raw shown, neither prevalence shown (M-001) |
| "No metric is reported without the conditions under which it was measured" | Eval §1 | ❌ **FAIL** (M-001, M-009) |
| B2 negative controls, per named scenario | App Flow §5 D6 #2 · Eval §4/V4 | ⚠️ all 7 scenarios present; **scored by sanity scorers, not the system** (M-007) |
| B3 "univariate AUC per feature … above 0.95 flagged" | App Flow §5 D6 #3 · UIUX §6.13 | ✅ **PASS** — sorted desc, 0.95 rule, amber, correct copy |
| B4 curves at both regimes + ribbon + both optima + saving | App Flow §5 D6 #4 | ⚠️ all elements present in the DOM, **three of them not legible** (M-003/4/5) |
| B4 "rupee gap set between them" | UIUX §6.13 | ❌ markers coincide; gap rendered below the chart |
| B5 "reliability at both regimes; Brier and ECE for {raw, Platt, Platt+prior}" | App Flow §5 D6 #5 · Eval §3.4 | ❌ **FAIL** — no reliability diagram, no raw column (M-010) |
| B6 "naive velocity and BIN-concentration rule **beside the model, on every tier**" | App Flow §5 D6 #6 | ❌ **FAIL** — no model row, not per-tier (M-008) |
| "Every model number is reported beside four baselines" (B0/B1/B2/B3) | Eval §8 | ❌ **FAIL** — B3 absent (M-008) |
| "B2 shares R3's statistic … must not present B2 as independent of B0" | Eval §8 | ✅ **PASS** — caption verified accurate against `eval/baselines.py` |
| "B0 and B1 are not the same rule and are never reported as one" | Eval §8 | ✅ **PASS** — separate rows, caveat shown |
| "If the model only beats the naive baselines on the hard and evasive tiers, **that is the finding and it gets stated in that form**" | Eval §8 · Decisions.md | ❌ **FAIL** — the page omits every comparison that would state it (M-002) |
| "Every reported figure carries … `seed`, `config_hash`, `model_version`, `policy_version`, `π_eval`, and the split name. A number that cannot state those six things does not go on a slide." | Eval §9 | ❌ **FAIL** — 3 of 6 shown (M-009) |
| Evasive "no special treatment … simply the fourth bar" | UIUX §6.13 | ⚠️ styling honoured; **but it is a different split** (M-016) |
| Amber only here, meaning "measurement suspect" | UIUX §6.13 | ✅ **PASS** |
| `prefers-reduced-motion` block | UIUX §7 | ✅ **PASS** — present in `base.css:28` |

**Score: 7 pass, 5 partial, 8 fail.**

---

## 11. API Contract

**There is no HTTP API for the Metrics page.** The contract is the JSON schema of
`eval/outputs/d6.json`, `schema_version: 1`.

- **No schema validation** anywhere — not at generation, not at build, not at render.
  `test_d6_artifact.py` checks presence and non-emptiness of 6 blocks + 8 provenance
  fields; it does not validate types, nullability, or the ~200 leaf fields the UI reads.
- **Nullability is inconsistently modelled.** `recall_at_target_fpr` is a rich object with
  an explicit `resolvable` flag (excellent). `ap_raw` is a bare `float | absent`.
  `sanity_recall_at_*.always_positive` is a bare `null` with no accompanying reason.
  Three different conventions for "we don't know".
- **`max_univariate_auc` is misnamed** — it is the configured *threshold* (0.95), not the
  maximum observed AUC (0.9976). `test_d6_artifact.py:82` asserts it non-null in a test
  named "carries the univariate_auc table", reinforcing the misreading (M-011).
- **23 fields are emitted and never consumed** (§5.2). Not a contract error, but the
  artifact's surface area is ~2× what the UI uses, with no marker of which is which.
- **`schema_version` is never checked by the frontend.** A v2 artifact would render
  silently or crash, depending on which key moved.

---

## 12. Loading / Error States

**Loading:** none, and none needed. The artifact is a synchronous ES-module import; the
component renders complete on first paint. **No misleading zeros, no partial data, no
layout shift from data arrival.** This is a genuine benefit of the static design.

One real transient: web fonts load asynchronously (`IBM Plex Mono` observed as
`unloaded → loaded` per weight). During the fallback window monospace label widths differ,
which worsens the Block 3 overflow (M-025) before settling.

**Error handling: absent.** There is **no React error boundary anywhere in the dashboard**
(`grep` for `componentDidCatch|ErrorBoundary|getDerivedStateFromError` → no matches). Five
of six blocks dereference artifact fields with no guard:

| Expression | File | Missing field → |
|---|---|---|
| `d6.provenance.build_hash?.slice(0,12)` | `D6Metrics.jsx` | `provenance` absent → **TypeError** (the `?.` guards the wrong level) |
| `Object.entries(d6.block2_negative_controls)` | `Block2` | absent → **TypeError** |
| `d6.block3_audit.features \|\| {}` | `D6Metrics.jsx` | `block3_audit` absent → **TypeError** |
| `b4.curve_pi0`, `b4.ribbon[0].curve` | `CostCurve` | absent/empty → **TypeError** |
| `const b = d6.block6_baselines; b.b0` | `Block6` | absent → **TypeError** |
| `if (!cb \|\| !cb.pi0) return <p>not measured…` | `Block5` | ✅ **the only guarded block** |
| `d6.tier_e \|\| {}` | footer | ✅ guarded |

Any one of these throws during render, and with no boundary React unmounts the **entire
application** — the whole dashboard goes blank, not just the Metrics section (M-019).

Mitigating: because the import is build-time, a *missing* file fails the Vite build rather
than shipping a broken page, and `test_d6_artifact.py` guards the gitignore trap. The
exposure is to a **malformed or version-skewed** artifact, not an absent one.

**Backend unavailable:** D6 itself is unaffected (no network dependency) — a genuine
strength. The shell's SSE/polling failures surface in the nav (`SSE: …`) and do not touch
the Metrics content.

---

## 13. Edge Cases

| Case | Handling | Verdict |
|---|---|---|
| No positives / no negatives | `_degenerate()` → `None`, never `0.0` | ✅ **excellent** — documented as F1 |
| n_neg < 1/target_fpr | `resolvable: false` | ✅ **excellent** (§5.1) |
| Scorer with ≤2 distinct ROC points | `value: None` ("unreachable") | ✅ correct, distinguished from a real 0.0 |
| 0 observed FPs | one-sided Wilson `[0, 0.0171]`, not `[0,0]` | ✅ verified, test-covered |
| Constant feature | AUC → 0.5 by tie convention | ⚠️ **mathematically right, presented as a measurement** (M-006) |
| AUC exactly 0.95 | `>= THRESHOLD` → flagged | ✅ boundary inclusive, consistent with config |
| AUC below 0.5 | never flagged | ❌ **one-sided rule** (M-013) |
| Division by zero in precision | `denom > 0 ? … : 0.0` | ✅ guarded |
| `max <= 0` in BarRow | `frac = 0` | ✅ guarded |
| Empty bin in reliability | `mean_predicted: null`, weight 0, skipped in ECE | ✅ correct — 6 of 20 bins are empty |
| Single-episode scenario | `episodes: 1` → `0/1` | ⚠️ correct arithmetic, under-powered (M-017) |
| `n = 1` negative control | `shared_ip_legit` → `0/1` | ⚠️ statistically vacuous (M-017) |
| F1 optima coincide | `coincident` branch, explanatory caption | ✅ handled, and the caption is accurate |
| NaN / Infinity | not reachable — all inputs are bounded rationals | ✅ |
| Curves crossing in the ribbon | **unhandled** → self-intersecting polygon | ❌ (M-005) |
| Two series 900× apart on one axis | **unhandled** → shared linear scale | ❌ (M-003) |

---

## 14. Performance

Measured on the live page at 1536×960:

| Metric | Value | Verdict |
|---|---|---|
| DOM nodes (total / `<main>`) | 491 / 445 | ✅ small |
| Network requests for metric data | **0** at runtime (build-time import) | ✅ ideal |
| Requests during 5 s idle on Metrics | **1** (`/v1/stream/recent`) | ⚠️ shell, not D6 (M-031) |
| Console errors / warnings | **0** | ✅ |
| 404 / 500 / CORS | **none** | ✅ |
| Artifact size | 26.9 KB → inlined into the bundle | ✅ negligible |
| Re-render triggers | D6 takes no props; re-renders when `App` re-renders from SSE | ⚠️ 24-row audit + SVG re-render on unrelated stream events (M-031) |
| Main-thread blocking | none observed | ✅ |

Performance is a strength. The one real cost is architectural: the Metrics screen keeps an
`EventSource` open and a 1 Hz `/v1/replay/status` poll armed while displaying data that
cannot change.

---

## 15. Security / Data Exposure

**No vulnerabilities found.**

| Surface | Finding |
|---|---|
| API keys / secrets | none — the page makes no authenticated request |
| Filesystem paths | ⚠️ in **dev only**, Vite serves `/@fs/D:/Projects/Tollgate/eval/outputs/d6.json`, leaking the absolute repo path. Not present in a production build. `vite.config.js` widens `server.fs.allow` to `["..","../.."]`, which is required for the import and is dev-server-only. **Informational.** |
| Raw exceptions | none surfaced (no error boundary means a crash blanks the page rather than printing a stack) |
| Build/config/seed/model hashes | **intentional** — Eval Protocol §9 requires them. Not a vulnerability |
| PII / cardholder data | none. Features are aggregates; `card_hash` never reaches the artifact |
| Merchant/customer identifiers | none |
| Internal spec IDs in UI copy | `UIUX v2 SS6.13`, `Eval Protocol SS4/V2` — cosmetic, not a security issue (M-032) |

---

## 16. Accessibility

| Check | Result |
|---|---|
| Heading hierarchy | ✅ clean `h1` → 6× `h2`, no skips |
| Landmarks | ✅ `<nav>`, `<main>` present |
| Contrast — `tg-label` 12px, `tg-body` 14px | ✅ **8.88:1** |
| Contrast — `tg-caption` 12px | ❌ **4.34:1** (AA needs 4.5:1) |
| Contrast — `tg-mono-caption` 11px (provenance line) | ❌ **4.34:1** |
| Contrast — `tg-mono-data` 13px (all `n/a · n_neg=` values) | ❌ **4.34:1** |
| Contrast — SVG axis labels | ❌ **4.34:1** |
| Contrast — SVG optima labels | ❌ **4.36:1** |
| Contrast — `FLAGGED` amber | ✅ 10.00:1 |
| Contrast — "not resolvable…" in-track label | ✅ 19.19:1 |
| Table `<th scope>` | ❌ **absent on all 9 headers**, both tables |
| Table `<caption>` | ❌ absent on both |
| Blank scenario cells | ❌ empty `<td>` used as visual rowspan — a screen reader reads 21 rows with no scenario |
| Bar rows semantics | ❌ `<div>` grids; label and value are unassociated siblings. 32 bars, no `role`, no `aria-label` |
| SVG | ⚠️ `role="img"` + `aria-label` present; **no `<title>`/`<desc>`**, no data-table alternative. Both ₹ headlines are real text, which partly mitigates |
| Threshold rule | ✅ correctly `aria-hidden="true"` |
| Nav active state | ❌ no `aria-current`; conveyed by colour + 2px border only |
| Focus / keyboard | ⚠️ **0 focusable elements in `<main>`** — content is static, so nothing is trappable, but nothing is reachable either |
| Status by colour alone | ✅ `FLAGGED — GENERATOR ARTIFACT` is text, not just amber |
| Reduced motion | ✅ honoured globally |

---

## 17. Responsive Design

No `@media` query exists anywhere in `services/dashboard/src/styles/` except
`prefers-reduced-motion`. Layout is **fixed-column at every width**:
`gridTemplateColumns: "200px 1fr 168px"` (BarRow) and `"200px 1fr 64px"` (AuditBars), in a
`maxWidth: 900` container.

Measured by progressively constraining the container:

| Container | Bar track | Table | SVG | Verdict |
|---:|---:|---:|---:|---|
| 900 (default) | 508 px | 852 | 852×426 | ✅ intended |
| 1024 | 688 px | 976 | 976×488 | ✅ |
| 768 | 432 px | 720 | 720×360 | ✅ |
| 600 | 264 px | 552 | 552×276 | ⚠️ bars cramped |
| 480 | **144 px** | 432 | 432×216 | ❌ a 0.5 bar is 72 px |
| 390 | **54 px** | **429 (overflows by 39)** | 342×171 | ❌ **broken** |

At 390 px the 200 px label and 168 px value columns consume 368 px of a 342 px grid, so the
data-bearing element — the bar — is squeezed to 54 px while the chrome keeps full width.
The tables have **no `overflow-x` container**, so they overflow the document horizontally.
The SVG scales proportionally, taking its `font-size="9"` labels to ~5.9 effective px.

At 1536 px the opposite problem: `maxWidth: 900` leaves **~40% of the viewport empty**
while Block 3's label column is simultaneously too narrow for its longest feature name.

**Sticky bottom control strip (§33): PASS.** Measured at maximum scroll —
`position: sticky`, 56 px tall, top at y=512 in a 568 px viewport; last content ends at
y=476. **Gap: 36 px. No content is hidden.** All six sections and the Tier E footer are
fully reachable.

---

## 18. UI / UX / Professionalism

### 18.1 What works

- Restrained, coherent dark palette with real design tokens.
- Grey-by-default series colour; amber reserved for one meaning, and that meaning is stated.
- The `resolvable:false` treatment — no bar, muted text, in-track explanation — is a
  genuinely sophisticated piece of data-honesty design.
- Tabular figures (`tg-num`) prevent digit reflow.
- Clean heading hierarchy; the six-block argument order is legible.

### 18.2 Where it reads as unfinished

**"NOT RESOLVABLE AT THESE NEGATIVE COUNTS" × 8, stacked.**
*What the user sees:* eight consecutive full-width grey rectangles with identical caps-lock
text, then eight identical `n/a` values.
*Why it is weak:* the empty track is itself bar-shaped, so the null state reads as a 100%
bar; and repeating a 40-character sentence eight times turns a caveat into noise.
*Professional alternative:* one grouped null state — "recall @ FPR 1e-3 is unresolvable for
all tiers (n_neg 221–316 < 1000)" — stated once above a collapsed group.

**"FLAGGED — GENERATOR ARTIFACT" × 6, stacked at 12 px, overlapping the row above.**
*Why it is weak:* absolutely positioned at `top: -15px`, so each label sits in the previous
row's space; six repetitions of the same 27-character string in the same column.
*Alternative:* flag once as a group header ("6 features excluded — generator artifacts"),
then render each feature's own `reason`, which the artifact already carries.

**14 identical `0.500` bars.**
*Why it is weak:* more than half of Block 3 is a wall of visually identical rows conveying
"no information available", styled exactly like a measurement.

**Internal spec IDs in user-facing copy: `(UIUX v2 SS6.13)`, `(Eval Protocol SS4/V2)`.**
Note `SS` is a mangled `§`. This is build-log text in a product surface (M-032).

**Cost-curve label collisions.** `cost-optimal` and `F1-optimal` stack in the top-left
corner pointing at the y-axis; the rotated y-axis label is clipped at the top of the
viewBox; `false-positive rate (hull)` floats far below the plot.

**Inconsistent capitalization.** CSS uppercases group labels (`L1-LGBM-V1`,
`BRIER PLATT`) while the provenance line and the regime column stay lowercase.

**Inconsistent precision.** Blocks 1/3/6 use 3 decimals, Block 5 uses 4, Block 2 uses raw
integers, Tier E uses 3. No stated convention.

**No interpretation anywhere.** Block 5 presents ECE 0.3955 and ECE 0.0007 in identical
type with no units, no direction ("lower is better"), and no verdict — even though the Eval
Protocol says prior correction failing at π₁ means "it is broken and the test says so".

**Irrelevant chrome.** The Metrics screen carries the Stream Rail, the `CALM` threat band,
and the Demo Control Strip (`TIER / SPEED / Launch / Stop / Reset`) — live-monitoring
controls on a static evaluation report.

**`<title>` never changes** — the tab reads "Tollgate — Live Monitor" on the Metrics page.

---

## 19. Test Coverage

### 19.1 What exists

**Backend unit tests are genuinely good** — 25 tests across 6 files with real analytic
assertions: Wilson CI bracketing, degenerate→`None`, hull-minimum vs brute force, hull
convexity, B2 equals `distinct_cards_per_bin_5m` event-by-event, B1's 340 ms bitemporal
gap, planted-discriminator detection, prior correction reduces ECE at π₁.

**`test_d6_cost_gap.py` is the one real end-to-end numeric gate.** It recomputes
`f1_optimal`, `cost_optimal` and the rupee gap from the artifact's own curve *and*
independently from hardcoded `C_FN = 5200` / `C_FP = 1800` — a true anti-circularity anchor
that would fail if `cost_model.yaml` drifted from the artifact.

### 19.2 Gaps, ranked by risk

| # | Gap | Risk |
|---|---|---|
| 1 | **No JavaScript test infrastructure at all.** `package.json` has one script: `dev`. No runner, no `*.test.*`, no `*.spec.*` | **CRITICAL** — every rendering defect in this report is invisible to CI |
| 2 | The three "frontend" tests (`test_d6_static.py`, `test_ui_contracts.py::TestD6Resolvability`) are **Python `grep` over JSX source strings** — e.g. `assert "metric.resolvable === false" in src`. They never render a component or inspect a DOM node | **CRITICAL** — a passing suite proves only that a substring is present |
| 3 | **`regime_switch_saving_minor` — the ₹2,32,145 headline — is asserted only `>= 0`** | **HIGH** — the largest number on the page is effectively untested |
| 4 | No test asserts Block 1 renders `ap_at_eval_prevalence`, or prevalence, or B0's AP | **HIGH** — M-001 and M-002 are invisible |
| 5 | No test on any Block 1 / 5 / 6 artifact *value* — `test_d6_artifact.py` checks only presence and non-emptiness | **HIGH** |
| 6 | No test that `AuditBars.THRESHOLD` equals `block3_audit.max_univariate_auc` | MEDIUM — M-012 drift undetectable |
| 7 | No SVG geometry test — nothing checks a curve is visible, a marker is distinguishable, or a ribbon is non-self-intersecting | MEDIUM — M-003/4/5 undetectable |
| 8 | No error-state test — no malformed/partial-artifact fixture | MEDIUM — M-019 undetectable |
| 9 | No responsive or contrast test | MEDIUM — M-023/027 undetectable |
| 10 | No staleness test — nothing compares the artifact's provenance to the tree it renders in | MEDIUM — M-029 |
| 11 | No schema validation of the ~200 leaf fields | MEDIUM |
| 12 | No test that the 23 emitted-but-unrendered fields are either rendered or documented as intentionally omitted | LOW |

**A green suite does not indicate a correct Metrics page.** All backend tests and all D6
tests pass against an artifact whose most prominent numbers are, as displayed, misleading.

---

## 20. Detailed Findings

### METRICS-001 — Block 1 shows average precision at raw prevalence, with the prevalence omitted and the normalised figure discarded

**Severity:** CRITICAL · **Category:** DATA / FRONTEND / SPECIFICATION
**Location:** `services/dashboard/src/screens/D6Metrics.jsx:29-31` (`apMetric`), `:76-82`

**Expected.** Eval Protocol v2 §2.1: *"PR-AUC is reported within a tier, with that tier's
prevalence printed beside it, and every tier's eval set is resampled to a common evaluation
prevalence (π_eval = 0.01, stated)… Both the raw and resampled prevalence appear in the
report."* App Flow §5 D6 #1 repeats it. Eval Protocol §1: *"No metric is reported without
the conditions under which it was measured. For a rate metric that means the prevalence."*

**Actual.** `apMetric = (tm) => ({ value: tm.ap_raw, resolvable: true })`. The UI renders
`ap_raw` alone, as a 0–1 bar, under the label "average precision (resolvable)". No
prevalence is printed. `ap_at_eval_prevalence` — present for all four tiers — is never read.

**Impact.** AP's floor is the prevalence, so an AP without its prevalence is
uninterpretable, and these prevalences are very high (0.43–0.73):

| Tier | Prevalence | Displayed `ap_raw` | Trivial baseline | **Lift** | `ap_at_eval_prevalence` | Lift @ π=0.01 |
|---|---:|---:|---:|---:|---:|---:|
| easy | 0.7308 | **0.789** (79% bar) | 0.731 | **1.08×** | 0.0178 | **1.78×** |
| medium | 0.6847 | **0.998** (100% bar) | 0.685 | 1.46× | 0.9782 | **97.8×** |
| hard | 0.4760 | **0.935** (93% bar) | 0.476 | 1.96× | 0.7438 | 74.4× |
| evasive | 0.4333 | **0.814** (81% bar) | 0.433 | 1.88× | 0.4105 | 41.1× |

A viewer sees `easy 0.789` beside `medium 0.998` and concludes the model is good on easy
and excellent on medium. The truth is that on `easy` the model is **barely distinguishable
from a constant classifier**, while on `medium` it is genuinely excellent — a ~55×
difference in lift, rendered as a 21-percentage-point difference in bar length. This is
precisely the failure mode Eval Protocol §2.1 exists to prevent, occurring on the page that
cites it. `Decisions.md` independently confirms the model "is weaker than B0 overall … and
on easy".

**Reproduction.** Open `http://localhost:5174` → Metrics → Section 1, third group.
Compare against `eval/outputs/d6.json → block1_per_tier["l1-lgbm-v1"]`.

**Evidence.** DOM: `easy | 0.789 | fillW 78.9228%`. Artifact: `ap_raw: 0.789228046757773`,
`prevalence: 0.730816077953715`, `ap_at_eval_prevalence: 0.01783008837101664`.

**Root cause.** Frontend field selection. The backend computes and serialises everything
required (`eval/metrics.py:ap_at_prevalence`, `eval/d6.py:_block1_per_tier`).

**Correct behaviour.** Render `ap_at_eval_prevalence` as the comparable series (with the
π_eval = 0.01 floor marked), show `ap_raw` beside it, and print each tier's raw prevalence
in the row — exactly what §2.1 asks for.

---

### METRICS-002 — Block 1 omits B0's per-tier AP, the only comparison that shows the baseline beating the model

**Severity:** CRITICAL · **Category:** DATA / FRONTEND / SPECIFICATION
**Location:** `D6Metrics.jsx:Block1` — `apMetric` is applied only to `model`, never to `b0`

**Expected.** Eval Protocol §8: *"Every model number is reported beside four baselines"*
and *"If the model only beats the naive baselines on the hard and evasive tiers, that is the
finding and it gets stated in that form."* `Decisions.md` (Decision 43 trade-off) commits
in writing: *"It is weaker than B0 overall (temporal_test ROC-AUC 0.889 vs 0.994) and on
easy, but competitive on medium … and decisively better on hard … **Reported 'in exactly
that form' (Eval Protocol §8)**."*

**Actual.** Block 1 renders B0's four **recall** bars — all `n/a`, therefore carrying no
information — and does not render B0's four **AP** values, which do:

| Tier | l1-lgbm-v1 `ap_raw` (shown) | rules-only-v0 `ap_raw` (**not shown**) | Winner |
|---|---:|---:|---|
| easy | 0.789 | **0.9998** | B0 |
| medium | 0.998 | **0.9987** | B0 |
| hard | 0.935 | **0.9815** | B0 |
| evasive | 0.814 | **0.9583** | B0 |

**The rules baseline beats the learned model on all four tiers**, and every number needed to
show it is in the artifact the page already imports. `b0.roc_auc = 0.9943` is likewise
present and unrendered.

**Impact.** Combined with METRICS-001, the net effect is that the *only* quantitative
model-vs-baseline comparison a reader can make on this page is one the project's own
decision record says should show the model losing — and it is absent. The section that
would carry it (Block 6, "Baseline comparison") has no model row at all (METRICS-008). The
page presents a systematically favourable subset of a correct and candid artifact.

**Reproduction.** Section 1 renders three groups: `l1-lgbm-v1` recall, `B0 — live rules`
recall, `l1-lgbm-v1 — average precision`. There is no fourth group.

**Root cause.** `Block1` calls `apMetric(model[t])` inside one `TIERS.map`; there is no
corresponding `apMetric(b0[t])` loop.

**Correct behaviour.** Render B0's AP series beside the model's, per tier, and state the
finding in the form Decision 43 commits to.

---

### METRICS-003 — Cost curve: the entire decision-relevant region renders sub-pixel

**Severity:** HIGH · **Category:** UI/UX / DATA VISUALISATION
**Location:** `services/dashboard/src/components/charts/CostCurve.jsx:32-38`

**Expected.** The cost-optimal minimum is the point that defines both headline ₹ figures. It
must be visible and locatable.

**Actual.** `maxCost` is taken across `curve_pi0 ∪ curve_pi1 ∪ ribbon`. `curve_pi1` peaks at
**₹46,800,000**; `curve_pi0` peaks at ₹52,000 — a **900× ratio** — and both are plotted on
one linear y-axis. Computed and confirmed against the rendered DOM (viewBox 520×260,
inner plot 360×204, baseline y = 220):

| π₀ point | cost | y | px above baseline |
|---|---:|---:|---:|
| (0.0, 0.0) | 52,000 | 219.773 | **0.227** |
| **(0.0, 0.4689) ← cost-optimal** | **27,617** | **219.880** | **0.120** |
| (0.0013, 0.4974) | 49,856 | 219.783 | **0.217** |

All three sit within **0.107 px of each other vertically** and within **0.5 px
horizontally** (x = 64.0, 64.0, 64.5), because the x-axis is linear in FPR over [0,1] while
every operating point worth choosing lives in FPR ≤ 0.0013. The chart devotes **99.9% of
its width and 99.95% of its height** to a region no operator would select, and renders the
minimum as a sub-pixel artefact indistinguishable from the axis.

**Impact.** The chart cannot be read for its purpose. A viewer sees a rising line, a falling
dashed line, and no minimum — while the caption below asserts two precise ₹ figures derived
from a point they cannot see.

**Reproduction.** Metrics → Section 4. The solid π₀ line leaves the origin flat.

**Evidence.** DOM `path` d-attribute begins `M64,219.97733 L64,219.98796 L64.47493,219.88511
L127.16623,206.22907 …`.

**Root cause.** Single shared linear scale for two series 900× apart, plus a linear FPR axis
over a range where the data occupies 0.13%.

**Correct behaviour.** Log or symlog y-axis; separate scales (twin axes or small multiples);
log/clipped FPR axis over [0, ~0.01]; and an explicitly marked minimum.

---

### METRICS-004 — Cost curve: the cost-optimal marker is drawn at the y-axis coordinates and is invisible

**Severity:** HIGH · **Category:** UI/UX
**Location:** `CostCurve.jsx:88-94`

**Expected.** UIUX §6.13: *"Two `--viz-threshold` markers … `F1-optimal` and
`cost-optimal`, with the rupee gap set between them."*

**Actual.** Both optima are at FPR = 0.0, so `cox = f1x = M.left = 64`. The marker line is
emitted as `x1=64 y1=16 x2=64 y2=220` — **byte-identical to the y-axis line** emitted four
lines earlier. `coincident` is true, so F1-optimal's line is suppressed, yet **its text
label is still rendered** at `(67, 38)`. The result is two labels stacked in the top-left
corner both pointing at what looks like a purple-tinted y-axis, and no "between them" for
the rupee gap to occupy.

**Impact.** The two markers the section is built around are not perceivable as markers.

**Evidence.** All three `<line>` elements in the DOM:
```
64,16  -> 64,220   stroke=var(--viz-grid)        ← y-axis
64,220 -> 424,220  stroke=var(--viz-grid)        ← x-axis
64,16  -> 64,220   stroke=var(--viz-threshold)   ← cost-optimal (identical to y-axis)
```

**Root cause.** No offset/collision handling when an optimum lands on an axis; the
`coincident` branch suppresses the line but not the duplicate label.

**Correct behaviour.** Offset markers off the axis, draw a point marker with a leader line
and callout, and collapse the two labels into one when coincident.

---

### METRICS-005 — Cost curve: the sensitivity ribbon self-intersects and is at most 2.2 px thick

**Severity:** HIGH · **Category:** UI/UX / DATA VISUALISATION
**Location:** `CostCurve.jsx:40-47`

**Expected.** UIUX §6.13 / App Flow §5 D6 #4: a `--viz-ribbon` band across π ∈ [1e-4, 1e-2].

**Actual.** The path is built as `lo` forward + `hi` reversed + `Z`, where `lo` is π=1e-4 and
`hi` is π=1e-2. **These two curves cross.** At FPR = 0 the FN term dominates and `hi` is
above `lo`; at FPR = 1 the FP term dominates and `lo` is above `hi`. Computed band thickness
across the ten hull vertices:

```
+2.244, +1.192, +1.127, +0.389, −0.067, −0.315, −0.457, −0.675, −0.776, −0.777  (px)
```

The sign flips at ~FPR 0.30, producing a **self-intersecting bowtie polygon** filled under
the default `nonzero` fill-rule — a shape with no defined meaning. Maximum thickness
anywhere is **2.24 px** in a 204 px plot (1.1%).

**Impact.** The prevalence sensitivity band — one of the section's three specified elements
— is invisible in practice and geometrically wrong where it renders. Confirmed by
inspection: no band is discernible on screen.

**Evidence.** DOM ribbon path shows the forward pass reaching `424,141.546` and the reverse
pass starting `424,142.323` — reversed ordering at the right terminus.

**Root cause.** Band construction assumes non-crossing envelopes; the shared axis scale
(METRICS-003) then compresses it to ~1% of plot height.

**Correct behaviour.** Compute per-x min/max across all ribbon π values rather than assuming
first/last bound the family, and render on a scale where the band has extent.

---

### METRICS-006 — 14 un-fed constant features render as measured AUC 0.500 with real bars

**Severity:** HIGH · **Category:** DATA / FRONTEND
**Location:** `services/dashboard/src/components/charts/AuditBars.jsx:16-22`

**Expected.** A feature that is constant has **undefined** discriminability. `Decisions.md`
Decision 43 establishes these as *"un-fed slots"* emitting a neutral placeholder — and
records that the model runs on **4 live features** out of 24.

**Actual.** `eval/metrics.py:roc_auc` resolves all-tied scores to exactly 0.5 (correct by
the tie convention). The artifact records `constant: true` and
`reason: "constant 0.0 -- un-fed slot, Decision 43"` for each. **`AuditBars` reads neither
field.** All 14 render as `0.500` with a grey bar at exactly 50% width, typographically and
visually identical to a genuine measurement.

Fourteen of the twenty-four rows in the "Discriminability audit" — the section App Flow
calls *"the most persuasive thing on the screen … a test the author would fail if they were
cheating"* — are placeholders presented as measurements.

**Impact.** Directly the failure mode the brief's §12 names: *"A mathematically undefined
metric must not silently become zero."* Here it silently becomes 0.500. A reader concludes
the feature set contains 14 mediocre-but-real discriminators; in fact those slots are never
populated and the model runs on four features.

**Evidence.** DOM, 14 rows: `amount_percentile_vs_store auc=0.500 bar=50%
color=rgb(167,176,188)` … identical for `attempts_per_session`, `bin_is_foreign_issued`,
`clock_skew_s`, `decline_rate_per_ip_5m`, `distinct_cards_per_ip_5m_q`,
`distinct_cards_per_ipua_5m_q`, `event_id_reuse_count`, `foreign_bin_share_5m`,
`foreign_bin_share_sigma`, `invalid_cvv_share_ip_5m`, `outcome_coverage_ratio`,
`store_decline_rate_deviation_sigma`, `store_volume_deviation_sigma`.

**Root cause.** `AuditBars` maps only `univariate_auc` and `excluded`; `constant` and
`reason` are dropped. Note `test_discriminability_audit.py` explicitly asserts every
excluded feature *has* a reason — the backend contract is enforced, the frontend contract
is not.

**Correct behaviour.** Render constant features in a separate, visually distinct group with
no bar and the text "not fed — un-fed slot (Decision 43)", exactly as `BarRow` already does
for unresolvable recall.

---

### METRICS-007 — Block 2 reports false positives for four sanity scorers and none for the system

**Severity:** HIGH · **Category:** DATA / BACKEND / SPECIFICATION
**Location:** `eval/d6.py:_block2_negative_controls` (lines 137-146)

**Expected.** App Flow §5 D6 #2 and Eval Protocol §4/V4: per-scenario false-positive counts
on adversarial-but-legitimate traffic — the block that answers *"does Tollgate flag real
customers?"*. V4 names the NRI scenario specifically to stop `bin_is_foreign_issued`
becoming a free discriminator, which is a claim about **the model**.

**Actual.** The generator iterates a fixed list of four B3 sanity scorers —
`PerfectScorer, RandomScorer, InvertedScorer, AlwaysPositiveScorer`. **Neither
`l1-lgbm-v1` nor `rules-only-v0` appears in any of the 28 rows.**

**Impact.** A section titled "Negative-control false positives", presented as the
credibility exhibit for FP behaviour, contains **zero information about the product's false
positives**. The `perfect` rows are 0 by construction, the `inverted`/`always_positive` rows
are 100% by construction, and `random` is ~70% by construction. All 28 cells are
analytically predetermined; none is a measurement of the system.

**Reproduction.** Metrics → Section 2. The `scorer` column contains only `perfect`,
`random`, `inverted`, `always_positive`, repeated for all 7 scenarios.

**Root cause.** Backend — the artifact never carries model FP rows for negative controls.

**Correct behaviour.** Add `l1-lgbm-v1` and `rules-only-v0` rows per scenario at
θ_challenge, and keep the sanity scorers as the harness floor they are meant to be.

---

### METRICS-008 — "Baseline comparison" contains no model, no B3, and is not per-tier

**Severity:** HIGH · **Category:** DATA / BACKEND / SPECIFICATION
**Location:** `eval/d6.py:_block6_baselines`; `D6Metrics.jsx:Block6`

**Expected.** App Flow §5 D6 #6: *"naive velocity rule and BIN-concentration rule **beside
the model, on every tier**."* Eval Protocol §8: *"Every model number is reported beside
**four** baselines"* — B0, B1, B2, and **B3 (always-positive and random), the sanity floor
"that proves the harness works"**.

**Actual.** Four rows: `B0 — live rules` (recall `n/a`), `B0 — average precision`,
`B1 — decline-velocity`, `B2 — BIN-concentration`. Three failures:

1. **No model row.** The artifact has no `l1-lgbm-v1` entry in `block6_baselines` — a
   backend gap. The section named "Baseline comparison" has no subject to compare against.
2. **No B3.** `sanity_recall_at_b1_fpr` and `sanity_recall_at_b2_fpr` are in the artifact
   (`{perfect: 1.0, random: 0.00146, inverted: 0.0, always_positive: null}` and
   `{…, random: 0.00073, …}`) and are never rendered — a frontend gap.
3. **Not per-tier.** `baseline_summary` carries one overall operating point per baseline.

**Impact.** Three baselines are shown with nothing to be a baseline *for*. Combined with
METRICS-002 (B0's per-tier AP omitted from Block 1), the page contains **no
model-vs-baseline comparison anywhere**, which is the central claim D6 exists to support —
App Flow calls D6 *"the track's stated bar"*.

**Root cause.** Backend for (1) and (3); frontend for (2).

---

### METRICS-009 — The provenance line omits 3 of the 6 attributes the Eval Protocol requires for a number to "go on a slide"

**Severity:** HIGH · **Category:** DATA / SPECIFICATION
**Location:** `D6Metrics.jsx:169-174`

**Expected.** Eval Protocol §9, verbatim: *"Every reported figure carries, in the artifact
itself: `seed`, `config_hash`, `model_version`, `policy_version`, `π_eval`, and the split
name. **A number that cannot state those six things does not go on a slide.**"*

**Actual.** The header renders four fields — `build`, `config`, `seed`, `model`. Missing:

| Required | Present in artifact | Rendered |
|---|---|---|
| `seed` | 42 | ✅ |
| `config_hash` | `a7db8c61…` | ✅ |
| `model_version` | `l1-lgbm-v1` | ✅ |
| **`policy_version`** | **1** (`provenance.policy_version`) | ❌ |
| **`π_eval`** | **0.01** (`provenance.eval_prevalence`) | ❌ |
| **split name** | **`temporal_test`** (`block4_cost.split`, `b0.split`) | ❌ |

All three are already in the file the page imports.

**Impact.** The page violates the bar its own governing spec sets, on the screen whose
entire purpose is credibility. π_eval is doubly consequential: its omission is what lets
METRICS-001's raw-prevalence AP pass without challenge. The missing split name also
conceals METRICS-016 (evasive comes from a different split).

**Correct behaviour.** Extend the line to all six, and label the split per block where
blocks differ.

---

### METRICS-010 — Block 5 omits the raw calibration column and both reliability diagrams

**Severity:** HIGH · **Category:** DATA / FRONTEND / BACKEND / SPECIFICATION
**Location:** `D6Metrics.jsx:Block5`; `eval/harness.py:_calibration_block:_regime`

**Expected.** App Flow §5 D6 #5: *"Calibration — **reliability at both regimes**, Brier and
ECE for **{raw, Platt, Platt+prior-correction}**."* Eval Protocol §3.4 adds *"the ECE gap
between them. If prior correction does not improve ECE at π₁, it is broken and the test says
so."*

**Actual.** A 2×4 table: Brier Platt, Brier Platt+prior, ECE Platt, ECE Platt+prior.

| Required | Status |
|---|---|
| Brier {Platt, Platt+prior} | ✅ shown, values verified |
| **Brier {raw}** | ❌ `brier_raw` = 0.1193 / 0.1403 **in the artifact, not rendered** |
| **ECE {raw}** | ❌ **never computed** — `_regime` computes `brier_raw` but no `ece_raw` |
| **Reliability diagram, both regimes** | ❌ `reliability_pi0` / `reliability_pi1`, 10 bins each with `mean_predicted`, `observed_rate`, `weight`, **fully computed and never rendered** |
| ECE gap / verdict | ❌ neither computed nor stated |

**Impact.** The reliability diagram is *the* canonical calibration visualisation and the one
the spec names first; twenty bins of correct data are computed on every harness run and
discarded. Without the raw column the reader cannot see what calibration bought. And the
spec's own test — "if prior correction does not improve ECE at π₁, it is broken" — is left
for the reader to perform mentally (it does improve: 0.3955 → 0.2807).

**Note:** the values that *are* shown are correct — I recomputed both ECE figures from the
artifact's own reliability bins and matched to 10 decimal places.

---

### METRICS-011 — `max_univariate_auc` is the threshold, not the maximum

**Severity:** MEDIUM · **Category:** API / DATA
**Location:** `config/features.yaml:19` → `block3_audit.max_univariate_auc`

**Expected.** A field named `max_univariate_auc` states the maximum observed univariate AUC.

**Actual.** It is the configured **flag threshold**, 0.95. The actual maximum across the 24
features is **0.9976** (`distinct_cards_per_bin_5m`). `test_d6_artifact.py:82` asserts it
non-null inside a test named *"carries the univariate_auc table"*, reinforcing the
misreading.

**Impact.** Any consumer reading the artifact as a data file concludes the worst feature
sits at 0.95 when six features exceed it, one at 0.998. The UI happens to use 0.95 as a
threshold (hardcoded), so nothing is visibly wrong today.

**Correct behaviour.** Rename to `univariate_auc_threshold`; emit a real maximum separately
if one is wanted.

---

### METRICS-012 — AuditBars hardcodes the threshold and recomputes `flagged` instead of reading the artifact

**Severity:** MEDIUM · **Category:** FRONTEND
**Location:** `AuditBars.jsx:12`, `:18`

**Actual.** `const THRESHOLD = 0.95;` duplicates `block3_audit.max_univariate_auc`, which
the component already receives. `flagged: (auc >= THRESHOLD) || !!excluded` duplicates
`features.*.flagged`, which the artifact already carries.

**Verified agreement today:** I compared the artifact's `flagged` against the frontend rule
for all 24 features — **no disagreement**. And the caption's claim ("A feature over it is
excluded from the model and stays active only in the R1/R3 rule floors") is **accurate**
against `config/features.yaml`'s own comment.

**Impact.** Latent drift. The value 0.95 now lives in three places (`08-UIUX-SPEC-v2.md:493`,
`config/features.yaml:19`, `AuditBars.jsx:12`); changing the config silently desynchronises
the chart's rule from the classification, with no test to catch it (test gap #6).

---

### METRICS-013 — The generator-artifact flag is one-sided; inverted discriminators are ranked as the weakest features

**Severity:** MEDIUM · **Category:** CALCULATION / UI
**Location:** `AuditBars.jsx:16-23`

**Expected.** Univariate discriminability is `|AUC − 0.5|`. An AUC of 0.02 is as perfect a
single-feature separator — and as likely a generator artifact — as 0.98.

**Actual.** `flagged = auc >= 0.95`, and rows sort by `auc` descending. Two features have
AUC < 0.5:

| Feature | AUC | Separability \|AUC−0.5\| | Rendered |
|---|---:|---:|---|
| `bin_entropy_5m` | 0.711 | 0.211 | 7th, 71% bar |
| `bin_hhi_5m` | **0.289** | **0.211** | 23rd, 29% bar |
| `card_seen_24h` | **0.225** | **0.275** | **24th (last), smallest bar** |

`card_seen_24h` is the **third most discriminative non-excluded feature** on the split, and
it renders as the weakest row on the page. A hypothetical feature at AUC 0.02 would be a
near-perfect inverted discriminator, would sort dead last with a 2% bar, and would never be
flagged — defeating the block's stated purpose.

**Correct behaviour.** Sort and flag on `|AUC − 0.5|`; mirror the threshold to 0.05; mark
sign separately.

---

### METRICS-014 — The ₹ headline is locale-dependent

**Severity:** MEDIUM · **Category:** FRONTEND
**Location:** `CostCurve.jsx:19` — `` `₹${Math.round(minor/100).toLocaleString()}` ``

**Actual.** `toLocaleString()` with **no locale argument** uses the viewer's browser locale.
The same artifact renders:

- `₹2,32,145` — Indian digit grouping (reference screenshot, `en-IN`)
- `₹232,145` — Western grouping (**my capture**, `en-US`)

**Impact.** A rupee figure rendered with Western grouping is wrong for its currency, and the
headline number differs between viewers of the same page. The underlying value is identical
and correct (23,214,508.206 paise → ₹232,145); only the formatting varies.

**Evidence.** Two screenshots of the same build showing different groupings.

**Correct behaviour.** `toLocaleString("en-IN")`, or
`Intl.NumberFormat("en-IN", {style:"currency", currency:"INR", maximumFractionDigits:0})`.

---

### METRICS-015 — Block 1's caption describes grouped bars that are not rendered

**Severity:** MEDIUM · **Category:** UI/UX
**Location:** `D6Metrics.jsx:54-57`

**Actual.** The caption reads: *"recall @ FPR 1e-3 per tier. The evasive bar gets no special
treatment — it is simply the fourth bar, **at whatever height it is** (UIUX v2 SS6.13)."*
Immediately below, **all eight recall rows render with no bar at all**, because every
`recall_at_target_fpr` carries `resolvable: false`.

**Impact.** The section's only explanatory text describes a chart that does not exist. The
suppression is correct (FIX-019); the caption was not updated to match, so the copy actively
contradicts the render. A reader looking for "the fourth bar" finds four grey tracks reading
"NOT RESOLVABLE AT THESE NEGATIVE COUNTS".

**Correct behaviour.** Rewrite for the unresolvable case; keep the no-special-treatment
principle where it applies (the AP series).

---

### METRICS-016 — The evasive tier is measured on a different split from easy/medium/hard

**Severity:** MEDIUM · **Category:** DATA
**Location:** `eval/d6.py:_block1_per_tier` (lines 196-206)

**Actual.**
```python
"easy":    _tm_json(report.tier_breakdown.get("easy")),      # temporal_test
"medium":  _tm_json(report.tier_breakdown.get("medium")),    # temporal_test
"hard":    _tm_json(report.tier_breakdown.get("hard")),      # temporal_test
"evasive": _tm_json(te.tier_breakdown.get("evasive")),       # tier_e  ← different split
```

Verified: 821 + 701 + 603 = **2125** = the whole `temporal_test` split. The evasive tier's
390 samples are entirely outside it, drawn from the separate `tier_e` split
(`tier_e.split_n = 390`, `prevalence = 0.4333` — identical to `block1.evasive`).

**Impact.** Four bars are presented as four tiers of one evaluation; the fourth is a
different dataset with a different (also 221-sample, coincidentally) negative pool. The UI
says nothing, and the split name is not displayed anywhere (METRICS-009). This is
defensible methodology — Tier E is constructed by adversarial search — but it must be
labelled, especially under a caption insisting the bar gets "no special treatment".

---

### METRICS-017 — Negative-control episode denominators are 1; two scenarios have n ≤ 5 attempts

**Severity:** MEDIUM · **Category:** DATA
**Location:** `eval/report.py:_episode_and_attempt_fp`; `d6.json:block2_negative_controls`

**Actual.** `n_episodes = len(flagged_by_episode)` = **1 for all 7 scenarios**, so every
"episode FP" cell is `0/1` or `1/1` — a boolean formatted as a rate. Attempt denominators
vary widely and two are tiny:

| Scenario | attempts | Note |
|---|---:|---|
| flash_sale | 720 | adequate |
| cgnat | 500 | adequate |
| corporate_nat | 300 | adequate |
| nri_traffic | 216 | adequate |
| subscription_batch | 200 | adequate |
| **retry_storm** | **5** | under-powered |
| **shared_ip_legit** | **1** | **a single sample** |

`shared_ip_legit` — Eval Protocol §4/V4 calls it *"the F14 case"*, one of the two scenarios
newly added in v2 and conceptually the most important FP trap — is evaluated on **one
legitimate attempt**. Its `random` row reads `0/1`, which is pure coin-flip noise presented
in the same table as `542/720`.

The counts themselves are correct (`_episode_and_attempt_fp` correctly excludes `is_attack`
samples so that catching the embedded fraud in `shared_ip_legit` is not scored as an FP —
good design). The defect is presentational: no denominator warning, no confidence interval,
identical typography for n=1 and n=720.

---

### METRICS-018 — No routing: Metrics has no URL, no deep link, and does not survive refresh

**Severity:** MEDIUM · **Category:** FRONTEND / UX
**Location:** `services/dashboard/src/App.jsx:44` — `useState("live")`

**Actual.** Navigation is `useState`, no router. Verified in the browser:

- Clicking **Metrics** leaves the URL at `http://localhost:5174/`.
- Refresh returns to **Live**; Metrics cannot be reached directly.
- Browser back/forward do nothing.
- `document.title` stays **"Tollgate — Live Monitor"** while Metrics is displayed
  (`index.html:5`).
- Nav buttons carry no `aria-current`.

**Impact.** The evaluation page — the one App Flow calls "the track's stated bar" and the
one most likely to be linked to a reviewer — is not addressable. Answering the brief's §31
directly: **the Metrics route does not work directly, and refresh does not preserve it.**
It does not depend on visiting another page first, which is the one part that passes.

---

### METRICS-019 — No error boundary; five of six blocks dereference artifact fields unguarded

**Severity:** MEDIUM · **Category:** FRONTEND
**Location:** `D6Metrics.jsx`, `CostCurve.jsx`; whole dashboard

**Actual.** No `componentDidCatch` / `ErrorBoundary` / `getDerivedStateFromError` anywhere
in `services/dashboard/src`. Unguarded dereferences: `d6.provenance.build_hash` (the `?.` is
on the wrong level), `Object.entries(d6.block2_negative_controls)`, `d6.block3_audit.features`,
`b4.curve_pi0` / `b4.ribbon[0].curve`, `d6.block6_baselines.b0`. Only `Block5` guards
(`if (!cb || !cb.pi0) return <p>not measured in this artifact.</p>`) and `tier_e` (`|| {}`).

**Impact.** A malformed or schema-skewed artifact throws during render and, with no
boundary, React unmounts the **entire application** — the whole dashboard blanks, not just
Metrics. Mitigating: the build-time import means a *missing* file fails the build rather
than shipping a broken page.

---

### METRICS-020 — `THETA_CHALLENGE` is a hardcoded rounded copy of a derivable threshold

**Severity:** MEDIUM · **Category:** BACKEND
**Location:** `eval/report.py:26`

**Actual.** `THETA_CHALLENGE = 0.257`. The cost model derives it:
`C_FP(challenge)/(C_FP(challenge)+C_FN) = 1800/(1800+5200) = 0.2571428571…`.
The constant is **rounded down**, making the threshold marginally more permissive than the
model implies. All 28 Block 2 cells are computed at this threshold.

**Impact.** Small and currently immaterial, but it contradicts the project's own thesis —
App Flow §2 cuts the D5 threshold UI precisely because *"thresholds are `θ_T =
C_FP(T)/(C_FP(T)+C_FN)`, arithmetic, not preference."* A hand-typed rounded copy is exactly
the drift that argument rules out, and `cost_model.yaml` can change without it following.

---

### METRICS-021 — π₀ / π₁ are hardcoded in three UI strings

**Severity:** MEDIUM · **Category:** FRONTEND
**Location:** `D6Metrics.jsx:Block5` (×2), `CostCurve.jsx` y-axis label

**Actual.** `"π₀ = 0.001 (steady state)"`, `"π₁ = 0.9 (under attack)"`, and
`"₹ / 10,000 attempts · π₀=0.001 (solid) · π₁=0.9 (dashed)"` are literals. The artifact
carries `block4_cost.pi0 = 0.001` and `pi1 = 0.9`.

**Impact.** Currently correct. If `cost_model.yaml`'s priors change, every number moves and
every label lies — on the exact axis label UIUX §6.13 mandates *"because a curve whose
prevalence you have to hunt for is how v1's number became arbitrary in the first place."*

---

### METRICS-022 — Single-seed point estimates are presented without qualification

**Severity:** MEDIUM · **Category:** DATA / UI
**Location:** `provenance.seeds_used = 1`

**Actual.** Every figure on the page comes from **one seed**. `seeds_used` is in the
artifact and never displayed. `effective_n` (759.5 at π₀ against a nominal n = 2125 — the
prevalence reweighting costs ~64% of effective sample size) is likewise present and hidden.

**Impact.** Values are printed to 3–4 decimals with no interval, implying a precision one
seed cannot support. The Wilson CIs that *are* computed are attached only to recall, which
is never displayed (see METRICS-040).

---

### METRICS-023 — Captions, provenance and all `n/a` values fail WCAG AA contrast

**Severity:** MEDIUM · **Category:** ACCESSIBILITY

Measured against the page background `rgb(11,13,16)`:

| Class | Size | Colour | Ratio | AA (4.5:1) |
|---|---|---|---:|---|
| `tg-caption` | 12px | `rgb(110,120,133)` | **4.34** | ❌ |
| `tg-mono-caption` | 11px | `rgb(110,120,133)` | **4.34** | ❌ |
| `tg-mono-data tg-num` | 13px | `rgb(110,120,133)` | **4.34** | ❌ |
| SVG axis labels | 9 (scaled) | `rgb(110,120,133)` | **4.34** | ❌ |
| SVG optima labels | 9 (scaled) | `rgb(99,102,241)` | **4.36** | ❌ |
| `tg-label` / `tg-body` | 12/14px | `rgb(167,176,188)` | 8.88 | ✅ |

Affected: every explanatory caption, the provenance line, both cost-curve axis labels, and —
notably — **every `n/a · n_neg=` value**, i.e. the muted styling applied to unresolvable
metrics pushes exactly the honesty-critical text below the threshold.

---

### METRICS-024 — Tables and bar rows lack semantic structure

**Severity:** MEDIUM · **Category:** ACCESSIBILITY

- Neither table has `scope` on any of its 9 `<th>` elements; neither has a `<caption>`.
- Block 2 uses **empty `<td>`s as a visual rowspan** (`{i === 0 ? scenario : ""}`). A screen
  reader announces 21 of 28 rows with no scenario. Correct markup is `rowSpan={4}`.
- All 32 bar rows (`BarRow`, `AuditBars`) are `<div>` grids. Label, bar and value are
  unassociated siblings with no `role`, `aria-label`, or `aria-describedby`.
- The cost-curve `<svg>` has `role="img"` and an `aria-label` but no `<title>`/`<desc>` and
  no tabular alternative; the curve data is unavailable to assistive tech.

---

### METRICS-025 — A feature name overflows its column into the bar track

**Severity:** MEDIUM · **Category:** UI/UX
**Location:** `AuditBars.jsx` — `gridTemplateColumns: "200px 1fr 64px"`

**Actual.** `store_decline_rate_deviation_sigma` measures **235 px** at 11 px IBM Plex Mono
in a **200 px** cell, with `overflow: visible`, `text-overflow: clip`, `white-space: normal`
and no break opportunity in an underscore-joined token. The span's right edge lands at
x ≈ 259 while the bar track starts at x = 236 — **23 px of text sits on top of the bar**.
Reproduced at the default 1536 px desktop width, fonts fully loaded.

---

### METRICS-026 — A Block 6 value wraps to two lines and breaks row alignment

**Severity:** MEDIUM · **Category:** UI/UX
**Location:** `D6Metrics.jsx:Block6` — `valueText={`recall ${metricText(...)}`}`

**Actual.** `"recall n/a · n_neg=758"` does not fit the 168 px value column and wraps,
giving that row a **36 px** height against ~22 px for its neighbours. Visible as a broken
baseline at the top of Section 6.

---

### METRICS-027 — Fixed-column layout with no media queries breaks below ~600 px

**Severity:** MEDIUM · **Category:** UI/UX
See §17 for the measured table. At a 390 px container the bar track collapses to **54 px**
while the 200 px label and 168 px value columns keep full width, and the tables overflow the
document horizontally with no `overflow-x` container. No `@media` rule exists other than
`prefers-reduced-motion`.

---

### METRICS-028 — The unresolvable null state renders as a full-width bar

**Severity:** MEDIUM · **Category:** UI/UX
**Location:** `BarRow.jsx:70-72`

**Actual.** When `resolvable === false` no fill is drawn, but the **track** — a
`--tg-surface-2` rounded rectangle spanning the full column — remains. Since a filled bar is
also a rounded rectangle in a similar grey family, the null state reads as a **100% bar** at
a glance. In Block 1, eight consecutive rows render this way. The in-track caption
disambiguates on reading, but the pre-attentive signal is inverted from the intent.

---

### METRICS-029 — The artifact carries no timestamp and the build hash is silently stale

**Severity:** MEDIUM · **Category:** DATA
See §8. `config_hash` and `fixture_sha256` match today exactly; `build_hash` has diverged
(`9141a8ecc4…` → `36d0cc4817…`) because HEAD moved and the tree is dirty. The header prints
the artifact's build hash with no temporal qualifier, and **the artifact has no
`generated_at` field**, so neither the page nor the file can say how old the numbers are.

---

### METRICS-030 — No frontend test infrastructure exists

**Severity:** MEDIUM · **Category:** TEST
See §19. `package.json` declares one script (`dev`), no test runner, no test files. The three
"frontend" tests are Python substring greps over JSX. `regime_switch_saving_minor` — the
₹2,32,145 headline — is asserted only `>= 0`.

---

### METRICS-031 — The static Metrics screen keeps a live SSE connection and 1 Hz polling

**Severity:** MEDIUM · **Category:** PERFORMANCE / UX
**Location:** `App.jsx:60-63`

**Actual.** `useReplayStatus`, `useEventStream` and `useIncidents` are called unconditionally
in `App`, before the route switch. While Metrics is displayed the app keeps an `EventSource`
open and polls `/v1/replay/status`; one `/v1/stream/recent` fetch was observed during a
5-second idle dwell. Each incoming event re-renders `App`, and with it D6's 24-row audit and
the inline SVG. The Stream Rail, the `CALM` threat band and the Demo Control Strip all
render on a static evaluation report.

**Impact.** Contradicts App Flow §5 D6's *"Static render. No live computation on stage."* at
the screen level, even though `D6Metrics` itself is genuinely static.

---

### METRICS-032 → METRICS-040 — Low severity

| ID | Finding | Location |
|---|---|---|
| **M-032** | Internal spec IDs in user-facing copy, with `§` mangled to `SS`: `(UIUX v2 SS6.13)`, `(Eval Protocol SS4/V2)` | `D6Metrics.jsx:56`, `AuditBars.jsx:64` |
| **M-033** | Inconsistent capitalization — CSS uppercases `L1-LGBM-V1` / `BRIER PLATT` while the provenance line and regime column stay lowercase | `type.css`, `D6Metrics.jsx` |
| **M-034** | The rotated y-axis label `₹ / 10,000 attempts · π₀=0.001 (solid) · π₁=0.9 (dashed)` is clipped at the top of the viewBox | `CostCurve.jsx` |
| **M-035** | `maxWidth: 900` leaves ~40% of a 1536 px viewport empty while Block 3's label column is simultaneously too narrow (M-025) | `D6Metrics.jsx:166` |
| **M-036** | Block 5 gives no units, no "lower is better", and no threshold; ECE 0.3955 is styled identically to ECE 0.0007 | `D6Metrics.jsx:Block5` |
| **M-037** | The cost curve never states its series, tier or split (`l1-lgbm-v1` / `challenge` / `temporal_test`, all in the artifact) | `CostCurve.jsx` |
| **M-038** | `sanity_recall_at_*.always_positive: null` is a meaningful "unreachable" sentinel with no accompanying reason field, and is never rendered | `d6.json:block6_baselines` |
| **M-039** | The `₹0` rupee gap is presented as an empirical finding, but at π₀ = 0.001 precision ≈ 1.0 only at FPR = 0, so F1-argmax and cost-argmin coincide **almost by construction**. Verified: F1 falls from 0.638 at FPR=0 to 0.353 at the next hull vertex | `eval/d6.py:_argmax_f1` |
| **M-040** | `ci_low`/`ci_high` are Wilson intervals on the **achieved FPR** (0/221 → [0, 0.01709], verified), but `BarRow.fmtCi` renders them immediately after the **recall** value as if they bounded recall. Latent only — all current recall entries are unresolvable, so the CI never renders | `BarRow.jsx:31-34` |

---

## 21. Correctly Verified Metrics

Independently confirmed correct — this is not only a defect list.

| Metric | Displayed | Verification method | Result |
|---|---|---|---|
| `regime_switch_saving_minor` | ₹232,145 | Recomputed from `cost_model.yaml`: 24855010.972933434 − 1640502.7668777597 | **exact** |
| `rupee_gap_minor` | ₹0 | Recomputed: cost(F1-opt) − cost(cost-opt) at π₀ | **exact, 0.0** |
| cost-optimal point | (0.0, 0.46891) | Independent argmin over `curve_pi0` | **exact** |
| F1-optimal point | (0.0, 0.46891), F1 0.638446 | Independent argmax of F1 at π₀ | **exact** |
| `curve_pi0`, `curve_pi1` | 20 points | All 20 recomputed from `10000·(π(1−TPR)·5200+(1−π)·FPR·1800)` | **exact** |
| C_FN = 5200 | — | 200 + 5000 from `cost_model.yaml` | **exact** |
| C_FP(challenge) = 1800 | — | 120000 × 0.30 × 0.05 | **exact** |
| ECE Platt+prior @ π₀ | 0.0007 | Recomputed from the artifact's own 10 reliability bins | **exact to 10 dp** |
| ECE Platt+prior @ π₁ | 0.2807 | Same | **exact to 10 dp** |
| B1 TPR | 0.075 | 103/(103+1264) from the confusion matrix | **exact** |
| B2 TPR | 0.718 | 982/(982+385) | **exact** |
| B0 AP | 0.997 | `ap_raw` 0.9969616 | **exact** |
| `resolvable: false` ×9 | `n/a` | n_neg 221/221/316/758 all < 1/1e-3 = 1000 | **correct** |
| Wilson CI (0/221) | — | z=1.95996 → upper 0.017085189 | **exact** |
| n_neg per tier | 221/221/316 | n × (1 − prevalence) | **exact** |
| Split consistency | — | 821+701+603 = 2125 = block5.n = b0.n; 221+221+316 = 758 = b0.n_neg | **exact** |
| All 32 bar widths | — | `width%` vs value × 100, 4 dp | **exact** |
| Audit `flagged` ×24 | — | Frontend rule vs artifact field | **no disagreement** |
| B2/B1 caption | prose | Read against `eval/baselines.py` docstrings — B2 issues the identical `WindowRequest` to `compute.py:203` (R3's statistic); B1 requires `outcome_visible_ms = t_ms + 340ms` | **accurate** |
| AuditBars caption | prose | Read against `config/features.yaml` comment | **accurate** |
| Coincident-optima caption | prose | Verified — both optima are genuinely at FPR 0 | **accurate** |
| Tier E params | 77 IPs, 19 BINs, 866/h | Read from `config/attack_tiers.yaml:evasive` | **exact** |
| `config_hash` | `a7db8c6118…` | `config_hash()` recomputed today | **match** |
| `fixture_sha256` | — | Compared to `tests/fixtures/golden.sha256` | **match** |
| Sticky strip clearance | — | 36 px gap at maximum scroll | **no occlusion** |
| Console cleanliness | — | Full page visit | **0 errors, 0 warnings** |

---

## 22. Backend ↔ Frontend Consistency Report

- **Matching metrics:** 100% of rendered values. Zero mismatches, zero stale values, zero
  wrong field mappings, zero divergent denominators, zero frontend recomputation of a
  backend metric.
- **Ignored API fields:** **23** (§5.2) — the dominant problem.
- **Frontend-only calculations:** 2 (`AuditBars` threshold + `flagged`), both currently
  agreeing with the backend.
- **Hardcoded strings duplicating artifact data:** 3 (π₀/π₁ labels ×2, axis label).
- **Backend-internal duplication:** 1 (`THETA_CHALLENGE`).
- **Different datasets within one visual group:** 1 (evasive from `tier_e`, M-016).

---

## 23. UI / UX Report

**Visual defects (7):** M-025 (label overflows into bar), M-026 (value wraps), M-028
(null state reads as full bar), M-034 (clipped axis label), M-004 (markers on the axis),
M-005 (invisible self-intersecting ribbon), M-003 (sub-pixel curve region).

**UX defects (7):** M-018 (no URL/deep link/refresh, stale `<title>`), M-015 (caption
contradicts render), M-036 (no units or direction in Block 5), M-037 (chart doesn't state
its series/split), M-027 (no responsive strategy), M-031 (irrelevant live chrome on a
static page), M-035 (900 px cap wastes 40% of the viewport).

**Professionalism issues (5):** M-032 (`SS6.13` — mangled `§` and leaked internal spec IDs),
M-033 (inconsistent capitalization), inconsistent decimal precision across blocks (3/4/raw),
repeated 40- and 27-character labels stacked 8× and 6×, and 14 identical placeholder rows
occupying more than half of the audit section.

**Accessibility issues (6):** M-023 (five text roles below AA), M-024 (no `th scope`, no
`caption`, empty cells as rowspan, unassociated bar rows, no SVG `title`/`desc`), no
`aria-current` on nav.

---

## 24. Recommended Fix Priority

### Tier 1 — data correctness (the page is misleading until these land)

| # | ID | Problem | Impact | Fix |
|---|---|---|---|---|
| 1 | **M-001** | AP shown at raw prevalence, prevalence omitted, `ap_at_eval_prevalence` discarded | `easy` reads as 0.789/79% when its lift over trivial is **1.08×**. Violates Eval §2.1, §1, App Flow §5 D6 | Render `ap_at_eval_prevalence` as the comparable series; print each tier's raw prevalence in-row; keep `ap_raw` beside it |
| 2 | **M-002** | B0's per-tier AP omitted | Hides that B0 beats the model on **all four tiers** — which `Decisions.md` commits to publishing | Add the B0 AP series to Block 1 |
| 3 | **M-006** | 14 un-fed constants render as measured 0.500 | >half of the audit section is placeholders shown as measurements | Read `constant`/`reason`; render as a distinct no-bar null state |
| 4 | **M-007** | Block 2 scores only sanity scorers | The FP section says nothing about the system's FPs | Add model + B0 rows per scenario at θ_challenge |
| 5 | **M-008** | Block 6 has no model, no B3, not per-tier | No model-vs-baseline comparison exists anywhere on the page | Emit the model + B3 + per-tier baselines; render all |

### Tier 2 — backend / frontend divergence and missing values

| # | ID | Problem | Fix |
|---|---|---|---|
| 6 | **M-009** | 3 of 6 spec-mandated provenance attributes missing | Add `policy_version`, `π_eval`, split name |
| 7 | **M-010** | No raw calibration column, no reliability diagrams | Render `brier_raw`; add `ece_raw` to the backend; draw both reliability diagrams |
| 8 | **M-016** | Evasive measured on a different split, unlabelled | Label the split per tier |
| 9 | **M-013** | One-sided discriminability flag | Rank and flag on \|AUC − 0.5\| |
| 10 | **M-022** | Single-seed estimates unqualified | Surface `seeds_used`, `effective_n`; add intervals |

### Tier 3 — misleading representation

| # | ID | Fix |
|---|---|---|
| 11 | **M-003** | Log/symlog y-axis or twin scales; clip the FPR axis to the decision-relevant range |
| 12 | **M-004** | Offset the optima markers off the axis; single label when coincident |
| 13 | **M-005** | Per-x min/max envelope; render on a scale where the band has extent |
| 14 | **M-028** | Visually distinct null track |
| 15 | **M-014** | Pin the rupee locale to `en-IN` |
| 16 | **M-015** | Rewrite Block 1's caption to match what renders |
| 17 | **M-017** | Show denominators/intervals; suppress or mark `n ≤ 5` scenarios |
| 18 | **M-039** | State that the ₹0 gap is structural at π₀, not an empirical coincidence |

### Tier 4 — staleness and hardcoding

19. **M-029** add `generated_at`, surface artifact age · 20. **M-012** read the threshold and `flagged` from the artifact · 21. **M-021** read π₀/π₁ from `block4_cost` · 22. **M-020** derive `THETA_CHALLENGE` from the cost model · 23. **M-011** rename `max_univariate_auc` · 24. **M-040** label the CI as an FPR interval

### Tier 5 — tests

25. **M-030** add a JS test runner (Vitest + Testing Library); assert rendered values against the artifact · 26. recompute the ₹2,32,145 headline in a test · 27. assert Block 1 renders prevalence and `ap_at_eval_prevalence` · 28. assert `AuditBars.THRESHOLD === block3_audit.max_univariate_auc` · 29. add a malformed-artifact fixture · 30. add SVG geometry assertions (curve visible, markers separated, ribbon simple) · 31. add a staleness test

### Tier 6 — accessibility · Tier 7 — UX · Tier 8 — visual polish

32. **M-023** raise muted text to ≥4.5:1 · 33. **M-024** `th scope`, `caption`, `rowSpan`, ARIA on bar rows, SVG `title`/`desc` · 34. `aria-current` on nav
35. **M-018** add a router + per-route `<title>` · 36. **M-019** add an error boundary · 37. **M-027** responsive columns + `overflow-x` on tables · 38. **M-031** mount the stream hooks only on live routes
39. **M-032** remove internal spec IDs (and the `SS`/`§` mangling) · 40. **M-033/035/036/037/026/025/034** typography, alignment, units, width

---

## 25. Final Audit Summary

### Overall status: **NOT READY**

Correct arithmetic, faithful rendering, misleading selection.

### Findings

| Severity | Count | IDs |
|---|---:|---|
| **CRITICAL** | 2 | M-001, M-002 |
| **HIGH** | 8 | M-003 … M-010 |
| **MEDIUM** | 21 | M-011 … M-031 |
| **LOW** | 9 | M-032 … M-040 |
| **Total** | **40** | |

### Missing values

**9 intentionally missing** (all `resolvable:false` recall — verified mathematically
unresolvable at 221/316/758 negatives against the 1000 required).
**23 incorrectly missing** (computed, serialised, discarded by the frontend).
**4 missing from the backend** (ECE-raw, model FP rows, model baseline row, per-tier
baselines).
**6 incorrectly represented** (14 constants as 0.500; 2 inverted features mis-ranked; AP
without its baseline; null bars reading as full; `episodes` as a rate; ₹0 as an empirical
result).
**2 unverified** (artifact-vs-corpus provenance; the unrendered `always_positive: null`).

### Backend ↔ frontend mismatches: **0**

Every displayed value is the faithful rendering of its artifact field. The problem is
**23 ignored fields**, not disagreement.

### Calculation errors: **0**

Every independently checkable quantity reproduces exactly — cost model, ROC hull, both
optima, rupee gap, regime-switch saving, both ECEs, Wilson CIs, negative counts, split
sums, all 32 bar widths.

### UI/UX problems: **19** — 7 visual, 7 UX, 5 professionalism
### Accessibility problems: **6** — 5 text roles below AA; no table semantics, no ARIA on 32 bar rows, no `aria-current`
### Performance problems: **1** — the shell's SSE + 1 Hz polling on a static screen. Otherwise excellent: 0 runtime data requests, 491 DOM nodes, 0 console errors.
### Security problems: **0** — one informational note (Vite dev-only `/@fs/` absolute path).

### Test coverage

Backend unit tests are strong (25 real analytic assertions). **Frontend coverage is
effectively zero** — no JS test runner exists; the three "frontend" tests are Python
substring greps over JSX. The ₹2,32,145 headline is asserted only `>= 0`. **All 40 findings
in this report are invisible to the current suite, and it is green.**

---

## 26. The Questions the Audit Had to Answer

**Where does every number come from?** `config/*.yaml` + corpus + model → `eval.harness`
(offline, manual) → `eval/d6.py` → the committed `eval/outputs/d6.json` → a build-time ES
import → JSX → DOM. No API, no runtime computation. Traced end-to-end for all 79 values.

**Is every number mathematically correct?** Yes. Every independently checkable quantity
reproduces exactly. Zero calculation errors.

**If a number is missing, why — and should it be?** 9 recall figures are missing because
221/316/758 negatives cannot resolve a 1e-3 FPR (needs 1000). **They should be missing, and
the page handles them exemplarily.** 23 further values are missing because the frontend does
not read fields the artifact provides — **those should not be missing.** 4 are missing
because the backend never computes them.

**Does the backend have the value / the API expose it / the frontend receive it / render
it?** For the 23: backend yes, artifact yes, frontend receives yes (it imports the whole
object), **renders no.**

**Does backend = artifact = frontend = DOM?** Yes, for everything rendered. Verified value
by value.

**Does the displayed value match the specification?** Often no — 8 spec failures against
Eval Protocol §1/§2.1/§3.4/§8/§9 and App Flow §5 D6 blocks 1, 5, 6.

**Are charts plotting the correct data? Are bars representing the correct numbers?** The
data is correct and every bar width matches its value to 4 decimals. **The cost curve's
geometry is wrong** — the decision-relevant region is sub-pixel, the markers coincide with
the axis, and the ribbon self-intersects.

**Are repeated/suspicious values legitimate?** Investigated all of them. `0.500` ×14 —
arithmetically correct, **presented misleadingly**. `0/1` and `1/1` ×28 — correct,
**under-powered** (1 episode; two scenarios with n ≤ 5). `n/a` ×9 — **correct and
well-handled**. `₹0` — correct, but **structurally forced** at π₀ = 0.001. Repeated
`ci_high = 0.017085189` — correct, it is the Wilson upper bound for 0/221, shared because
three tiers share a negative count.

**Are any values hard-coded or stale?** 3 frontend hardcodes duplicate artifact data
(+1 backend); `config_hash` and `fixture_sha256` are **current**, `build_hash` is stale with
no timestamp to bound it.

**Are backend and frontend using the same source?** Yes — one artifact, one import.

**Does the page look production-ready?** No. Nineteen UI/UX findings, six accessibility
findings, no responsive strategy, and a flagship chart whose three specified elements are
illegible.

**What is correct, broken, missing, unverified?** Correct: all arithmetic, all rendered
values, the `resolvable:false` design, provenance hashes, the B1/B2/B0 explanatory prose,
performance, console cleanliness, sticky-strip clearance. Broken: the cost curve's geometry,
the constant-feature representation, three whole blocks measured against their own spec.
Missing: 23 computed values and 4 backend metrics. Unverified: the artifact's provenance
against the corpus, which cannot be checked without regenerating it.

**What should be fixed first?** METRICS-001 and METRICS-002. Together they mean the Metrics
page presents a systematically favourable subset of an artifact that is, itself, candid
about the model being weaker than the rules baseline.

---

*Audit performed read-only. No repository file was modified, no test altered, no defect
repaired. The dashboard and scorer were started for live inspection and stopped afterwards;
neither was running beforehand.*
