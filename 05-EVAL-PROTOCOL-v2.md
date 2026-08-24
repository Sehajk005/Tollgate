# Tollgate — Evaluation Protocol

**Version:** v2.0 — 22 August 2026
**Status:** New document in v2. v1 scattered this across PRD §8 and TRD §8, which is how the cost formula lost its prevalence term without anyone noticing.
**Fixes:** F3, F4, F5 (measurement side), F12, F13, F14, F20.

---

## 0. The rule this document exists to enforce

> **No metric is reported without the conditions under which it was measured.** For a rate metric that means the prevalence. For a cost metric that means the prior, the cost parameters, and the tier. For a detection-latency metric that means the attacker's pacing.

v1 violated this in the one place it mattered most: the rupee gap the pitch closes on was computed at whatever prevalence happened to fall out of the simulator config.

---

## 1. The cost model, corrected (fixes F3)

### 1.1 What was wrong

v1 gave `FN cost` and `FP cost` per event and computed an optimal threshold from those two numbers. Expected cost is not a function of two numbers. It is:

```
E[cost per attempt | θ, π] = π · (1 − TPR(θ)) · C_FN
                           + (1 − π) · FPR(θ) · C_FP(tier)
```

**π enters multiplicatively and was absent.** Under attack π ≈ 0.9; in steady state π ≈ 0.001. The cost-optimal threshold moves by orders of magnitude between those regimes, and since the mixed dataset's prevalence is a knob in the simulator config, v1's headline rupee number was whatever it happened to generate.

### 1.2 The decision rule

With a properly calibrated `p = P(attack | x)`, the cost-minimising action at tier *T* is: **act iff**

```
p  ≥  θ_T  =  C_FP(T) / (C_FP(T) + C_FN)
```

Three properties worth stating out loud, because they carry the pitch:

1. **The prior does not appear in the threshold.** It appears *inside* `p`, via the calibration's prior correction (§3). Prevalence enters exactly once, in the right place. This is the whole fix.
2. **The tier ladder falls out of the cost model.** Because `θ_T` is increasing in `C_FP(T)`, and `C_FP` is increasing in tier severity, the thresholds are automatically monotone. v1 hand-picked thresholds and then claimed they were cost-derived; v2 derives them and can show the arithmetic on a slide.
3. **When the regime changes, every threshold moves at once** — not because the thresholds changed, but because `p` did. The CUSUM state feeds the prior. That is Bayes decision theory doing something visible, and it is the strongest single idea in the project.

### 1.3 Worked defaults

`config/cost_model.yaml`, every parameter with a `source:` field (asserted by test):

| Parameter | Default | Note |
|---|---|---|
| `auth_fee_minor` | ₹2.00 | Per-attempt, charged on declines too |
| `downstream_exposure_minor` | ₹50.00 | Amortised — a validated card returns as fraud with probability *q* at cost *L*; `q·L` |
| `C_FN` | ₹52.00 | Sum of the above |
| `aov_minor` | ₹1,200 | Store profile |
| `margin_pct` | 0.30 | Contribution margin, not revenue |
| `P(abandon | throttle)` | 0.01 | |
| `P(abandon | challenge)` | 0.05 | |
| `P(abandon | step_up)` | 0.15 | |
| `P(abandon | block)` | 1.00 | By definition |

Derived ladder — **hand-checkable, and checked by an analytic test**:

| Tier | `C_FP` | `θ_T = C_FP/(C_FP + 52)` |
|---|---|---|
| `throttle` | ₹3.60 | **0.065** |
| `challenge` | ₹18.00 | **0.257** |
| `step_up` | ₹54.00 | **0.509** |
| `block` | ₹360.00 | **0.874** |

`tests/acceptance/test_cost_thresholds.py` recomputes this table from the YAML and compares against these literals. If someone edits a cost parameter, the test fails and the thresholds move — which is the point.

### 1.4 What gets reported

Never a single rupee number. Always:

- **A curve per regime.** Expected ₹ per 10,000 attempts across θ, drawn twice: at `π₀ = 0.001` (steady state) and at `π₁ = 0.9` (under attack). Both curves on one axis.
- **A sensitivity ribbon** across `π ∈ [1e-4, 1e-2]` for the steady-state curve, because π₀ is the parameter a judge will challenge.
- **The gap, stated with its conditions:** *"At steady-state prevalence 10⁻³ and the cost parameters in `cost_model.yaml`, the F1-optimal threshold costs ₹X per 10,000 attempts more than the cost-optimal threshold."*
- **The regime-switch saving:** what the fixed-threshold policy costs versus the CUSUM-conditioned policy across a stream containing both regimes. This is the number that demonstrates the architecture, not just the arithmetic.

---

## 2. Metric selection (fixes F3's second half, F20)

### 2.1 PR-AUC is prevalence-dependent — so it is not a cross-tier comparator

v1 reported per-tier PR-AUC side by side. Tiers have different attack densities, so those numbers were never comparable, and the "credibility exhibit" of visible degradation was partly an artifact of density.

**v2 rules:**

- **Cross-tier comparison uses `recall @ fixed FPR`** (default FPR = 0.001), which is prevalence-independent. This is the headline table.
- **PR-AUC is reported within a tier, with that tier's prevalence printed beside it**, and every tier's eval set is resampled to a common evaluation prevalence (`π_eval = 0.01`, stated) so the numbers are at least on one footing. Both the raw and resampled prevalence appear in the report.
- Any chart plotting PR-AUC across tiers carries the prevalence on the axis label. Enforced by the report generator, not by discipline.

### 2.2 Layer 2 headline: `attempts_before_alert`, not time-to-detect

For the hard and evasive tiers at ~20 attempts/hour, time-to-detect is measured in hours, looks terrible, and means nothing — it is dominated by the attacker's pacing, not the detector's sensitivity.

**Primary Layer 2 metrics, in reporting order:**

1. **`cards_exposed_before_alert`** — distinct card hashes the attacker validated before we fired. This is the harm unit. It is what the merchant actually loses and what the issuer actually cares about. v1 didn't have it.
2. **`attempts_before_alert`** — median and p90.
3. **`time_to_detect_s`**, in **event time**, reported per tier with the tier's attempt rate printed beside it, and an explicit note that at hard/evasive pacing this metric is attacker-controlled.
4. **Episode FP count** on the negative-control suite, per named scenario.

### 2.3 Calibration metrics

Reliability diagram + Brier + ECE, computed **separately at each regime prevalence**, because a calibrator that is well-behaved at π₀ and broken at π₁ is exactly the failure that invalidates the cost curve.

---

## 3. Calibration under prevalence shift (fixes F12)

**v1 used isotonic regression on a validation split.** Isotonic overfits badly on small validation sets and produces coarse step functions in the tails — which is precisely where the operating thresholds (0.065, 0.874) live. And it was fitted at one prevalence and applied at another.

**v2:**

1. **Platt scaling** (two-parameter sigmoid on the model logit). Robust in the tails, stable on a few thousand validation rows, and monotone by construction. Isotonic is kept behind a config flag for comparison in the report; whichever wins on held-out Brier is shipped, and the comparison is published.
2. **Explicit prior correction at serve time:**

```
logit(p_serve) = logit(p_train) + ln(π_s / (1 − π_s)) − ln(π_t / (1 − π_t))
```

where `π_t` is the training-set prevalence (recorded in the model artifact) and `π_s` is the serving prior.

3. **`π_s` is regime-dependent and comes from Layer 2.** In-control → `π₀` from config. CUSUM in alarm → `π₁` estimated from the alarm's implied rate ratio, clamped to `[π₀, 0.95]`. This is the mechanism by which "the threshold moves when the prior moves."
4. **Reported:** reliability at both regimes; Brier for {raw, Platt, Platt + prior-correction}; the ECE gap between them. If prior correction does not improve ECE at π₁, it is broken and the test says so.

---

## 4. Simulator validity (fixes F4)

v1's four countermeasures did not close the circularity, because all four operate on the attack half. Citing a parameter to J.P. Morgan doesn't ground the *joint distribution* — and if attacker amounts are drawn from a floor while baseline amounts are drawn from a log-normal, `amount_is_floor` is a perfect discriminator by construction and its attribution measures the simulator, not the detector.

Four new controls. The first is the only one that structurally changes anything.

### V1 — The legitimate half comes from a source that isn't you

Baseline arrivals and amounts are **resampled from a public real-world e-commerce order dataset**. **Resolved Day 2 (Decisions.md decision 29):** UCI *Online Retail II* (Chen, D., 2012; CC BY 4.0; verified 1,067,371 line-item rows, 43.5 MB xlsx, doi:10.24432/C5CG6D — an actual transaction log, not a generative model), distilled once by `scripts/distill_baseline.py` into a committed, SHA-verified, integer-only profile (`data/baseline/online_retail_ii.profile.json`) that `packages/simulator/profile.py` loads at runtime. The raw xlsx is gitignored and never committed; redistributing the derived, aggregated profile with attribution is permitted under CC BY 4.0.

- Inter-arrival structure and diurnal/weekly shape: empirical — 168 integer hour-of-week weights, aggregated from the dataset's own `InvoiceDate` timestamps.
- Amount distribution: empirical order-value distribution (a 1001-point integer quantile table, GBP minor units), rescaled to the configured AOV via `amount_minor = round(q_gbp_minor × aov_minor / mean_order_value_gbp_minor)` (integer round-half-up — `packages/simulator/profile.py::rescale_to_store_aov()`).
- BIN spread: long-tailed, fitted to a published issuer share distribution; BIN *identities* remain fictional (safety constraint unchanged) — a reserved `999xxx` prefix, disjoint from every real IIN range.

The attack half stays authored. **The symmetry is now broken:** the covariance structure between attack traffic and legitimate traffic is no longer both mine. This is the countermeasure v1 was missing and it costs about three hours.

*Cut fallback:* **resolved — the dataset integration is green as of Day 2** (well ahead of end-of-Day-4), so this fallback was not exercised. The generative baseline stays implemented behind the same `AmountSampler`/`ArrivalSampler` interface and remains selectable by config, but is not the default. (Impl Plan's Day-2 20:00 schedule-guard trigger is reconciled there: it governs Day 2's own schedule, not eval validity, which this end-of-Day-4 line governs — see Impl Plan §Day 2, C2.)

### V2 — Single-feature discriminability audit

For every feature, compute its **univariate AUC** on the training set. Any feature with AUC > 0.95 alone is flagged as a probable generator artifact. Flagged features are either (a) removed, or (b) the generator is fixed so the artifact disappears — never (c) kept quietly.

The audit table ships in the report. It is a two-hour build and it is the most convincing single artifact against the circularity charge, because it is a test the author would fail if they were cheating.

**Expected first casualty:** `amount_is_floor`. Under V1 the attacker's amounts are drawn from the store's own empirical distribution's low tail rather than a fixed constant, which should drop its solo AUC into the 0.7s. If it doesn't, the generator is still leaking.

**v2.1 — amount-floor is explicitly not a Day 1 detection rule.** Because this audit
identifies amount-floor behaviour as the most likely simulator artifact, it must not become
load-bearing detection logic before the audit runs (Day 4). It remains a feature/evaluation
concern only; TRD §6.10 records that no Day 1 rule depends on it.

### V3 — Attack-shape holdout, correctly labelled

Train on easy + medium, evaluate on hard. v1 called this generalisation; it is **interpolation across my own parameterisation**. v2 keeps the split, keeps the number, and relabels it honestly in the report as *"held-out attack shape within the authored parameter family."* The generalisation claim is carried by Tier E instead.

### V4 — Negative controls, expanded

Never in any training split. Per-scenario FP counts, individually named:

| Scenario | Why it is adversarial |
|---|---|
| Flash sale / ad spike | 20× volume, legitimate |
| Corporate / campus NAT | Hundreds of customers, one IP |
| **Indian carrier-grade NAT** | Enormous shared mobile pools; any Western-tuned IP threshold shreds it |
| Genuine retry storm | One customer, 4–5 attempts, expiry typo |
| Subscription renewal batch | Many small identical amounts at once |
| **Genuine foreign-issued traffic (NRI)** | **New in v2** — stops `bin_is_foreign_issued` becoming a free discriminator now that it is a core family |
| **Legitimate customer sharing an attacker's CGNAT IP** | **New in v2** — the F14 case, see §6 |

---

## 5. Tier E — the adaptive adversary (fixes F5)

**Construction.** A config-space search, run offline against the trained detector:

```
maximise   cards_validated_per_hour
subject to  mean_calibrated_score < θ_challenge
            and no incident opened within the episode
search over attack_tiers.yaml parameters:
            pacing, IP pool size, BIN spread, amount sampler,
            session reuse, hour-of-day placement
```

Implementation is a coarse random search or CMA-ES over ~8 parameters, ~200 evaluations, each evaluation replaying a short synthetic episode. Roughly 3 hours to build, minutes to run.

**Safety posture (track compliance).** This searches parameters of a synthetic traffic generator against a local detector. It produces no card numbers, contacts no gateway, and yields no artifact usable against any system other than this one. It is adversarial robustness evaluation — the same category as an adversarial-example benchmark — and the README says so explicitly. If in doubt at submission time, ship the tier with the search *results* frozen into `attack_tiers.yaml` and the search script excluded; the metric survives, the tooling doesn't.

**Reported:** Tier E recall, `cards_exposed_before_alert`, and the parameter vector the search converged on — because *what the attacker had to do to evade us* is itself the finding. If evasion required dropping to 4 attempts/hour across 60 IPs, that is a cost imposed on the attacker, and cost imposed is the product's actual claim.

---

## 6. Label noise and selective labelling (fixes F13, F14)

### 6.1 Enforcement destroys the signal that justified it

Blocked and challenged attempts produce no `auth_outcome`, so `decline_rate_per_ip_5m` and `invalid_cvv_share_ip_5m` fall artificially for an entity **precisely while it is under enforcement** — a feedback loop into our own features.

**v2 mechanisms:**

- **Control arm.** A seeded random `control_fraction` (default 5%) of enforcement-eligible attempts is **not enforced** and is flagged `control_arm = true`. These preserve unbiased outcomes under enforcement, and they are what makes "cards saved" an estimate rather than an assertion. Reported: enforced-vs-control decline rates, and the counterfactual estimate of attempts prevented.
- **Censoring is explicit.** Decline-composition features are computed over *attempts that reached the gateway*, with a companion feature `outcome_coverage_ratio` = outcomes / attempts in window. The model sees the coverage ratio, so "declines vanished because we blocked them" is representable rather than confusing.
- **Reject inference is named as out of scope**, with the credit-scoring literature cited as the place to look. The control arm is v1's honest answer; pretending to more is worse than the gap.

### 6.2 Instance-dependent label noise

A legitimate customer behind the same CGNAT range as an attacker gets a feature vector dominated by the attacker's velocity, with `is_attack = false`. This noise is **correlated with the features**, which breaks the i.i.d. assumption behind both PR-AUC and the calibrator.

**v2:**

- **Measure it.** Every headline metric is reported twice: over all events, and over **"clean" events only** (legitimate events sharing no active entity key with a concurrent attack episode). The gap is the label-noise cost, published.
- **Architect around it** — see TRD §6.2 on composite entity keys and store-relative quantile thresholds instead of absolute counts.
- **Demo through the hard case, not around it.** v1's App Flow J6 step 6 — the "money shot" legitimate checkout completing during the attack — only worked if that customer sat on a different IP. In v2 **the legitimate customer is deliberately placed on the same CGNAT IP as the attacker.** It works because the enforcement key is `(ip, ua_class)` plus card-level corroboration, and because the auto-ceiling is `challenge`, which a human passes and a script does not. The demo now demonstrates the actual claim instead of dodging it.

---

## 7. Splits

| Split | Rule |
|---|---|
| **Temporal** | Train on earlier event-time windows, test on later. No shuffled split — windowed features leak across time. |
| **Attack-shape holdout** | Train easy + medium, test hard. Labelled as interpolation (§4 V3). |
| **Adaptive** | Tier E, never in training, generated *after* the model is frozen. |
| **Negative controls** | Never in any training split, at all. |
| **Clean subset** | A view, not a split: legitimate events with no entity overlap with a concurrent attack (§6.2). |

**Training features come from `feature_snapshot`** — the exact vectors the online path logged at decision time — never from a recomputation. See TRD §6.4. This is what makes point-in-time correctness structural rather than aspirational.

---

## 8. Baselines *(v2.1 — B0/B1/B2/B3, disambiguated)*

Every model number is reported beside four baselines, which are **not interchangeable**:

- **B0 — Day 1 rules-only baseline.** R1 + R2 + R3 (TRD §6.10). Pre-auth,
  outcome-independent, no learned baseline. Answers: *what can Tollgate actually do at
  install-minute-zero?*
- **B1 — naive decline-velocity baseline.** "N declines from one IP within M minutes."
  Offline; requires completed outcomes. The rule a competent engineer would write in an
  afternoon **if completed outcomes already existed.**
- **B2 — BIN-concentration baseline.** Distinct cards per BIN over 5m above a fixed
  threshold.
- **B3 — always-positive and random** — the sanity floor, and the thing that proves the
  harness works.

**B0 and B1 are not the same rule and are never reported as one.** B0 is a live capability
claim, evaluated at decision time with no decline data; B1 is a counterfactual that assumes
information the pre-auth path never has. Conflating them would credit the live detector with
information it never possessed when it decided. **Note:** B2 shares R3's statistic
(`distinct_cards_per_bin_5m`), so B0 ⊃ B2 by construction — the report must not present B2's
contribution as independent of B0's.

If the model only beats the naive baselines on the hard and evasive tiers, **that is the finding and it gets stated in that form.** Reporting where a simple rule suffices reads as confidence, and it is also true.

---

## 9. Report generation

`eval/report.py` regenerates every number from `--seed` and `--config-hash` in one command, writing `eval/outputs/report.md` plus plots. The dashboard's D6 renders the committed artifacts statically — no live computation on stage.

Every reported figure carries, in the artifact itself: `seed`, `config_hash`, `model_version`, `policy_version`, `π_eval`, and the split name. A number that cannot state those six things does not go on a slide.
