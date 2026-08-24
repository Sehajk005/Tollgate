# Tollgate — Implementation Plan

**Version:** v2.0 — 22 August 2026 (supersedes v1.0)
**Budget:** 10 days, solo
**Companions:** PRD v2 · TRD v2 · Threat Model v2 · Backend Schema v2 · Eval Protocol v2 · App Flow v2

---

## 0. What changed from v1, structurally

v1 was sixteen phases, sequenced bottom-up, with the first end-to-end run on **Day 8** — ten components integrating for the first time with two days left, one of which also carried the README, adapter contract, deck, and video. Day 10 was not a buffer; it was four deliverables.

Three structural changes:

1. **Risk-first sequencing.** The walking skeleton runs end to end on **Day 1**. A launchable attack that visibly changes the dashboard exists on **Day 2**. Everything after Day 2 improves a running system rather than assembling one. Integration is the thing most likely to kill this build, so it happens first, when there is time to recover.
2. **Days, not phases.** Sixteen phases with eight tests each was ~128 tests, most of them characterization tests providing no acceptance value. v2 has ten day-blocks and ~45 tests, of which ~20 are *analytic* acceptance tests (§1).
3. **A cut ladder with trigger times, not a priority list.** v1's "if you fall behind" table covered screens only; the isotonic calibrator, the Redis rebuild, the property tests and the negative-control suite had no declared cut-line. §4 gives every cut a clock time and a named fallback.

---

## 1. Test strategy — the seam runs along expectation type

The question "should I write the tests myself or let the builder write them?" has a wrong premise. Strip the test blocks out of a plan that says *tests before implementation* and the builder writes its own tests, derived from the implementation it just wrote, and they pass by construction. You'd trade "tests you specified, possibly gamed" for "tests the builder specified, certainly self-consistent, and unaudited."

The real distinction is between a **specification** (a property the system must satisfy) and an **oracle** (the thing that decides whether a given run was correct). Sort every assertion by which kind of expectation it carries:

### 1.1 Analytic expectations — ungameable, and they are the acceptance gates

Derivable from the spec without running the system. Any implementation that passes is correct by construction.

| Assertion | Why it's analytic |
|---|---|
| Perfect scorer (reads labels) → PR-AUC 1.0, recall 1.0 | Forced by the definition |
| Random scorer → PR-AUC ≈ prevalence | Forced |
| **Inverted scorer → PR-AUC below prevalence** | The only test for sign errors. v1 had no such test. |
| Always-positive → recall 1.0, precision = prevalence | Forced |
| Cost curve at θ=0 → FP cost × volume; at θ=1 → FN cost × attacks | Hand-computable endpoints |
| Tier ladder `θ_T = C_FP/(C_FP+C_FN)` → {0.065, 0.257, 0.509, 0.874} | Arithmetic from `cost_model.yaml` |
| Poisson CUSUM steps-to-alarm on a synthetic step → `h / (λ₁ln(λ₁/λ₀) − (λ₁−λ₀))` | Closed form |
| Empty buckets → `S_t` decreases by exactly `(λ₁−λ₀)` per bucket | Closed form |
| Single-BIN window → HHI = 1.0; uniform over *n* → entropy = ln *n* | Forced |
| `handmade_40.jsonl` → hand-computed feature values, hand-counted alert point | Human-authored oracle |
| Window boundary: an event at exactly `t − window` is excluded | Stated convention |

### 1.2 Characterization expectations — change detectors only, never acceptance

Recorded by running the system once and writing down what it said. They detect *change*, not *incorrectness*.

v1's Phase 8 treated `time_to_detect_s` matching a committed golden answer as a known-answer test. It isn't — the number can only have come from running the detector and writing down its output. Same for "beats the random baseline by a stated margin" and "exactly one incident."

**v2 rule:** these live in `tests/characterization/`, run under `pytest -m characterization`, and **a failure there is a prompt to look, never a build gate.** They are genuinely useful — a Day 8 change silently moving TTD by 40% is worth knowing about — but they are not evidence of correctness and are never cited as such.

### 1.3 Differential testing — an independent oracle where one exists

v1's Phases 4–5 already had the right idea and didn't notice why it worked: two implementations, different authors in effect, agreeing on the same input.

v2 keeps it but moves it out of the data path: `tests/oracles/pandas_windows.py` is a slow, brute-force, obviously-correct window implementation, used **only** by tests. The production path is `compute.py` over a `WindowStore`. A test asserts nothing outside `tests/` imports the oracle. This preserves the differential-testing value while removing the train/serve skew that a dual production path guarantees (TRD §6.4).

### 1.4 Metamorphic testing — for Layer 2, where no independent oracle exists and never will

This is the fix for v1's real structural hole: Phases 4 and 5 had an independent oracle and Phase 8 had none, so the incident detector was measured only against its own recorded output.

Eight relations. Each is a property that must hold between two runs, without either run's absolute output being known:

| | Relation | Catches |
|---|---|---|
| **M1** | Shift all ingest times by Δ → identical incident count and `attempts_before_alert` | Absolute-time dependencies |
| **M2** | Bijectively rename every IP / BIN / card hash → identical decisions | Hidden identifier ordering, hash-bucket leakage |
| **M3** | Insert additional attack attempts into an episode → `attempts_before_alert` never increases | Sign and monotonicity errors |
| **M4** | Double the attack rate → `attempts_before_alert` does not increase | Rate handling in the CUSUM |
| **M5** | Insert legitimate attempts on unrelated entities → attack-event decisions unchanged | Cross-entity contamination |
| **M6** | **Replay the same stream at 1× and at 60× → identical incidents, identical event-time TTD** | **The whole virtual-clock design.** This single test is what makes the demo's compression claim true. |
| **M7** | Replay an event twice with the same payload digest → windows unchanged | Idempotency |
| **M8** | Process the stream in two halves against a warm store → same result as one pass | Window-boundary and state-carry bugs |

M6 is the most important test in the suite. If it passes, the sentence *"time is compressed 60×, window semantics are preserved"* is a fact rather than a hope.

### 1.5 Leakage tests that catch the leakage that will actually bite

v1 asserted that `attempt_label` is never imported by `packages/detect`. That checks for label leakage through the module graph. It cannot see a feature computed over a window that includes events arriving *after* the attempt being scored — and with sliding windows plus out-of-order arrival, look-ahead bias is the failure mode that was actually built for.

**v2 adds the time-travel test:** for a random sample of 200 scored attempts, recompute the feature vector using only events with `ingest_time ≤ that attempt's ingest_time`, and assert equality with the logged `feature_snapshot`. This catches look-ahead directly, and it is only possible because training reads snapshots rather than recomputing (Backend Schema §9, step 5).

The module-graph assertion stays. It is cheap and it catches a different thing.

### 1.6 Concurrency tests for concurrent hazards

v1 tested idempotency by submitting the same `event_id` twice, in sequence. At 500 rps with an async write buffer, the case that breaks you is two *in-flight* requests interleaving. Sequential replay and concurrent duplication need different mechanisms.

- 40 threads submit the identical payload simultaneously → exactly **one** window increment, one `attempt_uid`, and 39 responses carrying the stored decision.
- 100 concurrent scores → the CUSUM statistic equals the sequential result exactly (this is what the Lua script buys).
- Same `event_id`, mutated amount → **two** window increments and `event_id_reuse_count == 2`.

### 1.7 Fixture integrity

`golden.jsonl` ships with `golden.sha256`; a test asserts it every run; `eval_run.fixture_sha256` records which fixture produced each number. "Frozen after Phase 3" was a sentence in a document; a hash is a mechanism.

### 1.8 Working with an AI builder *(v2.1 — authorship rule replaced by a review-gate model)*

**The protection is temporal and derivational independence, not who types.** An acceptance
test is worthless if it was derived from an implementation that already exists; it is sound
if its expectations trace to a specification line written first. Accordingly:

1. Acceptance tests are written **before** the implementation they gate.
2. They are written **against the specification**, never against observed behaviour.
3. **Every expectation carries a source comment** naming its originating document and
   section — e.g. `# Source: Implementation Plan §Day 1 — R1`. An expectation that cannot be
   traced to a specification line is **flagged for review, not invented.**
4. They enter `tests/acceptance/**` only after human review and approval.
5. Once approved they are **locked**: any later modification requires a `spec:`-prefixed
   commit and explicit human sign-off. The pre-commit check enforces this.

**Exception — `tests/fixtures/handmade_40.jsonl` is excluded from this model entirely and
must not be generated by the implementation agent** (see §6, item 2). Its value depends on
being independent of any code the builder wrote; an agent authoring both the fixture and its
expected values produces a self-consistent artifact with zero oracle value.

- **The builder writes `tests/unit/**`.** Those tests are advisory. They are useful for catching its own regressions and they are never cited as evidence that a day-block passed. This is the standing answer to *"what do I do with the tests it writes anyway?"* — keep them, run them, never count them.
- **One day-block per session.** Paste the block. State that earlier days exist and are green. Do not let it build ahead: a session that produces Days 6 through 9 at once produces exactly the undiagnosable state this plan exists to prevent.
- **Commit convention:** `day-N:` prefix; `git tag day-N-done`. `git log --grep "day-6"` shows what a day touched.

---

## 2. Does the schedule close?

Honestly: **not at solo human typing speed, and pretending otherwise is how Day 8 arrives with nothing integrated.**

| | Engineer-days |
|---|---|
| v1 as specified (review estimate) | 25–35 |
| Cuts (§2.1) | **−12** |
| Additions from the security and correctness fixes (§2.2) | **+4.5** |
| **v2 as specified** | **~14–18** |

Fourteen to eighteen days of work in a ten-day window closes only under two assumptions, both stated so you can check them on Day 2 rather than Day 8:

1. **AI-assisted implementation compresses typing, not verification.** This plan is structured so that verification is cheap — one atomic write path, one feature implementation, analytic expectations written before the code, differential and metamorphic oracles instead of eyeballing. The compression is real on implementation and roughly zero on debugging, integration, and judgement.
2. **The cut ladder actually gets used.** §4 has clock times. If Day 3 ends without a green differential test, Redis is cut that evening — not reconsidered on Day 6.

If neither assumption holds, the ladder in §4 degrades this to a rules-only detector with honest metrics and a working demo, which still satisfies the track. That is the floor, and it is a respectable floor.

### 2.1 What was cut (−12 days)

| Cut | Days |
|---|---|
| Dashboard 9 screens → 4 (D2, D4, D5, D7, D8 and their endpoints, queries, indexes) | −3.0 |
| Dual production feature implementation → one implementation + test-only oracle | −1.5 |
| 16 phases × 8 tests → 10 blocks × ~4.5 tests, with characterization demoted | −1.5 |
| Design-token system, self-hosted font subsets, token sheet page | −1.0 |
| Feature set 25 → 16; spaces 7 → 6; windows 4 → 3 (and their per-feature unit tests) | −1.0 |
| Hypothesis property-test suites → 6 targeted boundary tests | −0.5 |
| Alembic → one `schema.sql` | −0.5 |
| WebSocket → SSE | −0.4 |
| Acquirer JSON/PDF export, post-incident review journey | −0.7 |
| Locust → 60-line asyncio load script | −0.3 |
| Isotonic + separate `shap` dependency → Platt + `pred_contrib` | −0.3 |
| HyperLogLog path and its error-bound tests | −0.3 |
| Storefront polish, S4 flow simplification | −1.0 |

### 2.2 What was added (+4.5 days)

Clock abstraction and virtual clock (0.3) · Lua atomic script (0.4) · trust-boundary tiering and tests (0.2) · HMAC outcome, nonce, rate limiting, shed rung (0.4) · narrator sanitisation and pseudonyms (0.2) · prevalence-aware cost model and regime switching (0.4) · discriminability audit (0.15) · external baseline dataset (0.4) · Tier E evasion search (0.4) · control arm and censoring features (0.2) · Poisson CUSUM + L2b drift (0.3) · Platt + prior correction (0.2) · metamorphic, time-travel and concurrency tests (0.8) · handmade fixture (0.15) · fixture hashing and spool durability (0.15).

---

## 3. The ten days

Each block: goal, deliverables, **acceptance tests (analytic unless marked)**, exit criterion. Acceptance tests are written *before* the block, by you.

---

### Day 1 — Walking skeleton *(~9 h)* *(v2.1 — rules, durability, and UI stack corrected below)*

**Goal.** An event goes in one end and a decision comes out the other, visibly, today, and
the decision must be capable of being meaningfully non-`allow`.

**Deliverables**
- `packages/contracts/` — Pydantic models; **`Decision` (6) and `ClientOutcome` (8) in one
  module**; a `resolve_client_outcome(status, headers, body, error)` function is the sole
  authority mapping wire responses to all eight `ClientOutcome` values (§5.2)
- `packages/clock/` — `Clock` protocol, `SystemClock`, `VirtualClock`
- `schema.sql` + repository functions + **spool-always** writer (Schema §1) — every accepted
  attempt is appended to `spool/attempts-N.jsonl` before the response returns, always, not
  only after a flush failure; a background drainer batches into SQLite
- `packages/features/store.py` (protocol) + `memory_store.py`
- **The three Day 1 cold-start rules** (TRD §6.10), pre-auth and outcome-independent:
  ```
  R1  attempts_per_ip_60s        >= 20   ->  minimum tier: throttle
  R2  distinct_cards_per_ip_5m   >= 15   ->  minimum tier: challenge
  R3  distinct_cards_per_bin_5m  >= 20   ->  minimum tier: challenge
  ```
  Rules set a floor (`final_tier >= max(rule_minimums)`), never a ceiling, and never exceed
  the unchanged `challenge` auto-ceiling. Thresholds are seeded from `config/rules.yaml`
  into the versioned `policy_config.rules_config`.
- `services/scorer` with `/v1/score`, API-key auth
- **Two Vite + React 18 apps**, tightly scoped: `services/storefront` (ugly `S2` checkout,
  `:5173`) and `services/dashboard` (`D1` event ticker over SSE, `:5174`), connected by a
  Vite dev-server proxy. No Tailwind, no design tokens, no router, no component library, no
  state-management framework, no animation — one `App.jsx` per app, plain `fetch()` and
  `EventSource`. This is the walking skeleton, not a UI day.

**Acceptance tests**
- Round-trip all contracts; missing required field raises; `decision` rejects anything outside the six-member enum
- `set(UI_ROUTING_TABLE) == set(ClientOutcome)` ← makes the six/eight contradiction unrepresentable, and both the header (`shed`) and timeout (`fail_open`) paths are exercised through `resolve_client_outcome`
- **No raw PAN field exists on any model** — by field-name inspection
- **No module outside `packages/clock` calls `time.time()` / `datetime.now()`** — grep test
- FK violations rejected (`PRAGMA foreign_keys=ON` actually applied)
- Writing `policy_config` twice creates **two version rows**, never an update
- **R1:** 19 qualifying attempts within 60s → no fire; 20 → fire, minimum `throttle`
- **R2:** 14 distinct cards from one IP within 5m → no fire; 15 → fire, minimum `challenge`
- **R3:** 19 distinct cards within one BIN over 5m → no fire; 20 → fire, minimum `challenge`
- **R3 geometry test** — proves `distinct_cards_per_bin` is measured, not
  `distinct_bins_per_ip`: *(a)* one BIN, 20 distinct cards spread over 20 IPs → R3 fires, R2
  does not; *(b)* one IP, 20 distinct BINs, one card each → R2 fires, R3 does not
- **Durability (spool-always):** send attempts, collect the 200 responses, SIGKILL the
  process during normal/background draining, restart, drain, and verify **every attempt
  that received a 200 is present in SQLite exactly once** — the invariant is tied to what the
  caller was told, not to "zero attempts lost" in isolation. Durability boundary is process
  death, not power loss; no `fsync` is required.
- **Lock contention:** rebuild/eval opens SQLite read-only while the drainer writes; no `database is locked`

**Exit.** `curl` an attempt → decision returned (capable of `throttle`/`challenge`, not just
`allow`) → spooled → row in SQLite → line appears in the browser ticker. **If this is not
true by 20:00, it takes Day 2's morning and Day 2's UI polish is cut.**

---

### Day 2 — A launchable attack *(~9 h)*

**Goal.** Press a button, watch the dashboard change. Act One exists, ugly.

**Deliverables** *(paths corrected to `packages/simulator/` — Decisions.md decision 28; the bare `simulator/` package below is not installed by `pyproject.toml`)*
- `packages/simulator/baseline.py` — arrivals and amounts **resampled from a public real-world order log**, rescaled to `store_profile.yaml`; fictional long-tailed BIN sampling; organic declines; foreign-issued share
- `packages/simulator/attack.py` — easy and hard tiers, every parameter carrying `source:`
- `scripts/replay.py` on `VirtualClock`, plus `services/scorer/replay.py::ReplayDriver` (the in-process HTTP-triggered path — Decisions.md decision 25) and `services/scorer/routes_replay.py`
- `D1` threat band + four counters; `DC` control strip
- `tests/fixtures/golden.jsonl` **+ `golden.sha256`**

**Acceptance tests**
- Determinism: same seed → byte-identical file. Different seed → different file (catches a hardcoded stream) — **A1, A2**
- **Cross-environment determinism:** same seed under a different Python minor version and platform → identical hash, or an explicit documented tolerance *(new — float repr and dict ordering bite here)* — **A3**
- **Baseline content is independent of which attack tier is generated alongside it** — **A4** (Decisions.md decision 31)
- Every event with `is_attack=true` has an `episode_id` present in `episode_truth`
- Hard-tier attempt rate falls inside its configured band (guards against generating an easy attack and calling it hard)
- Hard-tier amounts are distributionally similar to baseline, not a fixed floor
- **Every parameter in `attack_tiers.yaml` has a non-empty `source`** ← the anti-circularity test
- `-m safety`: no Luhn logic, no digit-sequence construction, no `card_number`; no `requests`/`httpx`/`socket` importable from `packages/simulator`
- Fixture hash matches `golden.sha256`
- **Replay at `speed=0` and `speed=60` produce identical decision sequences — A13**; **`ingest_time - epoch_ms == event.t_ms` — A14** (Decisions.md decision 27)
- **End-to-end: a real Launch drives rules, decisions, spool→SQLite, and the threat band — A16**

**Exit.** Launch button → rules fire → threat band moves on screen. **Resolved (Decisions.md decision 29): the external baseline dataset (UCI Online Retail II, CC BY 4.0) was integrated and verified on Day 2 itself, well ahead of this trigger** — the generative-baseline fallback stays implemented but was not needed. The exit demo runs the **easy** tier; hard-tier detectability is measured, not required (Threat Model §6's Tier E paces just under the rules' thresholds by design).

---

### Day 3 — The real feature path *(~9 h)*

**Deliverables**
- `redis_store.py` + `windows.lua` — one atomic script: idem `SET NX` → `ZADD` → trim → read vector → CUSUM bucket increment
- `compute.py` — the S/M-class features (TRD §6.8; count corrected in v2.1, see that section's note)
- `tests/oracles/pandas_windows.py`
- `packages/narrator/template.py` — narratives render from tonight
- `tests/fixtures/handmade_40.jsonl` + hand-computed expectations

**Acceptance tests**
- **Differential:** replay the golden fixture; Redis window values equal the pandas oracle for every key, space, window
- **handmade_40:** every feature value equals the hand-computed number
- Boundary set: event exactly at `t − window` (excluded, stated convention); two events at identical timestamps; out-of-order arrival; event timestamped in the future
- One scoring call issues **exactly one** Redis round trip — asserted by command counter
- **Redis eviction under `maxmemory` is distinguished from TTL expiry** — eviction must degrade to rules-only, not to silently-wrong counts *(new — v1 tested only TTL, and these fail differently)*
- **Degenerate-but-not-cold:** store idle four hours, windows empty, baseline exists → no NaN, no divide-by-zero, no "cold start" misclassification *(new)*
- **Every Redis key matches `^tg:[^:]+:`** — merchant scoping, mechanically *(fixes F16)*
- No NaN or infinity in any feature, ever — including the first event a store ever sees
- **Trust boundary:** feature list ∩ C-class field set is empty
- Nothing outside `tests/` imports the pandas oracle

**Exit.** Differential green; the skeleton now runs on Redis; a narrative renders. **Trigger: if the differential test is not green by 20:00, cut Redis — ship `InMemoryWindowStore` behind the same protocol and state the single-process limitation in the README.**

---

### Day 4 — Trust the ruler *(~9 h)*

**Goal.** The measuring instrument, verified before anything is measured.

**Deliverables**
- `eval/harness.py` — splits, `recall@FPR`, PR-AUC with prevalence, per-tier and clean-subset views
- `config/cost_model.yaml` with `prior_steady_state` / `prior_under_attack`; derived tier ladder
- `simulator/negative.py` — seven scenarios including NRI traffic and legit-on-attacker-CGNAT-IP
- Naive velocity and BIN-concentration baselines
- `eval/report.py`

**Acceptance tests**
- Perfect / random / **inverted** / always-positive scorers hit their analytic values
- **Inverted lands below prevalence** *(new — the only sign-error test)*
- Cost-curve endpoints match hand calculation
- **Tier ladder recomputed from YAML equals {0.065, 0.257, 0.509, 0.874}**
- Temporal split: no test timestamp precedes any training timestamp
- Attack-shape holdout: no hard-tier episode in training
- Negative controls appear in **no** training split
- **Empty split renders without crashing**; report renders with zero incidents *(new)*
- Every reported figure carries seed, config hash, model version, policy version, π, split name

**Exit.** Three sanity scorers produce three analytically expected reports. **You now trust the ruler. Trigger: if not green by 20:00, cut Tier E and the discriminability audit — never the negative controls.**

---

### Day 5 — Layer 1 *(~9 h)*

**Deliverables**
- `scripts/replay --speed 0` → `feature_snapshot` corpus (this is the training substrate)
- `detect/model.py` — LightGBM, `pred_contrib=True`
- `detect/calibrate.py` — Platt + prior correction
- Discriminability audit in the report

**Acceptance tests**
- **Time-travel:** 200 sampled attempts, features recomputed from events at or before their `ingest_time`, equal to the logged snapshot *(new — this is the leakage test that matters)*
- `attempt_label` never imported by `packages/detect` (kept from v1; catches a different thing)
- **No single feature exceeds univariate AUC 0.95** — or it is flagged, removed, and the generator fixed
- Platt improves held-out Brier over raw; **prior correction improves ECE at π₁** — if it doesn't, it's broken
- Calibrated scores in [0,1]; reliability monotone
- Contributions from `pred_contrib` sum to the model output within tolerance
- Inference p99 < 5 ms over 1,000 calls
- `scale_pos_weight` set; **no SMOTE import anywhere**

**Exit.** First real per-tier `eval_run`, with prevalence stated. **Trigger: if not green by 20:00, ship rules-only with a calibrated rule score — costs the model, keeps the honest metrics.**

---

### Day 6 — Layer 2 and policy *(~9 h)*

**Deliverables**
- `detect/cusum.py` — Poisson CUSUM, time-varying λ₀
- `detect/drift.py` — L2b distinct-card sequential test
- `detect/episode.py` — `OPEN → ESCALATED → COOLING → CLOSED`
- `detect/policy.py` — derived ladder, AFA-aware ladder selection, hysteresis, entity resolution, auto-ceiling, `K_max`, control arm

**Acceptance tests**
- CUSUM steps-to-alarm on a synthetic step matches the closed form
- Empty buckets decay `S_t` by exactly `(λ₁−λ₀)` per bucket
- ARL₀ on pure noise at configured `h` hits its target
- **`h` tuning script reads only negative-control data** — asserted by fixture access
- **Metamorphic M1–M8** *(new — the ungameable core, since Layer 2 has no independent oracle)*
- State machine rejects illegal transitions (`CLOSED → ESCALATED` raises)
- Re-fire inside cooldown **merges** rather than opening a second incident
- **Overlapping incidents** and **an episode spanning the fixture boundary** are handled *(new)*
- **A `policy_config` version change landing mid-incident** does not change the open incident's tier resolution — it resolves against `pinned_policy_version` *(new)*
- Hysteresis: an oscillating score produces one tier change, not many
- **Property test: no enforcement action is emitted without an entity key.** Fuzz the input; store-wide must be unreachable
- `step_up` and `block` emit with `confirmed_by IS NULL` and are not in force
- Blast-radius cap → advisory mode at `K_max`
- Control arm: exactly `control_fraction` of eligible attempts pass unenforced, seeded and reproducible

**Exit.** One incident opens on `handmade_40` at the hand-counted alert point. **Trigger: if not green by 20:00, cut L2b — report the hard tier as undetected, honestly.**

---

### Day 7 — Security and the adaptive adversary *(~9 h)*

**Deliverables**
- Idempotency hardening: `SET NX`, payload digest, `event_id_reuse_count`
- Per-key token bucket; rules-only shed rung; fail-open rate limit + alert
- HMAC + nonce on `/v1/outcome`
- Narrator input pseudonymisation and charset gate
- `simulator/evade.py` — Tier E parameter search
- Full eval re-run including Tier E

**Acceptance tests**
- **Concurrency:** 40 simultaneous identical submissions → one window increment, 39 stored-decision replies
- Same `event_id` + mutated payload → two increments, `event_id_reuse_count == 2`
- 100 concurrent scores → CUSUM equals the sequential result
- **Injection:** a fixture whose UA is `... IGNORE PREVIOUS INSTRUCTIONS ...` → string absent from the assembled prompt; charset gate passes; narrative identical to the benign-UA run
- Unsigned / replayed / stale `/v1/outcome` rejected
- Over-budget requests return `X-Tollgate-Shed: 1`, are counted in `tg:{m}:shed:{ip}`, and are scored by rules in < 5 ms
- **Sustained fail-open raises an alert and is rate-limited** *(new — v1 treated fail-open as an unmonitored availability trade)*
- Fail-open under three faults: Redis killed, SQLite locked, model raising — all return `allow` inside the timeout
- Tier E search terminates and writes `evasion_params` to `episode_truth`

**Exit.** Security tests green; Tier E recall published. **Trigger: if the Tier E search isn't converging by 20:00, cut it — ship the threat model's evasion analysis without the empirical number.**

---

### Day 8 — The screens that carry the demo *(~9 h)*

**Deliverables**
- Design tokens — **one hour, hard cap**
- `D0` banners (advisory mode, degraded mode); `D3` full; `D6` metrics from committed artifacts
- Gemini narrator behind `NARRATOR_BACKEND`, template already working
- Storefront S1/S3/S5/S6/S7 finish

**Acceptance tests**
- Threat band renders all four states **with a text label** — no colour-only indicator
- `D3` renders identically with template and LLM narratives; no layout shift
- Narrator invalid JSON / 429 / timeout / charset rejection → template, **no error surfaces to the UI**
- **`NARRATOR_ENABLED` is false in the eval path** — assert no Gemini call during a harness run
- Evidence bundle contains no raw identifiers and no C-class value
- `narrator_call` rows written for every attempt including failures
- `D6` renders from committed artifacts with zero live computation
- Cost curve marks both optima and both regimes; the rupee gap matches a hand calculation
- SSE drop → 5 s polling → recovers on reconnect
- `prefers-reduced-motion` freezes the ticker

**Exit.** Act One and Act Two both walkable. **Trigger: if D6 is not rendering by 20:00, cut the Gemini swap and ship the template.**

---

### Day 9 — Rehearsal and hardening *(~8 h)*

- **Two full rehearsals** of Act One and Act Two, end to end, without intervention
- Chaos: kill Redis mid-demo (and run the rebuild command), flood toggle, kill scorer, SIGKILL mid-flush
- Load: p99 < 100 ms at 500 rps; rules-only p99 < 5 ms
- `adapters/CONTRACT.md` + `woocommerce-snippet.php` — including the **server-minted `session_id`** requirement and the signed-outcome requirement
- README: architecture, PCI note, defence-only statement, **residual risk from Threat Model §4**, free-tier data-usage note, retention note, and the honest statement of what was cut
- **Record the fallback video.** Today, not tomorrow.

**Exit.** Two clean rehearsals and a recorded fallback. **Trigger: if two clean rehearsals haven't happened by 18:00, the recorded video becomes Act One and you present against it.**

---

### Day 10 — Submission *(light, no new build)*

Pitch deck. Final rehearsal. Fresh-clone reproduction test — clone to an empty directory, one documented command, working demo, **on a genuinely clean checkout, not your working tree.** Full suite green. `eval.harness` regenerates every reported number from the committed seed. Submit.

**Nothing is built today.** That is the difference between a buffer and a deadline.

---

## 4. The cut ladder — pre-committed, with clock times

| When | Condition to hold | If not met, cut *this* |
|---|---|---|
| Day 1, 20:00 | Skeleton end-to-end | Nothing — take Day 2's morning; cut Day 2's UI polish instead |
| Day 2, 20:00 | Attack launch visibly moves the dashboard | **Resolved:** dataset integrated same-day (Decisions.md decision 29); this 20:00 line is now a schedule guard only, not an eval-validity deadline — Eval Protocol §4/V1's own end-of-Day-4 line governs eval validity (C2, reconciled) |
| Day 3, 20:00 | Differential test green | **Redis** → `InMemoryWindowStore`, limitation in README |
| Day 4, 20:00 | Harness sanity scorers green | Tier E **and** the discriminability audit |
| Day 5, 20:00 | First per-tier `eval_run` exists | The LightGBM model → rules-only with a calibrated rule score |
| Day 6, 20:00 | One incident on `handmade_40` at the hand-counted point | L2b drift → hard tier reported as undetected |
| Day 7, 20:00 | Security tests green | Tier E search → threat-model analysis without the empirical number |
| Day 8, 20:00 | D3 and D6 render | Gemini narrator → template only |
| Day 9, 18:00 | Two clean rehearsals | The live demo → present against the recorded video |

**Never cut, in any circumstance:**

- **D6 metrics** — this is the track's stated bar. Cutting it forfeits.
- **Negative-control suite** — the false-positive argument is the differentiator.
- **Per-tier reporting** — blended numbers read as fabricated.
- **Prevalence-explicit cost reporting** — a rupee number without its π is the flaw the review found; shipping it again would be worse than shipping no number.
- **The trust-boundary rule** — no C-class field becomes a feature.
- **The `challenge` auto-ceiling** — it is the security posture and the false-positive argument in one decision.
- **The degraded-mode ladder** — fail-open with no middle rung is a published bypass.
- **The fallback video.**

**And a second ladder, for claims rather than code.** If you cut the work, cut the claim with it — never keep the sentence and lose the mechanism. Cut order: multi-tenancy claim → 500 rps claim → sim-to-real generalisation claim → adaptive-adversary claim → cost-optimality claim. The last one is the pitch, so it is the last to go, and if it goes you say so.

---

## 5. Debugging procedure

```
1. pytest tests/acceptance -x        → first failure names the day
2. Green but behaviour wrong?
   pytest -m metamorphic             → relations catch what fixtures cannot
   pytest -m characterization        → what changed since it last worked
3. Still green? Bisect in order:
   Day 3  windows   vs tests/oracles/pandas_windows.py   (independent oracle)
   Day 3  features  vs handmade_40 hand-computed values  (human oracle)
   Day 5  scores    vs recorded eval_run                 (characterization)
   Day 6  incidents vs M1–M8                             (metamorphic)
   Day 6  policy    vs derived threshold table           (analytic)
   The first divergence is where the bug lives.
4. git log --oneline --grep "day-N"
```

This works because every day from 3 onward asserts against something that is **not** its own output: an independent implementation, a human-computed value, a closed-form expectation, or a relation between two runs. v1's bisection chain rested on `golden_answers.json`, which the builder generated — so a bug baked in on Day 3 would have propagated as the expected answer.

---

## 6. Two things to do before Day 1

1. **Write `tests/acceptance/` for Days 1–4 now.** They are the specification. Roughly 20 tests, most of them a handful of lines, and they are the thing that makes the AI-assisted multiplier in §2 safe rather than reckless.
2. **Hand-write `tests/fixtures/handmade_40.jsonl`.** Forty events, by hand, with expected feature values and the alert point computed on paper. One hour. It is the only oracle in the entire system that does not descend from code you or a model wrote, and on Day 6 it is what tells you whether the incident detector works. **v2.1 — this is an absolute carve-out: the implementation agent must not generate this fixture or its expected values, and must not be delegated any part of this task.** An agent that authors both the fixture and its expected values produces a self-consistent artifact with zero oracle value — the fixture's entire purpose is independence from any code the builder wrote.
