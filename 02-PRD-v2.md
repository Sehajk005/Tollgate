# Tollgate — Product Requirements Document

**Pre-authorization card-testing defence for Indian merchants**

| | |
|---|---|
| **Track** | Razorpay Buildathon — Track 02, AI Risk Manager |
| **Loss class** | Card testing / BIN enumeration |
| **Author** | Sehaj |
| **Version** | **v2.0 — 22 August 2026** (supersedes v1.0, 21 August) |
| **Build window** | 10 days, solo |
| **Companions** | Threat Model v2 · TRD v2 · Backend Schema v2 · Eval Protocol v2 · App Flow v2 · Implementation Plan v2 |

---

## 1. Overview

Tollgate is a drop-in risk service between a merchant's checkout and their payment gateway. It scores every authorization attempt *before* submission, detects card-testing campaigns in progress, and applies a graduated response — monitor, throttle, challenge — instead of a binary block.

Single merchant's own stream. No cross-merchant data, no gateway-level access, no historical fraud labels required on day one.

**What changed in v2:** the security posture is now specified rather than assumed (Threat Model v2), the cost thesis is prevalence-aware rather than arithmetically broken (Eval Protocol §1), the threat model is fitted to Indian regulation rather than imported from the US, and roughly 40% of v1's build scope has been deleted so that the remainder can actually ship in ten days.

---

## 2. The problem

### 2.1 The reframe

In a card-testing attack, **the merchant is not the fraud victim — the merchant is the instrument.**

An attacker holding stolen card numbers needs to know which are live. Your checkout tells them for free: submit a ₹1 authorization, read the response, sort the card. They don't want your goods. They want your gateway's answer.

### 2.2 Why merchants don't catch it

Merchants look for fraud in chargebacks. Card testing produces almost none — nobody disputes a ₹1 auth. The dashboard looks clean while the attack runs. By the time the loss is visible, it has been paid.

### 2.3 Where the money goes

| Channel | Mechanism |
|---|---|
| Auth fees on declines | Charged on failed attempts too. A 50,000-attempt campaign is a real invoice. |
| Authorization-rate degradation | Approval ratio collapses. Acquirers monitor this actively. |
| Acquirer and scheme standing | Sustained decline spikes trigger monitoring programmes; at the extreme, MATCH-list termination. |
| Deferred fraud | Cards validated on your site return as genuine fraud elsewhere. |

### 2.4 Why this still matters after RBI's AFA mandate — **new in v2**

The RBI Authentication Mechanisms Directions, 2025 made two-factor authentication mandatory for domestic digital payments from 1 April 2026. A judge will ask whether that kills the problem. It does not, and the answer is the sharpest sentence in the pitch:

> **Two-factor authentication protects the cardholder. It does not protect the merchant's invoice, their approval rate, or their standing with their acquirer.**

Every attempt still costs a fee and still lands in the approval-rate denominator, whether it dies at AFA or at the issuer. And the attack that AFA does *not* suppress — foreign-issued cards tested at an Indian merchant, where the issuer sits outside the domestic mandate until at least 1 October 2026 — is now the primary threat model. See Threat Model v2 §7 for the full treatment, including the consequences for the tier ladder.

### 2.5 Problem statement

> *My checkout is being used as a free card-validation service. I cannot see it while it is happening, and by the time I can, I have already paid for it — in fees, in approval rate, and in my standing with my acquirer.*

---

## 3. Who this is for

**Primary — the operator-owner.** Indian D2C / small e-commerce merchant, 500–5,000 orders/month, WooCommerce or custom, on Razorpay or similar. No fraud team. Needs to be told *an attack is happening now*, in plain language, with one recommended action.

**Secondary — the integrating developer.** Two HTTP calls, under an hour, no ML configuration.

**Explicit non-user:** enterprise fraud teams with existing vendor stacks.

**Persona consequence that v2 takes seriously:** at 5,000 orders/month this store sees ~0.02 attempts/second. That number invalidates several v1 design choices — most visibly the CUSUM formulation, which assumed a bucket would usually contain events. See TRD §6.5.

---

## 4. Goals and non-goals

### Goals
- **G1** Detect card-testing campaigns from a single merchant's own telemetry.
- **G2** Alert within a bounded number of *attempts* — the harm unit is cards exposed, not seconds elapsed.
- **G3** Keep false positives economically cheap via graduated response, with a **hard auto-enforcement ceiling at `challenge`**.
- **G4** Report metrics honestly: per tier, per prevalence, with an adaptive adversary included and the negative-control breakdown named scenario by scenario.
- **G5** Integrable in under an hour via a documented adapter contract.
- **G6 — new.** Be defensible under a hostile read: no attacker-controlled field becomes a feature, an enforcement key, or an LLM input.

### Non-goals
- **NG1** Not a general fraud engine.
- **NG2** Not a bot/WAF layer.
- **NG3** No cross-merchant intelligence in v1.
- **NG4** Nothing offence-capable.
- **NG5 — new.** Not multi-tenant in operation. `merchant_id` scopes every key and every row (including Redis, which v1 got wrong), but one deployment serves one store.
- **NG6 — new.** No automatic `block` or `step_up`. Both require operator confirmation. This is a security decision, not a UX one — see Threat Model §4/P1.

---

## 5. Solution design

### 5.1 Three layers, two units of prediction

**v2.1 — the Day 1 live rules layer.** Before Layer 1's model exists (Day 5), three
deterministic, pre-auth, outcome-independent rules are active from install-minute-zero:
attempt velocity per IP (R1), distinct-card fan-out per IP (R2), and distinct-card
concentration within one BIN (R3). See TRD §6.10 for the exact thresholds and windows. This
is the Day 1 rules layer (B0 in Eval Protocol §8) — a different object from the offline
naive baselines described in §7 below.

**Layer 1 — attempt scoring.** Unit: the transaction. Where precision/recall/PR-AUC live. Features are **S-class (server-observed) and M-class (merchant-attested) only** — see Threat Model §2. Families:

- Velocity and distinct-cardinality over IP, `(ip, ua_class)`, card hash, BIN, ASN, session
- **BIN structure** — concentration (HHI, entropy), and the **foreign-issuance family** now elevated to core per §2.4
- Decline-code composition within window, with an explicit outcome-coverage ratio
- Amount vs. this store's own distribution
- Store-relative deviation (volume and decline rate in sigmas against a learned diurnal baseline)

**Layer 2 — episode detection.** Unit: the episode. **Two detectors, because one instrument cannot cover both attack shapes:**

- **L2a — Poisson CUSUM on counts** for burst attacks. Counts, not mean scores, with a time-varying in-control rate. Empty buckets are well-defined; volume is not discarded.
- **L2b — sequential distinct-card accumulation** over 30 minutes, scored as a quantile against the store's own distribution. This is the instrument for low-and-slow, where a 10-second bucket contains nothing and CUSUM is useless.

**Layer 3 — graduated response.** `monitor → throttle → challenge`, automatically. `step_up` and `block` require operator confirmation. Tier thresholds are *derived* from the cost model (Eval Protocol §1.2), not hand-picked, and the ladder is selected by card provenance: `step_up` is meaningless on a domestic Indian card where AFA already binds.

### 5.2 Pre-auth is the primary path

The economic claim is avoiding fees on attempts that should never have been submitted.

- **Pre-auth (inline):** `POST /v1/score` before gateway submission. p99 < 100 ms.
- **Post-auth (webhook):** `POST /v1/outcome`, **HMAC-signed with a separate secret** (v1 left this forgeable), supplying decline codes for labelling.

### 5.3 Where the LLM goes

Detection is entirely statistical. No LLM in the scoring path.

One tightly-scoped call **per incident**, off the hot path, converting a fixed-schema evidence bundle into an analyst-readable narrative. In v2 that bundle contains **only integers, floats, and closed-vocabulary enums, with pseudonymised entities** — no free text, no sample attempts, no user-agent strings. The narrator's `recommended_action` field is deleted: it explains a decision the policy engine already made and cannot influence one. Rationale and tests in Threat Model §5.

**Track-fit note (was F19).** In a track called *AI Risk Manager*, the narrator is the component a non-technical judge reads as "the AI", and v1 scheduled it second-to-last with no slack. In v2 the **template narrator ships on Day 3** and the LLM is a drop-in replacement on Day 8. The narrative exists from the first demo rehearsal onward; the only risk carried to Day 8 is prose quality.

### 5.4 Cold start

Tollgate learns *this store's* normal — hourly volume shape, decline rate, BIN spread, amount distribution, and **the store's own distribution of distinct-cards-per-IP** (which is what makes CGNAT survivable). Rules-only detection runs until the baseline stabilises.

**v2.1 — the rules have an explicit lifecycle.** R1–R3's absolute thresholds (TRD §6.10)
exist only because no learned baseline exists yet, and must not silently become the
permanent detector. R2's upgrade path is specified — `cards_per_ip_quantiles` replaces the
absolute threshold with a store-relative quantile once the baseline stabilises (the CGNAT
fix, F18) — but the replacement threshold itself, and the equivalent upgrade paths for R1
and R3, are not yet specified anywhere and are recorded as future work rather than invented.

---

## 6. Data strategy

**The most attackable part of the project, treated accordingly.**

No public dataset of merchant checkout authorization attempts with card-testing labels exists. Simulation is mandatory. v1's countermeasures all operated on the attack half, which is why they didn't close the loop.

**Baseline attribution (Decisions.md decision 29, resolved Day 2).** The legitimate half is grounded in UCI *Online Retail II* (Chen, D., 2012; [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); doi:10.24432/C5CG6D) — a real transaction log, not a generative model. Only a derived, integer-only profile is committed; the raw dataset is gitignored and never redistributed. See `README.md` and `data/baseline/README.md` for the full attribution and regeneration instructions.

**v2's controls** (full detail in Eval Protocol §4):

1. **The legitimate half comes from a source that isn't me** — baseline arrivals and amounts resampled from a public real-world e-commerce order log. This is the only control that structurally breaks the symmetry.
2. **Single-feature discriminability audit** — any feature with univariate AUC > 0.95 is flagged as a generator artifact and removed or fixed. The table ships in the report.
3. **Four difficulty tiers, published separately**: easy / medium / hard / **evasive**. Tier E is generated by optimising attack parameters *against the trained detector*. It will produce the worst number in the deck and it is the only one a security-literate judge will believe.
4. **Negative controls**, never trained on, reported per named scenario — now including genuine foreign-issued traffic and a legitimate customer sharing an attacker's CGNAT IP.
5. **Honest relabelling** — the easy+medium → hard holdout is described as interpolation within an authored parameter family, which is what it is.

---

## 7. Success metrics

**Layer 1**
- **`recall @ FPR = 0.001`, per tier** — the cross-tier comparator, because PR-AUC is prevalence-dependent and tiers have different densities
- PR-AUC *within* a tier, with that tier's prevalence printed beside it
- All headline numbers reported twice: all events, and **clean events only** (no entity overlap with a concurrent attack). The gap is the label-noise cost.

**Layer 2**
- **`cards_exposed_before_alert`** — the harm unit, and the headline
- `attempts_before_alert` (median, p90)
- `time_to_detect_s` in event time, with the tier's attempt rate beside it
- Episode FPs on the negative-control suite, per scenario

**The differentiating metric — cost-calibrated thresholding**

The track asks for false-positive cost. Most submissions append a sentence. Tollgate makes it the deliverable — correctly this time:

```
E[cost | θ, π] = π·(1−TPR(θ))·C_FN + (1−π)·FPR(θ)·C_FP(tier)
```

Prevalence enters multiplicatively, lives inside the calibrated probability via prior correction, and the tier ladder falls out of the cost ratio `θ_T = C_FP(T)/(C_FP(T) + C_FN)` rather than being hand-picked. Deliverables: cost curves at both regimes, a sensitivity ribbon across π, and — the number that demonstrates the architecture — **the saving from letting the CUSUM state move the prior, versus a fixed threshold.**

**Baseline comparison.** Every number sits beside **B0** (the live Day 1 rules layer — R1/R2/R3, pre-auth, outcome-independent), **B1** (an offline naive decline-velocity rule, requiring completed outcomes B0 never has), and **B2** (a BIN-concentration rule). B0 and B1 are never reported as the same object — see Eval Protocol §8. If the model only wins on hard and evasive tiers, that is stated in that form.

---

## 8. Demo plan

**Act One — live interception.** Legitimate traffic through a minimal checkout. Attack launched. Dashboard fires an incident; tier escalates; **a genuine customer completes checkout from the same CGNAT IP the attacker is using.** That last clause is the demo — v1's version quietly staged the customer on a different IP, which dodged the hard case rather than demonstrating it.

Replay runs on a **virtual clock**: time is compressed 60×, and every window, TTL, and CUSUM bucket is driven by that same clock, so window semantics are identical to production. The compression factor is on screen at all times, and the honesty banner now says something stronger than v1's could:

> *Time is compressed 60×. Window semantics are preserved — the system runs on a virtual clock. Detection latency is reported in event time.*

**Act Two — the evidence.** Per-tier `recall @ FPR`, including Tier E. Negative-control FPs by scenario. The discriminability audit. The cost curves at both prevalence regimes with the regime-switch saving marked. Calibration at both regimes.

**Integration proof.** No WooCommerce plugin. A documented two-call adapter contract plus a ~20-line snippet against `POST /wc/store/v1/checkout`, with the session-minting requirement (Threat Model §2) stated as a contract term.

---

## 9. Safety and track compliance

- Simulator emits **event records only** — never card numbers. Card identity is a synthetic opaque hash; BINs are fictional.
- **No PAN generation.** No Luhn construction. No expiry/CVV enumeration anywhere.
- **No live gateway contact.** No network egress from the simulator package — asserted by test.
- **The Tier E search is defensive evaluation.** It searches parameters of a synthetic generator against a local detector. It produces no card numbers and no artifact usable against any other system. Stated in the README; if there is any doubt at submission, ship the frozen results and exclude the search script.
- **Publishing the fail-open timeout in CONTRACT.md is an evasion instruction** — v1 published it while claiming the design revealed nothing that assists evasion. v2 resolves the contradiction by *closing the hole instead of hiding the number*: the degraded-mode ladder is full → rules-only → fail-open, and the fail-open path is rate-limited and alerts.

---

## 10. Architecture

```
Checkout ──POST /v1/score──▶ Scoring API (FastAPI)
   │                             │
   │                    ┌────────┴─────────┐
   │                    ▼                  ▼
   │           WindowStore interface   Layer 1
   │           ├ RedisWindowStore      (LightGBM + rules,
   │           └ InMemoryWindowStore    S/M features only)
   │           (one atomic Lua call:         │
   │            write → read → CUSUM)        ▼
   │                    │            L2a Poisson CUSUM
   │                    │            L2b distinct-card drift
   ▼                    │                    │
Gateway                 │                    ▼
   │                    │            Policy engine
   └─POST /v1/outcome──▶│            (cost-derived ladder,
      (HMAC-signed)     │             auto-ceiling = challenge)
                        │                    │
                   SQLite (WAL)      ┌───────┴────────┐
                   source of truth   ▼                ▼
                                Narrator          Dashboard
                             (template → LLM)     (React, SSE)
```

**Deliberately absent:** Kafka, WebSockets (SSE is one-way and simpler), Alembic (one `schema.sql`), HyperLogLog (cannot express a sliding window — see TRD §6.1).

---

## 11. Ten-day plan (summary — full version in Implementation Plan v2)

The sequencing principle changed completely. v1 was bottom-up with first integration on Day 8; v2 is a **walking skeleton by end of Day 1 and a demonstrable end-to-end attack by end of Day 2**, after which every day improves a running system rather than assembling one.

| Day | End-of-day state |
|---|---|
| 1 | **Skeleton runs.** Checkout → score → decision → SQLite → dashboard ticker. In-memory windows, three hard rules, no model. |
| 2 | **Act One in ugly form.** Simulator baseline + one attack tier, virtual-clock replay, threat band moves on screen. |
| 3 | Redis window store behind the same interface, atomic Lua path, S/M feature set, differential test vs pandas oracle. Template narrator. |
| 4 | **Ruler trusted.** Eval harness, prevalence-aware cost model, negative controls, naive baselines. |
| 5 | Layer 1 model, Platt calibration + prior correction, discriminability audit. |
| 6 | L2a + L2b, episodes, policy engine, entity resolution, control arm. |
| 7 | **Security hardening day** — rate limits, HMAC, injection defences, degraded-mode ladder — then Tier E search and re-run. |
| 8 | D3 Incident Detail, D6 Metrics, LLM narrator swap. |
| 9 | Two full rehearsals, chaos tests, CONTRACT.md, README. |
| 10 | **Buffer. No new build.** Deck, video, submit. |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Scope exceeds the window | ~40% of v1 cut before Day 1; pre-committed cut ladder with trigger times, not a priority list |
| Simulator circularity | Legitimate half from an external dataset; discriminability audit; Tier E; honest relabelling of the holdout |
| A judge finds a security hole on stage | Threat Model v2 exists; the three findings from review are closed and the residual risk is in the README |
| Cost claim challenged as arbitrary | Prevalence explicit; curves at both regimes; sensitivity ribbon; ladder derived by hand-checkable arithmetic |
| RBI AFA question | §2.4 and Threat Model §7 |
| Redis integration eats a day | `WindowStore` is an interface; the pre-committed fallback is the in-memory store with the limitation stated |
| Live demo fails on stage | Deterministic virtual-clock replay; Act One recorded as fallback on Day 9, not Day 10 |
| Solo — one lost day | Day 10 carries no build; the cut ladder has trigger times |

---

## 13. Roadmap (out of scope for v1)

- Opt-in cross-merchant blocklist — the honest answer to the fully-distributed attacker that a single-merchant vantage point cannot see
- Real WooCommerce and Shopify plugins against the v1 contract
- Reject inference on enforced attempts, replacing the control-arm estimate
- Rolling EM estimation of the serving prior, replacing the two-regime constant
- Issuer notification when a validated card is detected
