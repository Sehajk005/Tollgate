# Tollgate — Technical Requirements Document

**Version:** v2.0 — 22 August 2026 (supersedes v1.0)
**Companions:** PRD v2 · Threat Model v2 · Backend Schema v2 · Eval Protocol v2 · Implementation Plan v2

---

## 1. Scope and constraints

**In scope:** local-first single-merchant risk service — pre-auth scoring API, window store, three-layer detection, policy engine, narrator, operator dashboard (4 screens), demo storefront (4 screens), traffic simulator, evaluation harness.

**Out of scope (v1):** multi-tenant *operation*, horizontal scaling, real gateway integration, auth/RBAC, user accounts, WooCommerce plugin binary, automatic `block`.

| Constraint | Value | Consequence |
|---|---|---|
| Pre-auth latency | p99 < 100 ms | No LLM in path; no network calls except one Redis round trip |
| Availability | **full → rules-only → fail-open** | v1 had no middle rung; a flood bought an unprotected checkout |
| Deployment | `docker compose up` on a laptop | No Kafka, no cloud, no managed services |
| Cardholder data | Never receives raw PAN or CVV | Truncated PAN + caller-supplied hash only |
| Build budget | 10 days solo | Boring, debuggable technology; ~40% of v1 scope deleted |
| **Time** | **All windowing on an injected clock** | Makes 60× replay semantically identical to production |

---

## 2. Stack

| Layer | Choice | Change from v1 |
|---|---|---|
| Scoring API | Python 3.11 + FastAPI + Uvicorn | — |
| Window store | **Redis 7, sorted sets only** | **HyperLogLog removed** — it cannot express a sliding window (§6.1) |
| Atomicity | **One Lua script per score call** | New. Fixes lost-update race and read-your-own-writes (§6.3) |
| Layer 1 | LightGBM, `pred_contrib=True` for exact tree attributions | Drops the separate `shap` dependency |
| Calibration | **Platt (sigmoid) + prior correction** | Was isotonic; overfits small validation sets in the tails where the thresholds live |
| Layer 2 | **Poisson CUSUM (counts) + distinct-card sequential test** | Was mean-score CUSUM, undefined on empty buckets |
| Narrator | Template first; Gemini free tier as a drop-in on Day 8 | Was Gemini-only, built Day 9 |
| Transport | **Server-Sent Events** | Was WebSocket; traffic is one-way, SSE reconnects natively |
| Persistence | SQLite WAL + **one `schema.sql`** | Alembic removed |
| Dashboard | React 18 + Vite + Recharts + Tailwind | — |
| Simulator + eval | scikit-learn, matplotlib (eval); **stdlib + pyyaml only at runtime for `packages/simulator`** — pandas/openpyxl are a dev-only `pyproject.toml` extra, used exclusively once by `scripts/distill_baseline.py` | Baseline now resampled from an external order log (Day 2: UCI Online Retail II, distilled to a committed integer-only profile, not re-run at simulator runtime) |
| Load test | 60-line asyncio script | Locust removed |

**Explicitly rejected:** Kafka, Postgres for hot features, deep learning for Layer 1, isolation forest for Layer 2, HyperLogLog, WebSockets, Alembic.

---

## 3. Repository layout

```
tollgate/
├── packages/
│   ├── contracts/          # Pydantic models + the Decision enum (single source)
│   ├── clock/              # Clock protocol: SystemClock, VirtualClock
│   ├── features/
│   │   ├── store.py        # WindowStore protocol
│   │   ├── redis_store.py  # + windows.lua
│   │   ├── memory_store.py # same protocol, no container
│   │   └── compute.py      # THE feature definitions — one implementation
│   ├── detect/             # rules, model, calibrate, cusum, drift, episode, policy
│   ├── narrator/           # bundle builder, template, gemini client
│   └── simulator/          # baseline, attack, negative, evade
├── services/
│   ├── scorer/             # FastAPI
│   ├── dashboard/          # React, 4 screens
│   └── storefront/         # React, 4 screens
├── eval/                   # harness, report, outputs/
├── tests/
│   ├── acceptance/         # human-authored, hash-pinned, builder may not edit
│   ├── unit/               # builder-authored, advisory
│   ├── oracles/            # pandas_windows.py — test-only, never a data path
│   └── fixtures/           # golden.jsonl + .sha256, handmade_40.jsonl
├── adapters/CONTRACT.md
├── config/                 # store_profile · attack_tiers · cost_model · features
└── docker-compose.yml
```

---

## 4. Time — the design decision v1 never made (fixes F6)

v1 wrote `ZADD tg:{space}:{key} {epoch_ms}` and never said which epoch. Both available answers were wrong: window on merchant-supplied `ts` and you have built the evasion the schema itself warned about; window on `received_at` and 60× replay compresses five minutes of window into five seconds, so the demo's detection is not the production detection.

**v2 resolution — three parts.**

1. **A `Clock` is injected everywhere.** `packages/clock` exposes `now_ms()`. `SystemClock` returns wall time. `VirtualClock(epoch_ms)` is a pure counter with `advance_ms()`/`set_ms()` — it never reads the wall clock and takes no `speed` parameter (Decisions.md decision 20; superseded from this section by decision 27). Nothing in the codebase calls `time.time()` directly — asserted by a grep test (`tests/acceptance/test_clock_discipline.py`).
2. **Windowing uses `ingest_time = clock.now_ms()`,** assigned server-side at request entry. S-class, unforgeable. Client `ts` is stored for audit and produces one evidence value, `clock_skew_s`. It never touches a window.
3. **Replay drives the same clock, and speed lives in the replay driver, not the clock (Decisions.md decision 27).** `services/scorer/replay.py::ReplayDriver` reads virtual time from the generated event stream's own `t_ms` (`vclock.set_ms(epoch_ms + ev.t_ms)`); `speed` only scales the driver's `asyncio.sleep()` between sends, so `speed=0` (no sleep) and `speed=60` produce byte-identical decision sequences — proved by `tests/acceptance/test_replay_virtual_time.py`'s A13, not merely hoped for. Every window boundary, TTL, and (Day 6) CUSUM bucket reads the same clock the events are timestamped against. A 5-minute window is 5 virtual minutes regardless of replay speed. **Window semantics are invariant to replay speed.**

What compression *does* change is wall-clock request throughput, which is a load statement, not a detection statement. The demo banner says exactly that, and the distinction converts v1's honesty banner from a liability into a point in your favour.

**Late arrivals.** `/v1/outcome` for an attempt scored earlier is normal — gateway latency is ~340 ms and at attack rates the outcome for attempt *N* lands after *N+1* is scored. Outcome-derived features are written to the decline windows at **the outcome's own ingest time**, i.e. when the information actually became available. This is what makes point-in-time correctness true rather than aspirational, and it is why offline recomputation is banned (§6.4).

---

## 5. API specification

Base `http://localhost:8080`. Auth: `X-Tollgate-Key` (score path). `/v1/outcome` additionally requires `X-Tollgate-Signature` (HMAC-SHA256 over body + timestamp + nonce, **separate secret**).

| Method | Path | Purpose | Budget |
|---|---|---|---|
| POST | `/v1/score` | Pre-auth decision | p99 < 100 ms |
| POST | `/v1/outcome` | Post-auth ingest, **signed** | async |
| GET | `/v1/incidents` · `/v1/incidents/{id}` | Incident list / detail | — |
| POST | `/v1/incidents/{id}/action` | Operator confirm/override/resolve | — |
| GET | `/v1/metrics/live` | Rolling counters | — |
| **SSE** | `/v1/stream` | Live event + incident push | — |
| POST | `/v1/replay/start` · `/stop` · `/reset` | Demo control | demo only |
| GET | `/v1/replay/status` | Current replay progress | demo only |
| GET | `/healthz` · `/metrics` | Liveness, Prometheus text | — |

**Day-2 replay shapes** (`services/scorer/replay.py`; Decisions.md decisions 25-27).
`POST /v1/replay/start` — API-key authed, same as `/v1/score` — body
`{tier: "easy"|"hard", seed: int=42, speed: int=0, epoch_ms: int|null=null,
hours: int=3}`, 202 + `ReplayStatus`; 409 if already running. `speed=0` means
no wall-clock pacing (full tilt); `speed=N>0` sleeps `Δt_ms / 1000 / N`
between events. `POST /v1/replay/stop` → 200 + `ReplayStatus` (cooperative:
the running loop checks a flag each iteration). `POST /v1/replay/reset` →
clears `InMemoryWindowStore` and the threat rollup, then 200 + `ReplayStatus`
(required, not convenient: `VirtualClock` cannot move backwards, so without
Reset a second Launch in the same process inherits stale window state).
`GET /v1/replay/status` → `ReplayStatus`: `{state: "idle"|"running"|
"stopped"|"finished", tier, seed, speed, sent, total, episode_id,
virtual_time_ms}` — also mirrored onto every SSE event's `replay` key so the
DC strip needs no separate polling while events are flowing.

### 5.1 Admission control ladder (fixes F5's missing rung)

| State | Trigger | Behaviour |
|---|---|---|
| **Full** | Normal | All features, model, CUSUM, policy |
| **Rules-only** | Per-key token bucket exceeded (50 rps sustained / 200 burst), **or** p99 breaches 80 ms for 10 s | Skip model and window reads. **v2.1 — evaluates R1 only**, from the shed counter `INCR tg:{m}:shed:{ip}`. R2 and R3 are **not evaluated in shed mode**: R2 requires a distinct card-hash set per IP and R3 is keyed by BIN, and the shed counter provides neither — an intentional capability reduction under load, not an oversight. **Known limitation:** an `INCR`+TTL counter is a tumbling window with arbitrary phase, so shed-mode R1 is approximate — the same phase defect that removed HyperLogLog in §6.1. Making it exact requires one sorted set on the shed path; deferred and unowned. < 5 ms. Response carries `X-Tollgate-Shed: 1`. |
| **Fail-open** | Redis down, unhandled exception, or the 150 ms client timeout | Return `allow`. Increment `scorer_unavailable`. **Rate-limited and alerted** — sustained fail-open raises an operator alert rather than passing silently. |

v1 jumped straight from full to fail-open, which made "flood the scorer" a complete bypass, published in CONTRACT.md.

### 5.2 The decision enum — six values, exactly (fixes F7 of the test review)

```python
class Decision(StrEnum):          # packages/contracts/decision.py — the only definition
    ALLOW = "allow"
    MONITOR = "monitor"
    THROTTLE = "throttle"
    CHALLENGE = "challenge"
    STEP_UP = "step_up"
    BLOCK = "block"

class ClientOutcome(StrEnum):     # what the storefront can render
    # ... the six above, plus:
    FAIL_OPEN = "fail_open"       # never on the wire; the absence of a decision
```

v1 said "six-member enum" in Phase 0 and "all seven decision values" in Phase 13. There were never seven decisions — the seventh row was the client-side timeout, which is not a decision at all. Two enums, one import, and a test asserting `set(UI_ROUTING_TABLE) == set(ClientOutcome)` makes the contradiction unrepresentable.

`step_up` and `block` are **never returned automatically** unless `allow_auto_block: true` (ships `false`). Automatic ceiling is `challenge`. See Threat Model §4/P1.

---

## 6. Detection pipeline

### 6.1 Window store — sorted sets only (fixes F7)

**HyperLogLog is removed.** `PFADD` has no removal and no per-member score, so `tg:hll:{key}:{win}` with `TTL = window + 60s` is a *tumbling window with arbitrary phase*, not a sliding one. `distinct_cards_per_ip_5m` would reset to zero at a boundary the attacker can straddle, and its value would depend on the key's TTL phase relative to attack start — while the offline path computed a true sliding distinct count. That is textbook train/serve skew on the feature that led the ScoreResponse example.

**v2:** one primitive for everything.

```
ZADD  tg:{merchant}:{space}:{key}:{metric}  {ingest_ms}  {member}
ZREMRANGEBYSCORE  ...  -inf  ({ingest_ms} - {window_ms})
ZCOUNT / ZCARD  → count and exact sliding distinct count
```

- `metric = ev` (member = `attempt_uid`) gives counts; `metric = card` (member = `card_hash`) gives exact distinct cards; `metric = bin`, `metric = amt` likewise.
- Cardinalities here are hundreds, not millions. Exactness costs nothing and removes an entire class of skew.
- **TTL is memory hygiene, never correctness.** Trimming is explicit `ZREMRANGEBYSCORE` against the injected clock. TTLs are set generously and no feature depends on one.
- **Every key is merchant-scoped** (fixes F16 — v1's `tg:z:ip:203.0.113.4` collided across merchants while `tg:cusum:{merchant}` didn't). A test asserts every key produced by the store matches `^tg:[^:]+:`.
- One 24 h datum survives: `card_seen_24h` as a plain `INCR` with TTL, no sorted set.

**Windows:** 60 s · 5 m · 30 m. (24 h dropped except the counter above.)
**Spaces:** `ip` · `ipua` · `card` · `bin` · `asn` · `session`. (`email`, `device` dropped — C-class per Threat Model §2.)

### 6.2 Entity resolution under shared identifiers (fixes F18, F14)

CGNAT was named as a negative control in v1 and had no architectural answer: `ip` stayed a primary key space, `distinct_cards_per_ip_5m` stayed the headline feature, and `asn_is_hosting` doesn't help because CGNAT sits on consumer ASNs.

**v2:**

1. **Composite keys.** `ipua = sha1(ip ‖ ua_class)` is a narrower entity than `ip` alone. `ua_class` is a five-value enum from a deterministic classifier (Threat Model §5.3) — the *class* is used as a key component, the raw string never is.
2. **Enforcement prefers the narrowest key that covers the evidence:** `card_hash` → `(ip, ua_class)` → `ip` → never `asn` alone.
3. **Thresholds are store-relative quantiles, not absolute counts.** `distinct_cards_per_ip_5m` is scored as its quantile against *this store's own learned distribution* of that statistic. A store behind heavy CGNAT learns a distribution with a fat tail and is not shredded by a threshold tuned on Western assumptions. This is the architectural answer, and it costs one extra baseline statistic.
4. **A CGNAT IP cannot reach `block`** — the corroboration rule (Threat Model §4/P3) requires card-level or BIN-level evidence before the ladder passes `challenge`.

### 6.3 The score path — one atomic call (fixes F9, F10)

v1's write path had two defects on one line: `CUSUM update → Redis HSET` was a read-modify-write on a single key across multiple Uvicorn workers (lost updates precisely during the burst regime where the statistic must climb), and window writes happened **after** the response, so attempt *N*'s contribution wasn't in the window when *N+1* was scored — velocity features systematically undercounting exactly under attack.

**v2: one Lua script, `windows.lua`, executed once per score call.** Inside a single atomic execution it:

1. Checks and sets the idempotency key with `SET NX` semantics
2. Writes this attempt into every relevant window (`ZADD`)
3. Trims every touched window against `ingest_ms`
4. Reads back the full raw window vector
5. Increments the current CUSUM bucket counter
6. Returns everything to Python

Then, in-process: feature assembly → rules → model → calibration + prior correction → policy → **respond**. Only the SQLite insert and the SSE publish are asynchronous.

Consequences, all of them tested:
- **No lost CUSUM updates** — the increment is inside the atomic script.
- **Read-your-own-writes** — features include the current attempt by definition, and the definition is the same offline because there is only one implementation (§6.4).
- **One round trip**, so the latency budget survives.

### 6.4 One feature implementation, two read paths (fixes F8)

v1 had two independent implementations of the same feature definitions — Redis for the app, pandas for the eval harness — and asserted they "cannot silently diverge." That is the definition of divergence risk. Simultaneously it praised `feature_snapshot` as the most valuable column while routing training through pandas, so the column would never have been read.

**v2:**

- `packages/features/compute.py` is **the** definition. It talks to a `WindowStore` protocol.
- Two backends implement that protocol: `RedisWindowStore` (production) and `InMemoryWindowStore` (tests, eval sweeps, and the pre-committed Redis fallback).
- **Training reads `feature_snapshot`** — the exact vectors the online path logged at decision time. Point-in-time correctness is structural, not aspirational.
- The pandas brute-force implementation survives **only** as `tests/oracles/pandas_windows.py`, a differential-test oracle over the golden fixture. It is never a data path. A test asserts nothing outside `tests/` imports it.

This keeps the differential-testing value that v1's dual path provided while removing the skew risk that came with it.

### 6.5 Layer 2a — Poisson CUSUM (fixes F11)

v1's signal was the mean calibrated score over 10-second buckets. At the stated persona's ~0.02 attempts/second, **the bucket is empty the overwhelming majority of the time** — the mean is undefined, and it was never said what `S_t` accumulates over hours of them. Worse, the mean of a variable-sized sample is heteroskedastic, and the diurnal baseline guarantees *n* swings by an order of magnitude between 3am and 8pm, so fixed `k` and `h` alarm on quiet nights from noise alone. And taking a mean discards volume, which for a burst attack is the strongest single signal.

**v2 uses counts, with a time-varying in-control rate:**

```
n_t = attempts in bucket t with p_calibrated ≥ τ_flag
λ₀(t) = baseline_rate(hour_of_day) × Δ × p̄₀      (floored at λ_min = 0.01)
λ₁    = ρ · λ₀(t)                                  (ρ = smallest ratio worth detecting, default 5)

S_t = max(0, S_{t−1} + n_t·ln(λ₁/λ₀) − (λ₁ − λ₀))
alarm when S_t > h
```

Four properties, each of which becomes an **analytic** test rather than a recorded observation:

1. **Empty buckets are well-defined:** with `n_t = 0`, `S_t` decreases by exactly `(λ₁ − λ₀)` per bucket, decaying to zero. No undefined mean, no silent accumulation.
2. **Diurnal handled:** `λ₀(t)` varies with the baseline, so quiet nights do not alarm.
3. **Volume retained:** `n_t` is a count.
4. **Steps-to-alarm under a step change is analytically forced:** `≈ h / (λ₁·ln(λ₁/λ₀) − (λ₁ − λ₀))`. A test asserts the implementation matches the closed form on a synthetic step, which is an expectation nothing can game.

`h` is tuned on **negative controls only** to hit a target ARL₀ (asserted: the tuning script never opens attack data), then detection latency is *measured* on attacks. v1 had this right and v2 keeps it.

### 6.6 Layer 2b — distinct-card drift (new)

CUSUM at 10-second buckets is the wrong instrument for ~20 attempts/hour. L2b is a sequential test on **distinct card hashes per entity over 30 virtual minutes**, scored as a quantile against the store's own learned distribution (§6.2/3). It fires on accumulation, not rate.

An incident opens if **either** detector fires. Per-detector attribution is recorded on the incident, so the report can say which shape each tier was caught by — which is a genuinely interesting result and costs nothing to log.

### 6.7 Layer 3 — policy engine

| Tier | Action | `C_FP` | Auto? |
|---|---|---|---|
| `monitor` | Log only | ₹0 | yes |
| `throttle` | Rate-limit the entity key | ₹3.60 | yes |
| `challenge` | Turnstile / CAPTCHA | ₹18.00 | **yes — the ceiling** |
| `step_up` | Force 3DS | ₹54.00 | **operator only** |
| `block` | Reject pre-auth | ₹360.00 | **operator only** |

- **Thresholds are derived**, `θ_T = C_FP(T)/(C_FP(T) + C_FN)`, hand-checkable (Eval Protocol §1.3).
- **Ladder selection by card provenance.** On a domestic Indian card `step_up` is skipped — AFA already binds, so forcing 3DS is not an escalation (Threat Model §7a). Foreign-issued cards keep the full ladder.
- **Hysteresis:** enter at `T_enter`, exit below `T_exit < T_enter`.
- **Entity-scoped, never store-wide** — enforced in the schema, not just in code.
- **Blast-radius cap** `K_max`; on breach the system enters advisory mode and alerts (Threat Model §4/P2).
- **Control arm:** a seeded 5% of enforcement-eligible attempts pass unenforced and flagged, preserving unbiased outcomes (Eval Protocol §6.1).

### 6.8 Feature set — all S/M class *(v2.1: count corrected — see note below)*

**Velocity / cardinality (S+M)**
`attempts_per_ip_60s` · `attempts_per_ip_5m` · `attempts_per_ipua_5m` · `distinct_cards_per_ip_5m_q` · `distinct_cards_per_ipua_5m_q` · `distinct_bins_per_ip_5m` · `distinct_ips_per_bin_5m` · `distinct_cards_per_bin_5m` **(v2.1 — new; R3's statistic, §6.10)** · `attempts_per_session` · `card_seen_24h`

**BIN structure (M)**
`bin_hhi_5m` · `bin_entropy_5m` · `bin_is_foreign_issued` · `foreign_bin_share_5m` · `foreign_bin_share_sigma`

**Amount (M)**
`amount_percentile_vs_store` · `distinct_amounts_per_ip_5m`

**Store-relative (S+M)**
`store_volume_deviation_sigma` · `store_decline_rate_deviation_sigma`

**Decline composition (M, lagged — see §4)**
`decline_rate_per_ip_5m` · `invalid_cvv_share_ip_5m` · `outcome_coverage_ratio`

**Integrity (S)**
`event_id_reuse_count` · `clock_skew_s`

**Deleted from v1:** `checkout_path_depth`, `is_direct_to_checkout`, `is_guest`, `time_on_site_ms` (all C-class — forgeable at zero cost); `inter_attempt_interval_*` (derived from client timing); `email_hash`/`device` spaces; `amount_is_floor` (pending the discriminability audit — it is the most likely generator artifact, Eval Protocol §4/V2).

Features suffixed `_q` are store-relative quantiles rather than absolute counts (§6.2/3).

**v2.1 note on the count.** This section's heading previously read "16 features"; the enumerated list has always contained more (9 velocity + 5 BIN + 2 amount + 2 store-relative + 3 decline + 2 integrity = 23), a pre-existing arithmetic error. Adding `distinct_cards_per_bin_5m` for R3 (TRD §6.10) brings the true count to **24**. No features were silently added beyond that one; the heading is corrected to avoid re-propagating the wrong number.

### 6.9 Layer 1 model

LightGBM binary classifier, ~200 trees, depth 6, early stopping on validation `recall@FPR=1e-3`. `scale_pos_weight` for imbalance; **no SMOTE** — synthesising minority rows over temporally-windowed features leaks across window boundaries. Attribution via `pred_contrib=True`. Rules layer evaluates first so the system works from install-minute-zero.

**v2.1 — the live rules layer and the offline naive baseline are different objects, and are never reported as one.**

- **Live rules (B0)** — R1/R2/R3 (§6.10), pre-auth, outcome-independent, no learned baseline, no BIN metadata join. Active at install-minute-zero and evaluated on every request.
- **Offline naive baselines (B1, B2)** — evaluated over completed historical streams in the eval harness. B1 requires decline outcomes, which the live pre-auth path never has at decision time.

Conflating them would credit the live detector with information it never possessed when it decided. See Eval Protocol §8.

### 6.10 The Day 1 rules layer *(v2.1 — new)*

Three deterministic, pre-auth, outcome-independent rules. No `/v1/outcome`, no decline data,
no learned baseline, no ML model, no BIN metadata join — they are computable from the
in-memory `WindowStore` alone and are active from the first scored attempt.

```
R1  attempts_per_ip_60s        >= 20   ->  minimum tier: throttle    [rate]
R2  distinct_cards_per_ip_5m   >= 15   ->  minimum tier: challenge   [source fan-out]
R3  distinct_cards_per_bin_5m  >= 20   ->  minimum tier: challenge   [issuer fan-out]

final_tier >= max(rule_minimum_tiers)      # rules set a FLOOR, never a ceiling
final_tier <= auto_ceiling (= challenge)   # §5.1/P1, unchanged

no rule fires -> allow
```

- **Windows are half-open** `(t − window, t]`; an event at exactly `t − window` is excluded
  (Impl Plan §1.1's stated convention).
- **Features are inclusive of the current attempt** (§6.3), so the 20th/15th/20th attempt
  is the one that fires.
- **R3 is `distinct_cards_per_bin_5m`** — space `bin`, key `<bin>`, metric `card`. It is
  **not** `distinct_bins_per_ip_5m`, which is the inverse geometry and is not the intended
  card-testing signal. R1 = attempt volume from one IP; R2 = distinct-card fan-out from one
  IP; R3 = distinct-card concentration within one BIN — three different geometries.
- **Scope carve-out from §5.1/P3.** §5.1/P3's corroboration requirement (≥2 independent
  feature families across ≥2 CUSUM buckets before enforcement above `monitor`) governs
  **CUSUM/drift-driven enforcement only** (Layer 2, from Day 6). It does **not** apply to
  R1–R3: their tier floors hold without corroboration, before and after Day 6. Accepted
  residual: a key-holder who forges a single fan-out pattern can force a `challenge` on a
  victim entity without corroborating evidence. Bounded by the unchanged auto-ceiling
  (never `block`/`step_up`), the `K_max` blast-radius cap, and the per-key token bucket.
  Stated in the README beside the existing residual-risk paragraph.
- **amount-floor is explicitly not a Day 1 rule.** Eval Protocol §4/V2 identifies amount-floor
  behaviour as the most likely simulator artifact, subject to the discriminability audit. It
  remains a feature/evaluation concern, never a Day 1 detection rule.
- **Configuration.** Thresholds are seeded from `config/rules.yaml` into the versioned,
  authoritative `policy_config.rules_config` (§3.1). Writing a new value creates a new
  `policy_config` version row; it never overwrites the previous one.

**Rule lifecycle — cold-start, not permanent.** R1–R3's absolute thresholds exist only
because no learned merchant baseline exists on Day 1, and they must not silently become the
permanent detector.

- **R2 upgrade path — specified.** `store_baseline.cards_per_ip_quantiles` (Schema §3.1, JSON
  deciles) replaces the absolute 15 with the store-relative quantile form
  `distinct_cards_per_ip_5m_q` (§6.2/3, §6.8) — the CGNAT fix (F18). **The replacement
  quantile threshold itself is not specified anywhere — future work, not invented here.**
- **R3 upgrade path — unspecified.** `store_baseline` has no cards-per-BIN quantile column.
  **Future work.**
- **R1 upgrade path — unspecified.** `attempts_per_ip_60s` is un-suffixed in §6.8 and carries
  no quantile form. **Future work.**
- Threshold keys are named `*_absolute_coldstart` in `rules_config` so a later swap is a
  visible edit, never a silent reinterpretation.

### 6.11 Narrator contract

- **Trigger:** once on incident open, once on operator-visible escalation. Never per transaction.
- **Input:** numbers, floats, closed-vocabulary enums, pseudonymised entities. No free text. Charset-gated. Full spec in Threat Model §5.
- **Output:** `{ "narrative": str, "confidence_note": str }` — schema-validated, 600-char cap, rendered as plain text. `recommended_action` **deleted**.
- **Template first.** `packages/narrator/template.py` ships Day 3 and renders from the identical bundle. Gemini is a drop-in on Day 8 behind `NARRATOR_BACKEND`.
- **`NARRATOR_ENABLED=false` in eval**, asserted by test — a full sweep produces thousands of episodes and would exhaust the daily free quota in one run.
- **Free-tier note:** prompts may be used for model improvement. Acceptable only because every payload is synthetic and now also pseudonymised. Stated in the README. Verify current rate limits against Google's official page before submission rather than trusting any blog table.

---

## 7. Simulator

Deterministic and seeded; identical config + seed ⇒ byte-identical stream.

**Package layout (Day 2; Decisions.md decision 28), `packages/simulator/`:**
`rng.py` (seeded `getrandbits`-only sampling, `SubStream` per `(seed, label)`),
`profile.py` (loads `config/store_profile.yaml` + the SHA-verified distilled
dataset profile), `identity.py` (opaque card hashes, fictional BIN pool),
`baseline.py` (`BaselineTrafficModel`), `attack.py` (`AttackModel`, easy/hard
shipped Day 2), `stream.py` (merge + canonical serialization + episode
records), `generate.py` (`__main__` CLI and `build_stream()`, the in-process
entry point `services/scorer/replay.py` also calls). Runtime is **stdlib +
pyyaml only** — pandas/openpyxl are a dev-only `pyproject.toml` extra used
exclusively by `scripts/distill_baseline.py`, which lives outside
`packages/simulator` specifically so the package's transitive import
closure never has a reason to include them (verified: `-m safety`).

- **`BaselineTrafficModel`** — arrivals and amounts **resampled from a public real-world e-commerce order log** (UCI Online Retail II, CC BY 4.0 — Decisions.md decision 29), rescaled to `store_profile.yaml`; fictional long-tailed BIN sampling; organic decline model; foreign-issued share matching a plausible Indian merchant mix.
- **`AttackModel`** — easy / hard shipped Day 2 per `attack_tiers.yaml`, every parameter carrying a `source:` field (asserted, `-m` acceptance test A10). `medium`/`evasive` declared `pending: "Day 4"`/`"Day 7"`. Attacks now draw predominantly **foreign-issued** BINs per Threat Model §7b.
- **`EvasionSearch`** — produces Tier E by optimising attack parameters against the trained detector (Eval Protocol §5).
- **`NegativeControlModel`** — flash sale, corporate NAT, Indian CGNAT, retry storm, subscription batch, **genuine foreign/NRI traffic**, **legitimate customer on the attacker's CGNAT IP**.

**Safety constraints, enforced in code and asserted by `-m safety`:** opaque synthetic card identity, no PAN generation, no Luhn construction anywhere, fictional BINs, no expiry/CVV enumeration, no network egress from the simulator package (checked both by a static transitive AST import-closure scan and, at runtime, by a full generation run with `socket.socket` monkeypatched to raise).

---

## 8. Non-functional requirements

| Requirement | Target | Verification |
|---|---|---|
| Score latency | p99 < 100 ms, p50 < 20 ms | asyncio load script, 500 rps |
| Rules-only latency | p99 < 5 ms | same script under shed mode |
| Redis memory | < 200 MB at 20k events/hr | explicit trimming + TTL backstop |
| Cold start | Useful detection from t=0 | rules layer active immediately |
| Failure mode | full → rules-only → fail-open | chaos test on each rung |
| Reproducibility | Byte-identical stream from seed | golden-file test + committed SHA-256 |
| Multi-tenancy | Every Redis key merchant-scoped | key-pattern assertion test |
| PII | No raw PAN, CVV, email, phone at rest | schema-level assertion |
| Trust boundary | No C-class field in the model feature list | `test_trust_boundary.py` |

---

## 9. Observability

Structured JSON logs correlated on `attempt_uid` across score → outcome → incident. Latency histograms on `/metrics`. Counters that carry a claim: `scorer_unavailable` (fail-open engaged), `requests_shed` (rules-only engaged), `enforcement_active` (against `K_max`), `narrator_fallback`, `event_id_reuse`.

---

## 10. Local run

```bash
cp .env.example .env                      # GEMINI_API_KEY optional; template narrator works without it
docker compose up                         # redis, scorer, dashboard, storefront
python -m simulator.generate --seed 42
python -m eval.harness --split all
open http://localhost:5173                # storefront
open http://localhost:5174                # dashboard
```

---

## 11. Open technical decisions

| # | Decision | Default | Trade-off |
|---|---|---|---|
| 1 | Redis vs. in-process windowing | **Redis**, with `InMemoryWindowStore` as a pre-committed fallback behind the same protocol | The fallback costs a scaling claim and nothing else |
| 2 | LightGBM vs. sklearn HistGB | LightGBM | Heavier dependency, better attribution ergonomics |
| 3 | Bucket size for L2a | 10 s virtual | Smaller detects faster, noisier; tuned on negative controls |
| 4 | Platt vs. isotonic | **Platt**, isotonic behind a flag | Both reported; ship the better held-out Brier |
| 5 | ρ (smallest rate ratio worth detecting) | 5 | Lower detects subtler attacks, raises ARL₀ pressure |
| 6 | External baseline dataset | **Resolved Day 2 (Decisions.md decision 29):** UCI Online Retail II, CC BY 4.0, verified 1,067,371 rows / 43.5 MB xlsx / doi:10.24432/C5CG6D. Distilled to a committed, integer-only, SHA-verified profile (`data/baseline/online_retail_ii.profile.json`); raw xlsx gitignored, never committed. | None realized — the generative fallback stays implemented behind the same sampler interface, unused |
