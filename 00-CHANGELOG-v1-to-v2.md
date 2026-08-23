# Tollgate — v1 → v2 Change Log

**22 August 2026.** Every finding from the two reviews, mapped to where it is fixed — or, where it isn't, what was accepted and why.

Read order: this file → Threat Model → PRD → TRD → Backend Schema → Eval Protocol → App Flow → Implementation Plan.

---

## The four changes that matter most

If nothing else survives contact with Day 3, these should:

1. **A trust boundary now exists.** Every field is classed server-observed / merchant-attested / client-asserted, and only the first two may become features, enforcement keys, or LLM inputs. This one table closes two of the three security findings and deletes four features that were free for an attacker to forge. → Threat Model §2
2. **Prevalence entered the cost model.** The pitch's closing number was computed with a missing term that made it arbitrary. The corrected decision rule puts the prior inside the calibrated probability and derives the entire tier ladder from a cost ratio — which turns the flaw into the strongest idea in the project. → Eval Protocol §1
3. **Time is injected.** One `Clock` abstraction resolves event-time-vs-processing-time, makes 60× replay semantically identical to production, and turns the demo's honesty banner from a liability into an argument. → TRD §4
4. **The plan is risk-first.** Walking skeleton on Day 1, launchable attack on Day 2, and a cut ladder with clock times instead of a priority list. → Implementation Plan §0, §4

---

## Security findings

| # | Finding | Status | Where |
|---|---|---|---|
| **S1** | Indirect prompt injection into the narrator via `user_agent`, entity lists, sample attempts | **Fixed** | Threat Model §5. Bundle is integers, floats, closed-vocabulary enums, pseudonymised entities. `user_agent` never leaves the DB — a five-value `ua_class` enum replaces it. "Sample attempts" deleted. Charset gate before dispatch. Output rendered as inert plain text; `recommended_action` deleted from the schema so the LLM cannot even appear to influence a tier. Injection test with a hostile UA fixture. |
| **S2** | `event_id` caller-supplied and load-bearing; reuse suppresses every velocity increment for free | **Fixed** | Threat Model §3. Server-minted `attempt_uid` becomes the primary key; idempotency keys on `sha256(merchant ‖ event_id ‖ payload_digest)` via atomic `SET NX`; **reuse with a different payload becomes a feature and a hard rule** rather than a free suppression. |
| **S3** | No per-key rate limiting + entity-scoped enforcement = a remote "get this IP throttled" primitive | **Fixed, with stated residual** | Threat Model §4. Five mechanisms; the decisive one is **P1: the automatic enforcement ceiling is `challenge`** — `block` and `step_up` require operator confirmation, expressed in the schema as `requires_confirmation` / `confirmed_by`. Plus blast-radius cap, corroboration rule, per-key token bucket, HMAC-signed outcomes. **Residual, documented in the README:** a key-holder can force CAPTCHAs on up to `K_max` entities and consume the rate budget. They cannot block a customer, cannot persist past TTL, cannot act invisibly. |

---

## Design findings

### Tier 0 — would have determined whether you shipped

| # | Finding | Status | Where |
|---|---|---|---|
| **F1** | Bottom-up plan; first end-to-end run on Day 8; Day 10 carrying four deliverables | **Fixed** | Impl Plan §0, §3. Walking skeleton Day 1, demonstrable attack Day 2, Day 10 builds nothing. Budget arithmetic in §2 with the assumptions stated so they can be checked on Day 2 rather than Day 8. |
| **F2** | Droppable list covered screens only; no cut-line for the calibrator, rebuild command, property tests, or negative controls | **Fixed** | Impl Plan §4. Nine cuts, each with a clock time and a named fallback, plus a second ladder for *claims* — cut the claim with the work, never keep the sentence and lose the mechanism. |

### Tier 1 — attacks on the headline claims

| # | Finding | Status | Where |
|---|---|---|---|
| **F3** | Cost-optimal threshold omits the base rate; PR-AUC not comparable across tiers with different densities | **Fixed** | Eval Protocol §1–2. `E[cost] = π(1−TPR)C_FN + (1−π)FPR·C_FP`; prior lives inside the calibrated probability; ladder derived as `θ_T = C_FP/(C_FP+C_FN)` and hand-checkable; cross-tier comparison moves to `recall@FPR`; PR-AUC only within a tier with its prevalence printed. |
| **F4** | Four circularity countermeasures don't ground the generative process | **Mitigated, not closed** | Eval Protocol §4. The legitimate half now comes from a public real-world order log — the only control that structurally breaks the symmetry. Plus a single-feature discriminability audit (>0.95 univariate AUC ⇒ generator artifact) and honest relabelling of the holdout as interpolation. **Accepted:** simulation remains simulation. The sim-to-real gap is stated, not claimed away. |
| **F5** | No evasion model; forgeable Path/Timing features; CONTRACT.md publishes the fail-open timeout | **Fixed** | Threat Model §6 + Eval Protocol §5. Tier E generated by optimising attack parameters against the trained detector. Forgeable features deleted under TB-1. The published timeout is resolved by **closing the hole rather than hiding the number**: degraded ladder full → rules-only → fail-open, with the fail-open path rate-limited and alerting. |
| **F6** | Event time vs processing time unresolved; 60× replay breaks the windows either way | **Fixed** | TRD §4. Injected `Clock`; windowing on server-assigned `ingest_time`; replay drives the same virtual clock so window semantics are invariant to replay speed. Metamorphic test **M6** (1× vs 60× → identical incidents and event-time TTD) is what makes the demo banner true. |

### Tier 2 — metrics that look excellent and mean nothing

| # | Finding | Status | Where |
|---|---|---|---|
| **F7** | HyperLogLog cannot express a sliding window, and it carried the headline feature | **Fixed** | TRD §6.1. HLL removed entirely. Sorted sets only, exact sliding distinct counts, explicit trimming against the injected clock. TTL demoted to memory hygiene so no feature value depends on a TTL phase. |
| **F8** | Two feature implementations; `feature_snapshot` collected but never read | **Fixed** | TRD §6.4, Schema §9. One `compute.py` over a `WindowStore` protocol with two backends. **Training reads `feature_snapshot`.** The pandas implementation survives only as a test-only differential oracle, with a test asserting nothing outside `tests/` imports it. |
| **F9** | CUSUM update is a lost-update race across workers | **Fixed** | TRD §6.3. The increment lives inside the single atomic Lua script. Test: 100 concurrent scores → statistic equals the sequential result. |
| **F10** | Window writes happen after the response, so velocity undercounts exactly under attack | **Fixed** | TRD §6.3. Writes are inside the atomic script and precede the response; features are inclusive of the current attempt, and the definition is identical offline because there is one implementation. |
| **F11** | CUSUM's assumptions violated by the stated persona: empty buckets, heteroskedastic means, diurnal *n*, volume discarded | **Fixed** | TRD §6.5. Poisson CUSUM on **counts** with time-varying λ₀(t). Empty buckets decay `S_t` by exactly `(λ₁−λ₀)`. Steps-to-alarm has a closed form, so the Day 6 test is analytic rather than a recorded observation. Plus **L2b**, a distinct-card sequential test, because CUSUM at 10 s buckets is the wrong instrument for 20 attempts/hour. |
| **F12** | Calibration under prevalence shift; isotonic overfits in the tails where the thresholds live | **Fixed** | Eval Protocol §3. Platt + explicit logit prior correction; π_s is regime-dependent and supplied by Layer 2; reliability reported at both regimes; isotonic kept behind a flag and the comparison published. |
| **F13** | Selective labelling — enforcement destroys the signal that justified it | **Fixed for v1 scope** | Eval Protocol §6.1. Seeded 5% control arm passes unenforced; `reached_gateway` and `outcome_coverage_ratio` make censoring explicit and representable. **Accepted:** reject inference is named as out of scope with the literature pointed at, rather than faked. |
| **F14** | Instance-dependent label noise on shared infrastructure; the "money shot" avoided the hard case | **Fixed** | Eval Protocol §6.2, App Flow J6. Every metric reported twice — all events and clean events — so the noise cost is published. And **the demo's legitimate customer now sits on the attacker's own CGNAT IP**, which the composite entity key, the store-relative quantile threshold, and the `challenge` ceiling make survivable. The demo goes through the hard case instead of around it. |
| **F15** | Decline features arrive lagged; pandas would compute them without the lag | **Fixed** | TRD §4 + §6.4. Decline windows are written at **the outcome's own ingest time**. Offline recomputation is banned outright because training reads snapshots. |

### Tier 3 — inconsistencies and domain gaps

| # | Finding | Status | Where |
|---|---|---|---|
| **F16** | Multi-tenancy claim false at the hot path — some Redis keys scoped, some not | **Fixed** | Schema §4. Every key is `tg:{merchant_id}:…`, asserted by a key-pattern test. NG5 also states plainly that operation is single-tenant. |
| **F17** | Unexamined collision with Indian payments regulation | **Fixed, and turned into an asset** | Threat Model §7, PRD §2.4. RBI Directions 2025 verified: effective 1 April 2026 domestically; cross-border CNP AFA obligations by 1 October 2026. Consequences adopted: `step_up` skipped on domestic cards (AFA is the floor, not an escalation); foreign-issued BINs promoted to a **core feature family**; the thesis restated as *AFA protects the cardholder, not the merchant's invoice.* |
| **F18** | CGNAT named as a negative control with no architectural answer | **Fixed** | TRD §6.2. Composite `(ip, ua_class)` keys, narrowest-key-first enforcement, and — the actual fix — **store-relative quantile thresholds instead of absolute counts**, learned into `cards_per_ip_quantiles`. A CGNAT IP also cannot pass `challenge` without card-level corroboration. |
| **F19** | Track fit: the "AI" is a GBM plus one prose call built on Day 9 | **Mitigated** | PRD §5.3. Template narrator ships Day 3; the LLM is a Day 8 drop-in, so a narrative exists from the first rehearsal and only prose quality rides on Day 8. **Accepted:** the detector is still statistical, and that is still the right engineering call. The positioning answer is now the Bayes decision layer — a prior that moves with the regime is more defensible as "AI risk management" than a bigger model would be. |
| **F20** | Time-to-detect is the wrong headline for the hardest tier | **Fixed** | Eval Protocol §2.2. Headline is **`cards_exposed_before_alert`** — the harm unit — then `attempts_before_alert`, then TTD in event time with the tier's attempt rate printed beside it. |

---

## Test-plan findings

| # | Finding | Status | Where |
|---|---|---|---|
| **T1** | Withholding tests doesn't remove the oracle, it hands it to the builder | **Fixed; authorship claim superseded by D7 — see the v2.1 addendum** | Impl Plan §1, §1.8. The seam runs along **expectation type**, not tests-vs-no-tests. The builder sees every acceptance test; `tests/acceptance/**` is human-authored and pre-commit-locked; builder-written `tests/unit/**` is advisory and never counted as evidence. |
| **T2** | Phase 8's "known answer" is a characterization test wearing a known-answer costume | **Fixed** | Impl Plan §1.1–1.2. All sixteen phases' expectations re-sorted into analytic (acceptance gates) and characterization (`-m characterization`, look-don't-block). The CUSUM expectation is now a closed form; the incident timing oracle is a hand-written fixture. |
| **T3** | Phases 4/5 have an independent oracle; Phase 8 has none | **Fixed** | Impl Plan §1.3–1.4. Differential testing retained (moved out of the data path); **metamorphic relations M1–M8** added for Layer 2, which is exactly the tool for when no independent oracle exists and never will. |
| **T4** | Golden fixture is circular and the freeze isn't a mechanism | **Fixed, with a caveat** | Schema §7. `golden.sha256` asserted every run; `eval_run.fixture_sha256` recorded per number. **`handmade_40.jsonl`** — forty events written by hand with expectations computed on paper — is the non-circular oracle. **Caveat:** `golden.jsonl` is still generated, so it is demoted to characterization duty only. |
| **T5** | Leakage guard checks the module graph, not look-ahead bias | **Fixed** | Impl Plan §1.5. Time-travel test: recompute features from events at or before each attempt's `ingest_time` and assert equality with the logged snapshot. Only possible because training reads snapshots. |
| **T6** | Idempotency tested sequentially for a concurrent hazard | **Fixed** | Impl Plan §1.6. Atomic `SET NX`; 40 simultaneous identical submissions → one increment, 39 stored-decision replies. |
| **T7** | Six decisions in Phase 0, seven in Phase 13 | **Fixed** | TRD §5.2. `Decision` (6) and `ClientOutcome` (8 — adds `shed` and `fail_open`, neither of which is a decision) in one module, with `set(UI_ROUTING_TABLE) == set(ClientOutcome)` asserted. The contradiction is now unrepresentable rather than merely resolved. |
| **T8** | Eight named edge-case categories absent | **Fixed** | Each assigned to a day in Impl Plan §3 and marked *(new)*: crash durability and lock contention (Day 1); cross-environment determinism (Day 2); Redis eviction vs TTL expiry, degenerate-but-not-cold windows (Day 3); inverted scorer, empty splits (Day 4); overlapping incidents, episode spanning the fixture boundary, config version change mid-incident (Day 6); rate-limited and alerting fail-open (Day 7). |
| **T9** | PDF is not runnable, greppable, diffable, or bisectable | **Fixed** | These eight documents are markdown, live in the repo, and the parts that need to be executable are executable: `tests/acceptance/` is the spec, and §5's debugging procedure runs it in day order. |
| **T10** | The schedule doesn't close | **Partially fixed, honestly** | Impl Plan §2. −12 engineer-days of cuts against +4.5 of additions gives ~14–18 days of work. That closes in ten **only** under two stated assumptions — AI-assisted implementation compressing typing but not verification, and the cut ladder actually being used. Both are checkable on Day 2. If both fail, the ladder degrades to a rules-only detector with honest metrics and a working demo, which still satisfies the track. |

---

## What v1 got right and v2 keeps unchanged

Worth naming, because a rewrite this large can throw out load-bearing decisions by accident:

- Merchant vantage point over gateway vantage point
- The §2.1 reframe — the merchant is the instrument, not the victim
- Attempts and scores in separate tables; labels physically isolated in their own
- Tuning CUSUM `h` on negatives and *measuring* detection on positives
- Config versioned rather than mutated
- Entity-scoped enforcement, with store-wide made unrepresentable in the schema
- No Kafka
- The PCI truncation stance
- Pre-auth as the primary path — post-auth detection has already paid for everything it detects
- Publishing the per-tier degradation instead of a blended number
- The self-awareness about simulator circularity in PRD §7 — the instinct was right even though the countermeasures were insufficient

---

## Three judgement calls you should make yourself

1. **Tier E and track rules.** The evasion search optimises synthetic generator parameters against a local detector. I read that as adversarial-robustness evaluation, squarely defensive, and Eval Protocol §5 says so explicitly with a fallback (ship the frozen results, exclude the search script). But *"strictly defence-only, anything offence-capable is disqualified"* is the organiser's line to draw, not mine. If you have any channel to ask them, ask — a one-line clarification is cheaper than a disqualification.
2. **The external baseline dataset.** I've specified "UCI Online Retail II or equivalent" without verifying its licence terms or its fit to Indian order timing. Check the licence before Day 2 and pick a substitute if it doesn't permit redistribution of derived data. The *principle* — one half of the generative process from a source that isn't you — matters more than the specific dataset.
3. **Whether `step_up` survives at all.** With AFA binding domestically, it only applies to foreign-issued cards, and it is cut candidate #2 on the storefront. Keeping it costs a screen; cutting it means the ladder is `monitor → throttle → challenge → block` and the AFA argument gets *simpler* to make on stage. I've kept it because the foreign-card path is now your primary threat model, but it is a defensible cut.

---

## v2.0 → v2.1 reconciliation (23 August 2026)

Seven decisions were issued ahead of Day 1 implementation, each correcting a place where the
shipped v2.0 text conflicted with what Day 1 actually needs to build. Reconciling them
against the nine specification documents surfaced six further findings. This addendum
records both; the underlying documents carry the detailed edits, each marked `(v2.1)`.

### Decisions (D1–D7)

| # | Decision | Affected document(s) |
|---|---|---|
| **D1** | Day 1 hard rules are authoritative: R1 (`attempts_per_ip_60s >= 20` → min. `throttle`), R2 (`distinct_cards_per_ip_5m >= 15` → min. `challenge`), R3 (`distinct_cards_per_bin_5m >= 20` → min. `challenge`) | TRD §6.10 (new), Impl Plan Day 1, PRD §5.1 |
| **D2** | Amount-floor is **not** a Day 1 rule — it remains a feature/evaluation concern pending the Day 4 discriminability audit | Eval Protocol §4/V2, TRD §6.10 |
| **D3** | R1–R3 are **not** deferred to Day 2; Day 1 must produce a meaningfully non-`allow` decision | Impl Plan Day 1 |
| **D4** | `/v1/outcome` stays outside Day 1; R1–R3 are outcome-independent by construction | Impl Plan Day 1 (unchanged; confirmed) |
| **D5** | **Spool-always** replaces the in-memory-queue-with-spool-on-failure design; durability boundary is process death, not power loss | Schema §1 |
| **D6** | Two Vite + React 18 apps (`:5173`, `:5174`), tightly scoped, connected by a dev-server proxy | Impl Plan Day 1, UIUX §10 |
| **D7** | Acceptance-test ownership becomes a review-gate model (temporal/derivational independence, not authorship); `handmade_40.jsonl` is carved out entirely | Impl Plan §1.8, §6; Schema §7 |

### New findings (N1–N6)

| # | Finding | Resolution |
|---|---|---|
| **N1** | R2's tier floor (D1) directly opposed Threat Model §4/P3's corroboration requirement (≥2 feature families, ≥2 CUSUM buckets) | **Resolved 23 Aug:** P3 is scoped to Layer-2/CUSUM-driven enforcement only; R1–R3 floors hold without corroboration, permanently. Residual risk recorded in Threat Model §4/P3 and the README |
| **N2** | The acceptance-test wording ("Decision and ClientOutcome returned") is unsatisfiable literally — `fail_open` is a timeout, not a wire value | **Resolved 23 Aug:** the wire carries `decision` only; `ClientOutcome` is derived client-side by `resolve_client_outcome()`, tested across all 8 values. See App Flow §4 |
| **N3** | Threat Model §4/P4 ("return `allow`") contradicted TRD §5.1/Threat Model §6 (rules-only rung) on what shed mode does | Threat Model §4/P4 corrected to match the rules-only rung |
| **N4** | Even R1 is only approximately computable in shed mode — `INCR`+TTL is a tumbling window, sharing HyperLogLog's phase defect | Documented as a known limitation in TRD §5.1; not fixed (would need a sorted set on the shed path, Day 7) |
| **N5** | `distinct_cards_per_bin_5m` (R3's statistic) was absent from TRD §6.8's feature list, and §6.8's own header count (16) was already wrong (true count 23, now 24) | Feature added; header corrected |
| **N6** | The Vite dev-server proxy (D6) removes the CORS surface rather than exposing it, though it does surface real SSE-through-proxy behaviour | Applied as decided; CORS middleware added on the scorer so the cross-origin path remains independently testable |

### Remaining, explicitly not resolved here

- **R1 and R3 have no specified quantile upgrade path** (only R2's does, via `cards_per_ip_quantiles`) — recorded as future work in TRD §6.10 / PRD §5.4.
- **Shed-mode R1's tumbling-window approximation (N4)** is accepted, not fixed.

See `decisions.md` for the full decision log (Context / Decision / Alternatives / Reasoning / Trade-off / Affected documents / Implementation impact per entry).
