# Tollgate — Project Presentation Script

**Audience:** you, the presenter. This is a study-and-deliver document, not
software documentation. Read it end to end before the demo; on the day, follow
it top to bottom.

**Companion documents**

| File | Use |
|---|---|
| `DAY-9-DEMO-SCRIPT.md` | the terse operator card — six acts, one table, what to click |
| `PROJECT-PRESENTATION-SCRIPT.md` (this file) | the full narrated version — what to say, why it matters, what an evaluator will ask |
| `DEPLOYMENT-GUIDE.md` | taking the exact container you demo to AWS |
| `QA-AUDIT-DAY-9-2026-09-03.md` | the evidence behind every "verified" claim below |
| `Decisions.md` / `Flow.md` | the *why* and the *actual code path* for anything you get pushed on |

**Everything in the live-demo acts (6, 7) is derived only from what actually
succeeded in `DAY-9-DEMO-REHEARSAL-1.md` (Pass B) and `DAY-9-DEMO-REHEARSAL-2.md`
against the real Docker Compose stack.** Nothing here is aspirational.

**Total budget:** ~12–15 min talk + ~5 min live demo + Q&A. If you have less,
Acts 1–3 + the live demo + Act 12 is the minimum viable version.

---

## Table of contents

- **ACT 1 — The problem: card testing**
- **ACT 2 — The goal: what Tollgate is for**
- **ACT 3 — Architecture, component by component**
- **ACT 4 — The detection pipeline (the technical core)**
- **ACT 5 — The metrics, one at a time**
- **ACT 6 — The live demo (SAY / DO / SCREEN / BACKEND / WHY / IF ASKED)**
- **ACT 7 — What each J6 step proves**
- **ACT 8 — Security**
- **ACT 9 — Reliability**
- **ACT 10 — Performance**
- **ACT 11 — D6 / evaluation and reproducibility**
- **ACT 12 — Known limitations (how to answer "what's wrong with it")**
- **ACT 13 — Closing statement**
- **LIKELY EVALUATOR QUESTIONS** (the big Q&A bank)

---

# ACT 1 — The problem: card testing

### Say it simply first

> "Criminals buy stolen card numbers in bulk — thousands at a time, cheaply,
> because most are already dead. Before they spend real money, they need to know
> which cards are still live. So they find a merchant with a checkout and they
> run tiny transactions against it — a one-rupee authorization, a small
> donation, an add-to-wallet — over and over, with a different card each time.
> A card that authorizes is live, and a live card is worth a hundred times what
> they paid for it. This is called **card testing**, or **carding**. The
> merchant sees a flood of tiny failed payments, a pile of processor fees, and
> eventually a wave of chargebacks. The card-holders see fraud on cards they
> never used here."

### Then the technical framing

**What the attacker is doing, precisely:**

- Many **authorization attempts**, each individually unremarkable: a valid-looking
  PAN, a plausible expiry, a small amount, a normal-looking user agent.
- The attempts come from a **small pool of IPs** (often one, sometimes a few
  dozen behind proxies) and draw cards from a **small pool of issuing BINs**
  (the 6-digit prefix that identifies the bank) — because a stolen batch tends
  to come from one breach, one issuer, one region.
- They are **fast** relative to how a real store fills — a genuine shopper makes
  one or two attempts; a tester makes hundreds in minutes.
- They are **pre-authorization**: the attempt never becomes a completed order.
  There is no shipment, no account history, no chargeback *yet*.

**Why ordinary fraud detection is insufficient here:**

1. **It is built for completed transactions.** Classic fraud models score an
   order using the outcome trail — was it charged back, does the account have
   history, does the shipping address match. Card testing produces **none of
   that** at decision time. By the time a chargeback lands, the card list has
   already been validated and sold.
2. **Each attempt looks fine in isolation.** A low-value authorization with a
   valid-format card and a normal UA has no per-transaction tell. The signal is
   **not in any one attempt — it is in the shape of the aggregate**: distinct
   cards per IP, distinct cards per BIN, attempts per IP per minute.
3. **The blunt fix breaks real customers.** "Just block the IP" fails because
   **carrier-grade NAT (CGNAT)** means a whole city's mobile users can share one
   public IP. Block it and you have blocked thousands of legitimate shoppers to
   stop one attacker who will rotate IPs in seconds anyway.
4. **Latency budget.** This runs in front of the authorization call. It has a
   ~100 ms budget and it must not add a network hop to a language model or a
   database on the hot path.

**What signals the system therefore needs to observe** — all *pre-auth*, all
*aggregate*, all in the attack's own timeframe:

- attempts per IP over a short window (velocity)
- **distinct cards per IP** and **distinct cards per BIN** over a few minutes
  (enumeration — the defining shape)
- how those counts *drift* away from what this store normally looks like
  (a store-relative baseline, not a global threshold)
- and it needs to attribute all of that to the **narrowest entity** that
  actually covers the evidence — one IP, one (IP, user-agent-class) pair, or one
  card — **never** the whole store.

---

# ACT 2 — The goal: what Tollgate is for

### The one-sentence goal

> "Tollgate sits in front of the authorization call and decides, in about
> fifteen milliseconds, whether a checkout attempt is part of a card-testing
> burst — and if it is, it adds **one friction step**, never a wall, and it
> tells a human operator exactly why."

### What it must detect

- Card-testing bursts, **pre-authorization**, measured in **event time** (the
  attack's own clock), not wall-clock.
- The aggregate shape: enumeration across cards / BINs from a concentrated
  source, drifting away from the store's learned normal.

### What it must **not** incorrectly block

- A legitimate shopper who happens to share a **CGNAT IP** with an attacker.
- A flash sale, a corporate NAT, a retry storm, a subscription-batch run, NRI
  traffic, a shared office IP — these are the **seven negative-control
  scenarios** the baseline and the CUSUM threshold are tuned against, using
  **only** those scenarios, never attack data.
- Anyone, ever, **automatically** with a hard block. The maximum the system
  applies on its own is `challenge` — one extra verification step.

### How it balances security and availability

Three ideas, in priority order:

1. **Never wall off a paying customer without a human.** The automatic ceiling
   is `challenge`. `step_up` (3-D Secure) and `block` exist, but only an
   operator can confirm them, per incident, per entity.
2. **Degrade loudly, never silently.** If a dependency dies, the scorer
   **fails open** — it returns `allow`, marks the attempt `degraded_reason:
   fail_open`, and raises one alert per window. It never returns a 5xx and never
   silently changes a decision. If the merchant is flooded, it **sheds** to a
   rules-only rung and stamps `X-Tollgate-Shed: 1`. Every degradation writes a
   row.
3. **Everything is reproducible.** The attack replay is seeded and
   virtual-time-driven: same events, same order, same virtual times, same
   decisions, every run. The evaluation artifact is committed and byte-checked.
   You can re-run the demo and get the same numbers.

### The core design philosophy (memorize this — it answers half the questions)

> **"Score yes, decide no."** The machine-learning model computes a *score*. It
> **never** makes the *decision*. The decision comes from an explicit,
> auditable policy: rule floors that cannot be trained away, a cost-derived tier
> ladder, a challenge ceiling, hysteresis, a blast-radius cap, and — for
> anything above `challenge` — a human.

Defense in depth: a cheap deterministic **rules floor** that always runs; a
**statistical drift** layer that is store-relative and tuned only on benign
traffic; a **calibrated model** that adds resolution where the rules are blunt;
and a **human** for the irreversible actions.

---

# ACT 3 — Architecture, component by component

Six containers (`docker-compose.yml`), started in dependency order:
`redis` → one-shot `bootstrap` → `scorer` → `storefront` + `dashboard`
(`redis-small` starts alongside for one test only).

```
Browser
  |-- storefront  :5173   (Vite dev server + React; the merchant checkout)
  `-- dashboard   :5174   (Vite dev server + React; the risk operator console)
        |  each app proxies /v1/* to the scorer; the proxy IS the "declared trusted edge"
        v
  scorer  :8080   (FastAPI, ONE uvicorn worker)
     auth -> resolve client IP -> admission -> compute_features -> rules R1..R3
          -> Layer 2a CUSUM (alarm regime) -> Layer 1 model + calibration
          -> Layer 2b drift SPRT -> incident state machine -> PolicyEngine.resolve
          -> decision -> spool append -> SSE publish
          -> [out of band, after publish] optional Gemini narration
        |                                  |
        v                                  v
  redis  :6379                       SQLite (WAL)  tollgate.db
  sliding-window store               written only via spool -> background drainer
  (one atomic Lua script/score)      auth_attempt / attempt_score / incident /
                                     incident_entity / tier_transition /
                                     enforcement_action / narrator_call / ...
```

For each component: **what it is · why it exists · what enters · what comes out
· what state it owns · how it talks to the others · what happens if it fails.**

### storefront (`services/storefront`, port 5173)

- **What:** a Vite dev server serving a small React app — the "Kesar & Co."
  merchant checkout. Screens: `S1` product → `S2` checkout → one of `{S3`
  challenge / `S5` confirmed / `S6` blocked / `S7` throttled`}`. `S4` (3-D
  Secure step-up) is **not built** — it is unreachable without a confirmed
  `step_up`.
- **Why:** the demo needs a real merchant surface that issues real
  `POST /v1/score` calls, so the audience sees protection from the customer's
  side (they see *nothing* — that is the point).
- **In:** a card number typed in the browser. **Out:** a `POST /v1/score` with
  `card_hash` = SHA-256 of the digits (computed in the browser via
  `crypto.subtle`), the first-6 `bin`, the `last4`, expiry, amount. **The PAN
  never leaves the browser.**
- **State it owns:** which screen is showing. Nothing else.
- **Talks to:** the scorer, via the Vite `/v1` proxy. The proxy is the
  **declared trusted edge** — its container IP is in the scorer's
  `TOLLGATE_TRUSTED_EDGE_HOSTS`, so an `X-Forwarded-For` it stamps is honoured.
- **If it fails:** the shopper cannot check out. The scorer and dashboard are
  unaffected. The plain (non-`?demo=1`) storefront also **fails open** on a
  transport error — it shows "Order confirmed" rather than erroring at the
  customer (TRD §5.2). The `?demo=1` readout surfaces the real HTTP status so
  *you* can see a misconfiguration (DEF-D9-012 fix).

### dashboard (`services/dashboard`, port 5174)

- **What:** a Vite dev server + React app — the risk operator's console. Three
  routes (`#/live`, `#/incident`, `#/metrics`): `D0` shell (nav + **Stream
  Rail** signature band + monochrome system-state banners), `D1` live (threat
  band + four metric tiles + event ticker + the demo control strip pinned to the
  bottom), `D3` incident read model, `D6` metrics.
- **Why:** the whole point of the product is that a human can *see* what the
  detector is doing and *act* on it. A detector with no operator surface is not
  a product.
- **In:** the SSE stream from `GET /v1/stream`, plus a concurrent back-fill of
  `GET /v1/stream/recent` on mount. **Out:** operator actions — replay
  Launch/Stop/Reset, incident confirm/resolve, and (demo only) flood / kill-scorer.
- **State it owns:** ephemeral UI state only. On refresh it opens the SSE stream
  **and** back-fills concurrently and merges through a de-duplicating set, so a
  dashboard opened mid-attack reconstructs the true state rather than showing an
  all-clear screen. The **backend owns the replay lifecycle** (Decision 102) —
  the dashboard never derives it from the event stream; it reads
  `/v1/replay/status`.
- **Talks to:** the scorer, via its own Vite `/v1` proxy (also a declared edge).
- **If it fails:** the operator loses visibility. Scoring and enforcement
  continue untouched. The connection chip reads `connecting -> live`; `polling`
  and `reconnecting` are reserved for *real* degradation, and an SSE drop falls
  back to 5-second polling of `/v1/stream/recent?after=<cursor>`.

### scorer (`services/scorer`, port 8080)

- **What:** a FastAPI app run by **one** Uvicorn worker (`--factory`, no
  `--reload`). This is the whole detection engine.
- **Why one worker:** the token bucket, the availability monitor, the
  stored-decision cache, the `InMemoryWindowStore` fallback, the replay driver,
  the incident registry and the policy engine all live **in process** on a
  `ScorerState` object (Decision 71 / 87). This is a deliberate trade: it keeps
  TRD §6.3's one-Redis-round-trip invariant and the p99 budget, at the cost of
  horizontal scale-out (see Act 12 / `DEPLOYMENT-GUIDE.md` §9).
- **In:** `POST /v1/score` (from the storefront), replay + incident control
  (from the dashboard), `POST /v1/outcome` (a merchant webhook, HMAC-signed),
  `/v1/demo/*` (gated). **Out:** a `ScoreResponse` (`decision` only on the
  wire), an SSE event, spooled rows.
- **State it owns:** everything in-process listed above, plus the spool file.
- **Talks to:** Redis (window store), SQLite (via the spool -> drainer, never on
  the request thread), and — out of band — Gemini.
- **If it fails:** at the request level it **fails open** — any exception from
  `score_attempt()` is caught and the response is `allow` with a
  `degraded_reason: fail_open:<reason>` row; a sustained breach logs `ERROR` and
  raises one `alert` per window. It **never** returns a 5xx from `/v1/score`.
  Authentication is fenced off from this — a cold key cache + an unavailable
  auth DB returns **503**, never `allow`.

### redis (port 6379)

- **What:** the sliding-window store. One `EVALSHA windows.lua` per score call
  does every `SET NX` (idempotency), `ZADD` / `ZREMRANGEBYSCORE` (window
  maintenance), `ZCARD` / `ZRANGE` (reads), `SADD` (distinct-card sets),
  `INCR` (24-hour card counter), and `HINCRBY` (CUSUM bucket) **atomically, in
  one round trip** (TRD §6.3).
- **Why:** the features are all "counts over a moving time window per entity" —
  exactly what sorted sets are for — and doing it in one Lua script is what
  keeps the compute path inside the latency budget and keeps 100 concurrent
  scores behaving identically to 100 sequential ones.
- **In:** a `ScorePathRequest`. **Out:** a `FeatureVector` (24 canonical
  features + `trusted` / `degraded_reason` + `idem_digest`).
- **State it owns:** all window / CUSUM-bucket / idempotency / shed-counter keys,
  every one TTL'd.
- **If it fails:** on startup the scorer logs a fallback notice and runs on
  `InMemoryWindowStore` — same protocol, single-process, not restart-durable.
  Mid-request, a dead Redis socket raises within a 150 ms timeout and `/v1/score`
  **fails open**.

### SQLite (`tollgate.db`, WAL mode)

- **What:** the system of record. `merchant`, `policy_config`, `store_baseline`,
  `auth_attempt`, `attempt_score`, `incident`, `incident_entity`,
  `tier_transition`, `enforcement_action`, `narrator_call`, `auth_outcome`,
  `outcome_nonce`, `eval_run`, and more (`schema.sql`).
- **Why SQLite:** it is a single-node demo. WAL mode gives readers a consistent
  snapshot while the one writer works.
- **Write path:** the score path **never touches SQLite directly**. It appends a
  JSON line to a spool file and `fsync`s it *before* constructing the response —
  that is what makes the `200`'s durability guarantee true. A background
  **drainer** thread reads the spool from a persisted byte offset and writes to
  SQLite (`INSERT OR IGNORE` on deterministic PKs, so a re-drain is idempotent).
- **If it fails / is locked:** reads proceed on the WAL snapshot; the score path
  is unaffected because it writes the spool, not the DB; `drainer_failures`
  stays 0 and the drainer catches up when the lock clears.

### bootstrap (one-shot container)

- **What:** `scripts/compose_bootstrap.py` runs `seed_merchant` (merchant row +
  API key + outcome HMAC secret) -> `learn_store_baseline` (the `store_baseline`
  row; **Layer 2 will not load without it**) -> `tune_cusum` (a `policy_config`
  version with a populated cost-derived `thresholds` map and a tuned `cusum_h`),
  then computes and writes the D6 `config_hash` for the dashboard.
- **Why a separate one-shot:** these three steps must succeed *before* the
  scorer can serve the full path, they must be **idempotent** (a second
  `docker compose up` must not re-seed or sprawl policy versions), and they must
  be **footgun-safe** — `seed_merchant` uses `INSERT OR IGNORE`, so a naive
  re-run against an existing merchant would print a key that was never stored
  and every request would 401. This script either reuses a key that hashes to
  the stored row or **fails loudly**. It never prints a dead key.
- **Out:** rows in `tollgate.db`, and `deploy/compose.env` (gitignored) with
  `VITE_TOLLGATE_API_KEY`, `TOLLGATE_OUTCOME_SECRET`, `TG_CONFIG_HASH`.
- **If it fails:** the scorer's `depends_on: service_completed_successfully`
  blocks — the stack does not come up half-bootstrapped.

### replay / evaluation path

- **Replay driver** (`services/scorer/replay.py`): plays a **seeded,
  virtual-time-driven** recorded attack (`tier` in `{easy, medium, hard,
  evasive}`) through the **identical** `score_attempt()` the storefront calls,
  with its own `VirtualClock` and a seed-derived `UlidGenerator`. Same events,
  order, virtual times, decisions, every run. `speed=60` runs it at 60x
  wall-clock; `pace_from: "episode"` scores the pre-attack hours at full tilt
  and only paces the ~20 s before the attack, so it is visible in seconds.
  Eight wire states, backend-owned (Decision 102). `run_id` (a ULID minted per
  run) is the frontend's single reset signal.
- **Evaluation harness** (`eval/`): a fully **offline** harness, independent of
  the live scoring path. It generates simulator traffic, splits it (temporal
  test + attack-shape holdout + a dedicated `tier_e` split), scores it, and
  renders `d6.json` + `report.md`. It forces `NARRATOR_ENABLED=false` — an eval
  run makes **zero** Gemini calls.

### narrator / LLM path

- At **incident open only**, `_resolve_layer2` renders a **template** narrative
  synchronously from a closed vocabulary and stores it on the incident row.
- Then, **after** the terminal SSE publish — outside the Layer-2 atomic block,
  outside the latency window — `score_attempt` *optionally* schedules an
  out-of-band Gemini call (Decision 98), only if `NARRATOR_BACKEND=gemini` and a
  key is set. On success it replaces the narrative with `narrative_source="llm"`;
  on **any** failure (bad JSON, 429, timeout, charset) the template narrative
  stays and only a `narrator_call` row with `fallback_used=1` is written. **No
  exception ever reaches a request or the UI.** The LLM cannot influence a
  decision, a tier, or enforcement.

### detection layers, enforcement, degraded modes — see ACT 4 and ACT 8.

---

# ACT 4 — The detection pipeline (the technical core)

Order of operations inside `score_attempt()` (all inside the measured latency
window, all before the single `await event_bus.publish`):

```
compute_features -> rules R1..R3 -> Layer 2a CUSUM regime -> Layer 1 model + calibration
  -> Layer 2b drift SPRT -> incident state machine -> PolicyEngine.resolve -> decision
```

For each mechanism: **what · why · what signal · what it solves · what breaks
without it · how it moves the decision.**

### 4.1 The rules floor — R1, R2, R3

- **Analogy:** the smoke detector. Cheap, deterministic, always on, cannot be
  argued with.
- **What:** three absolute-threshold rules read from one feature fetch
  (`config/rules.yaml`):
  - **R1** `attempts_per_ip_60s >= 20` -> minimum tier `throttle`
  - **R2** `distinct_cards_per_ip_5m >= 15` -> minimum tier `challenge`
  - **R3** `distinct_cards_per_bin_5m >= 20` -> minimum tier `challenge`
- **Signal:** raw velocity and enumeration counts per entity.
- **Problem it solves:** it guarantees a floor. No amount of model drift or
  calibration error can let an obvious burst through — if R2 fires, the tier is
  **at least** `challenge`, full stop.
- **Without it:** a mis-trained or mis-calibrated model is the only thing
  standing between an enumeration burst and `allow`. Unacceptable.
- **Decision impact:** `decision = max(model/policy tier, minimum rule tier)`,
  then clamped by the challenge ceiling. The rules can only *raise* the tier.

### 4.2 The 24 statistical features + the discriminability audit

- **What:** `packages/features/compute.py` defines 24 canonical features —
  per-IP / per-BIN / per-session velocity and fan-out, BIN concentration (HHI,
  entropy), amount dispersion, card-seen-in-24h, and (declared but not yet fed)
  outcome-derived and BIN-metadata features.
- **The audit:** `scripts/train_l1.py` runs a univariate Mann-Whitney AUC on
  every feature over the training set. Any feature with AUC **> 0.95** is a
  near-perfect single-feature discriminator — on synthetic training data that is
  a **"likely simulator artifact"** (Eval Protocol §4). Those features are
  **excluded from the model** (zeroed on input) but **stay active in the R1/R3
  rule floors and B0**.
- **Result:** **6 features excluded** (per-IP rate / fan-out counts,
  distinct-IPs-per-BIN, distinct-amounts-per-IP), **14 constant `0.0` un-fed
  slots** (`store_baseline` / `bin_metadata` / `/v1/outcome` are other days'
  work) -> the model runs on **4 live features**.
- **Why this matters:** it is an honesty mechanism. We refuse to let the model
  score itself a trophy on features that only separate *because the simulator
  built them that way*. The cost is a weaker model; we report that openly.

### 4.3 The model — `l1-lgbm-v1`

- **Analogy:** a second opinion from a specialist. It adds resolution where the
  rules are blunt, but it does not get to sign the chart.
- **What:** a LightGBM classifier — `objective=binary`, 200 trees,
  `max_depth=6`, `scale_pos_weight = n_neg/n_pos`, `num_threads=1`,
  `deterministic=True`, `seed=42`. Committed as JSON (`models/l1-lgbm-v1.json`);
  the booster `.txt` is regenerated by `train_l1`.
- **Signal:** the 4 live features.
- **Problem it solves:** on `hard` traffic the rules do not fire at all (spread
  over enough IPs and BINs that no single count crosses a threshold). The model
  recovers **recall 0.73 on `hard` where B0 gets 0.13**.
- **Without it:** `hard` and `evasive` traffic mostly gets `allow` from the rules.
- **Decision impact:** the model produces `score_raw` and `score_calibrated`,
  which feed the policy's cost-derived tier ladder. It **never** directly
  produces a decision — "score yes, decide no."

### 4.4 Calibration + serving-prior correction

- **Analogy:** a thermometer that reads correctly whether it is summer or winter.
- **What:** a **Platt** calibrator fit on a held-out `calib` slice
  (`models/platt-v1.json`), then a **serving-prior correction** — a logit shift
  by `ln(pi_s/(1-pi_s)) - ln(pi_t/(1-pi_t))` (Eval Protocol §3.2) that re-bases
  the calibrated posterior from the training prevalence `pi_t` to the **serving
  regime** prevalence `pi_s`.
- **Signal:** the model margin + the current alarm regime.
- **Problem it solves:** the training data is ~64% positive; production steady
  state is ~0.1% positive and "under attack" is ~90%. A raw probability trained
  at 64% prevalence is meaningless at either. The correction makes
  `score_calibrated` an actual probability *for the regime we are in*.
- **Result:** ECE at pi0 drops from **0.262 raw -> 0.0007** with Platt + prior;
  at pi1 from **0.395 Platt -> 0.281** with the prior added (the prior correction
  helps at pi1 — the well-conditioned criterion).
- **Without it:** the cost-derived threshold ladder is applied to a number that
  is not a probability, and every operating point is wrong.

### 4.5 Prior correction depends on regime — resolved BEFORE the model

- The alarm **regime** (`in_control` vs `alarm`) is resolved from CUSUM buckets
  that are **already fully scored** *before* the model runs — so the prior that
  produces `score_calibrated` is a pure function of past buckets. No
  circularity: the model's own output does not feed back into the prior that
  scaled it.

### 4.6 Layer 2a — CUSUM

- **Analogy:** watching a bathtub fill. You do not react to one splash; you
  react when the water is clearly rising faster than the tap explains.
- **What:** a one-sided **Poisson CUSUM** over `tau_flag`-gated flagged counts
  per 10-second bucket (`packages/detect/cusum.py`). `tau_flag` = the cost
  model's `throttle` tier threshold (~0.0647) — **derived from
  `config/cost_model.yaml`, never a literal** (Decision 70). Empty buckets decay
  the statistic by exactly `(lambda_1 - lambda_0)`. `cusum_h` (the alarm
  threshold) is **tuned only on the seven negative-control runs** by
  `scripts/tune_cusum.py`, to an **ARL_0 >= 8,640 buckets** — at most one false
  alarm per merchant per 24 virtual hours.
- **Signal:** the rate of flagged attempts at the **store** level, vs the
  store's learned benign rate `p_bar_0`.
- **Problem it solves:** a store-relative, self-calibrating "is the overall flag
  rate abnormal" detector that picks the serving prior (regime).
- **Without it:** you need a global "flags per second" threshold, which is wrong
  for every store.
- **In practice in the demo:** with the weak 4-feature model, `p_bar_0 ~ 0.60`,
  so CUSUM is conservative and **Layer 2b (SPRT) is the operative Layer-2
  detector for `easy`/`medium`**. This is reported, not tuned around.

### 4.7 Layer 2b — SPRT on distinct-card fan-out

- **Analogy:** a sequential hypothesis test — keep sampling until you can say
  "this IP is enumerating" or "this IP is normal" with controlled error.
- **What:** a one-sided **Wald SPRT** on the **95th-percentile exceedance** of
  `distinct_cards_per_ip_30m`, per `ip` and per `ipua` (Decision 73). `p_0 = 1 -
  0.95` by construction; `p_1 = 0.5`; type-I `alpha = 0.01`, type-II `beta =
  0.05`. Toggle: `config/policy.yaml: drift.enabled`.
- **Signal:** how often this specific IP's 30-minute distinct-card count exceeds
  the store's learned 95th percentile.
- **Problem it solves:** per-entity enumeration detection that accumulates
  evidence over time with **controlled false-positive rate**, instead of a
  single-window threshold.
- **Result in the demo:** opens **2 `drift` incidents**, `ESCALATED`,
  **time-to-detect ~ 76-78 seconds of event time**.

### 4.8 Distinct-card counting — why it is the load-bearing signal

- Card testing is, definitionally, **one source trying many cards**. A normal
  shopper uses one card, maybe two. `distinct_cards_per_ip_5m`,
  `distinct_cards_per_bin_5m`, `distinct_cards_per_ip_30m` are the features that
  encode exactly that shape. R2, R3 and the SPRT are all built on it.
- **Without it:** you are left with raw volume, which a flash sale also produces.

### 4.9 Entity resolution — `card -> ipua -> ip`, never store-wide

- **What:** `resolve_entity` picks the **narrowest key that covers the
  evidence** (`packages/detect/policy.py`): a decision driven by R3 alone is
  BIN-scoped; CUSUM and drift both point at the source `ip`; a card-level signal
  resolves to `card`. **`asn` is never used. Store-wide is unrepresentable —
  there is no schema row for it.**
- **Problem it solves:** it is the CGNAT answer. Enforcement attaches to `(ip)`
  or `(ip, ua_class)` or `(card)` — so a co-tenant on the same IP with a
  *different* UA class, or simply a single clean attempt, is a **different
  entity** and is not swept up.
- **Without it:** you are back to blocking IPs and breaking mobile networks.

### 4.10 Hysteresis

- **What:** rising to a tier requires `p >= theta_T`; falling below it requires
  `p < theta_T - 0.08` (`hysteresis_gap`, `config/policy.yaml`).
- **Problem it solves:** flapping. Without the gap, an entity hovering near a
  threshold toggles `challenge`/`allow` every attempt — noise for the operator
  and the customer.

### 4.11 Corroboration (P3)

- A **rules-only** decision (no model, no Layer-2 corroboration) is held to a
  higher bar before it escalates an incident — the policy requires the signal to
  be corroborated across rule families. Prevents a single noisy rule from
  driving enforcement on its own.

### 4.12 The challenge ceiling

- **What:** `apply_auto_ceiling` clamps every **automatic** tier to
  `challenge` (`auto_ceiling` in `policy_config`, default `challenge`;
  `allow_auto_block = False`).
- **Problem it solves:** the system can inconvenience a suspected attacker (one
  extra check) but can **never** wall off a customer by itself. `step_up` and
  `block` are *proposed* — written as `enforcement_action` rows with
  `requires_confirmation = 1`, `confirmed_by = NULL`, `applied_at = NULL` — and
  only an operator's `POST /v1/incidents/{id}/confirm` applies them and raises
  that entity's ceiling in the live `PolicyEngine`.

### 4.13 The incident state machine

- **What:** `OPEN -> ESCALATED -> COOLING -> CLOSED` (`CLOSED` terminal; a
  re-fire during cooldown **merges** into the open incident). It owns the harm
  fields: `attempts_before_alert`, `cards_exposed_before_alert`,
  `time_to_detect_s` (in **event time**), `cusum_stat_at_alert`, `peak_tier`.
- **Problem it solves:** it turns a stream of per-attempt signals into **one
  case** an operator can reason about, with a measurable time-to-detect and a
  measurable blast radius.

### 4.14 The control arm

- **What:** a **deterministic** 1-in-every-20 selection (`control_fraction =
  0.05`) of attempts that are scored normally but receive **no enforcement** —
  a holdout.
- **Problem it solves:** without a control group you cannot measure whether
  enforcement is doing anything. The control arm is what makes "enforcement
  reduced validated cards per hour by X" a measurable statement rather than an
  assertion.

### 4.15 The blast-radius cap — K_max advisory mode

- **What:** beyond `k_max_entities` (default 10) simultaneously-enforced
  entities, the `PolicyEngine` enters **advisory mode**: it still *proposes*
  tiers and opens incidents, but it stops *applying* enforcement, and the D0
  banner goes monochrome.
- **Problem it solves:** a bug, a misconfiguration, or an adversary with a key
  cannot turn Tollgate into a denial-of-service against the merchant's own
  customers. There is a hard cap on how many entities the system can be
  frictioning at once without a human.

---

# ACT 5 — The metrics, one at a time

All numbers below are from the committed `eval/outputs/d6.json` (schema v2, base
seed 42, `config_hash a7db8c61...`) and Phase 5 / Phase 10 of the Day-9 audit.
**Do not quote a number that is not here.**

For each metric: **What I say · What it means technically · Why it matters ·
What good looks like · This project's result · The limitation.**

### 5.1 Recall @ target FPR (per tier)

- **What I say:** "Recall is: of the attack attempts, how many did we catch —
  measured at a fixed low false-positive rate so it is comparable."
- **Technically:** true-positive rate at the operating threshold that produces
  the target false-positive rate on the negatives of that split.
- **Why it matters:** it is the headline "does it work" number, and pinning the
  FPR is what stops anyone gaming recall by flagging everything.
- **What good looks like:** high recall at a genuinely low FPR. The spec does
  **not** set a single pass bar — every figure is reported with its measurement
  conditions.
- **This project's result** (`temporal_test`):

  | tier | `l1-lgbm-v1` | B0 (live R1-R3 rules) |
  |---|---|---|
  | easy | 0.00 | 0.997 |
  | medium | 0.973 | 0.985 |
  | hard | **0.732** | 0.125 |
  | evasive | 0.391 | 0.284 |

  Overall ROC-AUC: model **0.889**, B0 **0.994**.
- **The limitation — say it out loud:** "**B0 beats the learned model on
  average precision at every tier.** The model is decisively better only on
  `hard`, where the rules do not fire at all. We show both curves; we do not
  hide the rules baseline. And on these short single-episode splits the
  target-FPR point is **`UNRESOLVABLE (too few negatives)`** — that is printed on
  the screen, not rounded to a fake `0.000`."

### 5.2 Precision / false-positive rate

- **What I say:** "Precision is: of the attempts we flagged, how many were
  actually attacks. In steady state, at 0.1% prevalence, precision is brutal —
  which is exactly why we never auto-block."
- **Technically:** `TP / (TP + FP)`; FPR is `FP / (FP + TN)` on the negatives.
- **Why it matters:** it is the customer-harm number. A false positive is a
  legitimate shopper getting a challenge.
- **This project's result:** the cost curve's decision region is bounded at
  `FPR <= ~0.002` at pi0. At the F1 optimum, F1 = 0.638; at the *next* hull
  vertex it collapses to 0.000 — precision falls off a cliff away from FPR = 0.
- **The limitation:** at realistic steady-state prevalence, a threshold that
  catches attacks also catches a meaningful fraction of legitimate traffic —
  hence `challenge`, not `block`, and hence the seven negative controls.

### 5.3 Calibration (ECE, Brier)

- **What I say:** "Calibration asks: when the model says 0.3, does it happen
  about 30% of the time? We correct the probability for the prevalence of the
  regime we are in."
- **Technically:** Expected Calibration Error over 10 bins; Brier score.
  Corrected via the Eval Protocol §3.2 logit shift.
- **Why it matters:** the cost-derived thresholds are only meaningful if
  `score_calibrated` is a real probability.
- **This project's result:**

  | regime | ECE raw | ECE Platt | ECE Platt + prior |
  |---|---|---|---|
  | pi0 = 0.001 (steady) | 0.262 | 0.070 | **0.0007** |
  | pi1 = 0.9 (attack) | 0.209 | 0.395 | **0.281** |

- **The limitation:** at pi0 the reweighting is extreme (effective n ~ 760 of
  2125), so ECE-at-pi0 is ill-conditioned; the well-conditioned criterion is
  ECE-at-pi1, where prior correction helps (0.395 -> 0.281).

### 5.4 CUSUM behaviour

- **What I say:** "The CUSUM is tuned to raise at most one false alarm per store
  per 24 hours, using only benign traffic."
- **Technically:** ARL_0 (average run length under the null) >= 8,640 ten-second
  buckets; `cusum_h` solved from the negative controls; `tau_flag` derived from
  the cost model.
- **Result:** in the demo replay, with `p_bar_0 ~ 0.60` (weak model), CUSUM is
  conservative; **SPRT is the operative Layer-2 detector**. Both are reported.

### 5.5 SPRT / distinct-card behaviour

- **What I say:** "Per-IP, a sequential test on how often that IP's
  distinct-card count exceeds the store's 95th percentile, with a 1% false-alarm
  and 5% miss design."
- **Result:** opens 2 `drift` incidents at **TTD ~ 76-78 s event time** in the
  demo.

### 5.6 Entity resolution

- **What I say:** "Every enforcement attaches to the narrowest entity that
  covers the evidence — one IP, one IP-plus-UA-class, or one card. Never the
  store."
- **Result:** in the demo, entity type is **`ip` only**; store-wide enforcement
  is unrepresentable in the schema.

### 5.7 Challenge / allow / block outcomes

- **What I say:** "In a full attack replay: 269 `allow`, 552 `challenge`, and
  **zero** automatic `block` or `step_up`. The ceiling holds."
- **Result** (`easy`/60/pace, 821 events): decision histogram
  `{allow: 269, challenge: 552}`; control arm 29/821 (deterministic).

### 5.8 Latency — p50 / p95 / p99

- **What I say:** "`/v1/score` compute p99 is 12 milliseconds. The budget is
  100. The language model is nowhere near this path."
- **Technically:** `latency_ms` is the time inside the measured window
  (features -> rules -> model -> Layer 2 -> decision), stamped before the SSE
  publish.
- **Result:** p50 / p95 / p99 = **4 / 8 / 12 ms** sequential; 17 ms at
  10-concurrent; 59 ms burst. Fail-open rung p99 = 10 ms (it skips the model +
  Layer 2). Round-trip p50 ~55 ms (Windows->container loopback dominates).
- **What good looks like:** TRD §1 is p99 < 100 ms. Met with a wide margin.

### 5.9 Throughput / the 60x replay

- **What I say:** "The replay runs the attack at 60x virtual time. On this
  laptop it actually runs at about 59x, which is a documented reference-machine
  limit — the compute path is fine, the serial test harness is the bottleneck."
- **Technically:** `verify_60x --gate throughput` drives 20 sequential
  single-client `POST /v1/score` loops and asserts >= 400 attempts/s. On the
  reference machine it gets ~305 aps.
- **Result / honesty:** the `throughput_ok` speed sub-check is **advisory** per
  **Decision 110**. It is a serial single-client HTTP-loop artefact bounded by
  loopback round-trip, **not** a serving inefficiency — the compute p99 is 12 ms.
  **Every correctness / determinism / repeatability sub-check of the same gate
  passes and stays blocking** — `identical_event_counts = [821]`,
  `no_run_was_swallowed`, `attempt_score_row_parity`, `redis_returns_to_floor`,
  `drainer_*`, `loop_lag_under_2s`. `verify_60x.py` was **not modified** — no
  threshold was lowered.
- **Say this exactly:** "It's advisory, not passing. The number stays; its
  interpretation is what Decision 110 fixes."

### 5.10 Availability / degraded state

- **What I say:** "Three rungs: full scoring, rules-only shed when the merchant
  is flooded, fail-open when a dependency dies. Every rung writes a row; none of
  them 5xxs."
- **Result (Phase 7):** six injected faults, all fail safely — Redis kill,
  Redis restart (auto-recovers), scorer SIGTERM (drainer resumes from byte
  offset, no double-write), scorer SIGKILL mid-replay (no phantom `running`),
  SSE drop -> polling, SQLite locked 4 s (scoring decoupled).

### 5.11 D6 evaluation result

- **What I say:** "D6 is a committed artifact. Regenerate it and diff — zero
  substantive metric differences, every block reproduces bit-for-bit."
- **Result:** `diff_d6.py` -> 0 substantive diffs; all four frozen-artifact SHAs
  byte-identical to the start of Day 9. The one caveat is DEF-D9-003 (Act 12 §10).

---

# ACT 6 — The live demo

**Setup, before anyone is watching:**

```bash
docker compose down -v          # true clean slate
docker compose up --build       # wait for all 5 long-running services "healthy" (~20-90 s)
docker compose ps               # confirm, off-screen
curl -s localhost:8080/healthz  # {"status":"ok",...}
```

Two browser windows side by side, **no dev console open**:
**LEFT** = storefront `http://localhost:5173/?demo=1` ·
**RIGHT** = dashboard `http://localhost:5174/`.

**Starting state to verify on screen:** dashboard threat band reads **`o CALM`**,
`SSE: live` chip, "No incidents...", control strip `replay: idle`. Storefront
shows the Kesar & Co. product page.

**Contingency check (off-screen, costs 3 s):** if the very first checkout shows
`HTTP 401` in the `?demo=1` readout, the frontends booted before `bootstrap`
wrote the key — `docker compose up -d --force-recreate storefront dashboard`,
retry. (This is DEF-D9-011; the fix makes it not recur, but check anyway.)

---

## Step 1 — Normal checkout (the invisible protection)

**SAY:** "This is a real merchant checkout. A shopper types a card and pays."
*(click Buy now -> the form appears)* "I'll leave the default card and pay."

**DO:** LEFT -> **Buy now** -> **Pay Rs 1,200**.

**SCREEN:**
- LEFT: routes to **"Order confirmed"**. The `?demo=1` readout shows
  `/v1/score latency: ~15 ms · tier: allow`.
- RIGHT: one new ticker row — `HH:MM:SS · <pseudonym> · <truncated-IP> · <BIN> ·
  ALLOW`.

**BACKEND:** the browser computed `card_hash = SHA-256(digits)` and sent
`POST /v1/score` with `bin`, `last4`, expiry, amount — **not the PAN**. The
scorer authenticated the key -> resolved the client IP (the storefront proxy
container, a declared trusted edge) -> token bucket had a token ->
`compute_features` (one Redis Lua round trip) -> R1/R2/R3 did not fire -> the
model scored it far below threshold -> `PolicyEngine` returned `allow` -> an
`auth_attempt` + `attempt_score` row were spooled and drained -> an SSE event
published.

**WHY:** it proves the whole path is live and that **the customer feels
nothing**. That is the product thesis — protection that is invisible when
there's no attack.

**METRIC / EVIDENCE:** `200 {"decision":"allow"}`; `auth_attempt` 0->1,
`attempt_score` 0->1 with the typed `bin`; the SSE stream carried the event.
(Rehearsal #1 Pass B Step 1; Rehearsal #2 Step 1. Re-verified in local Day-9
deployment validation: `200 {"decision":"allow","latency_ms":78}` via the proxy,
`bin=411122` persisted.)

**IF ASKED:**
- *"Where's the card number?"* — "It never leaves the browser. We send a SHA-256
  hash of the digits, the 6-digit BIN, and the last four. `test_no_pan.py` and
  the trust boundary enforce that."
- *"15 ms — is that the whole round trip?"* — "That's the compute time inside
  the scorer. The round trip is ~55 ms, dominated by Windows-to-container
  loopback on this laptop."

---

## Step 2 — Launch the attack

**SAY:** "Now a recorded card-testing attack, replayed at sixty times virtual
time. Read the banner: **x60 virtual clock · windows preserved · TTD in event
time**. The clock is fast; the detection windows are real seconds of the
attack's own time; and time-to-detect is measured in *its* time, not ours."

**DO:** RIGHT -> control strip: tier **`easy`**, speed **`60`**, [x] **pace from
episode** -> **Launch**.

**SCREEN:** the strip reads `replay: running (n/821)`; the ticker starts
filling.

**BACKEND:** `POST /v1/replay/start {tier: easy, seed: 42, speed: 60, pace_from:
episode}` -> `202`, mints a fresh `run_id` (a ULID) -> the replay driver plays
821 recorded events through the **identical `score_attempt()`** the storefront
just used, with a `VirtualClock` and a seed-derived ULID generator. Same events,
order, virtual times, decisions — every run.

**WHY:** it establishes that the thing under attack is the *real* scoring path,
not a mock, and that the run is deterministic and repeatable.

**METRIC / EVIDENCE:** `state: starting -> running`; fresh `run_id`; `sent`
climbs. Speed-0 matrix in Phase 8: `easy` = exactly 821 events, both reps
identical.

**IF ASKED:**
- *"Is this real traffic?"* — "It's a *recorded* attack from the deterministic
  simulator, replayed through the live scorer. The simulator never touches a
  real card number or opens a socket — `test_simulator_safety.py` enforces that
  statically and at runtime."
- *"Why 60x?"* — "So the attack is visible in a demo. The events, order, virtual
  times and decisions are identical to a real-time run — only the sleep between
  events changes (Decision 106)."

---

## Step 3 — Threat detection

**SAY:** "Same IP, many distinct cards, fast. The rules floor notices first —
attempts per IP, distinct cards per IP, distinct cards per BIN. Then Layer 2 — a
sequential drift test on distinct cards per IP — opens an incident. Time to
detect here was about seventy-eight seconds of the attack's own time."

**DO:** wait ~60-80 s. Watch the threat band and the tiles.

**SCREEN:**
- threat band **`o CALM` -> `<> ELEVATED`** (text label + a distinct ring glyph —
  never colour alone).
- the `ATTEMPTS · 5 MIN` and `CARDS PER IP` tiles climb.
- an **incident opens** — the Incidents nav gets a badge; a monochrome
  system-state banner may appear.

**BACKEND:** `compute_features` now returns high `distinct_cards_per_ip_5m` /
`_per_bin_5m` -> R2/R3 fire -> the SPRT accumulates exceedance evidence per IP ->
crosses its bound -> `incidents.step()` opens an incident, transitions it to
`ESCALATED` -> `PolicyEngine.resolve` proposes `challenge` and, because that is
at the auto-ceiling, applies it (`confirmed_by: auto`).

**WHY:** it proves detection is **layered** (rules floor + statistical drift),
**store-relative** (the SPRT compares to *this store's* learned 95th
percentile), and **timely** (TTD in event time, not "eventually").

**METRIC / EVIDENCE:** replay reaches `finished 821/821`, `terminal: true`,
`error: null` (never a stuck `N-1/N`). `attempt_score` row count == events
scored (exact parity). **2 incidents**, `state: ESCALATED`, `detector: drift`,
`peak_tier: challenge`, `time_to_detect_s ~ 78`. Decision histogram
`{allow: 269, challenge: 552}` — **zero automatic block/step_up**.

**IF ASKED:**
- *"Why not detect it in event 1?"* — "One attempt has no aggregate shape. The
  SPRT is designed to accumulate evidence with a controlled 1% false-alarm rate
  before it fires. Seventy-eight seconds of event time is fast for that
  guarantee."
- *"What about the decline-rate feature?"* — "It reads `0.0` on this pre-auth
  path — there is no completed authorization outcome to derive it from. The
  detection you just saw does not use it. I'm telling you that so you don't
  think the screen is showing something it isn't."

---

## Step 4 — The incident (D3)

**SAY:** "The full case. A generated summary at the top — but the evidence
underneath it is authoritative." *(read the narrative aloud)* "Pseudonym `ip_2`.
Closed vocabulary. No raw identifier, no card hash anywhere on this screen."
*(point at the in-force tier)* "The system did **not** block. `challenge` is the
automatic ceiling — one extra check for the customer. `block` and `step_up` need
an operator's confirmation. The system escalates on its own only as far as an
inconvenience, never as a wall."

**DO:** RIGHT -> **Incidents** nav -> newest incident.

**SCREEN:** header `Incident ... · OPEN/ESCALATED · proposed monitor/challenge ·
in force ...`; sections: **Narrative**, **Evidence** (detection timeline +
contribution bars + entity table), **Audit trail**, collapsed **Client-asserted**
panel. Entity table: `ip_2 · ip · 198.51.100.xxx (truncated) · <count> ·
first/last seen`. In-force tier `challenge`, `confirmed_by: auto`.

**BACKEND:** `GET /v1/incidents/{id}` returns a **read model** — nothing is
recomputed; every field already exists in SQLite. The narrative was rendered
from a **template** with a closed vocabulary at incident open. Pseudonyms come
from `incidents.pseudonym(merchant_id, entity)`; keys are truncated.

**WHY:** it proves (a) enforcement is **entity-scoped** and store-wide is
unrepresentable, (b) the automatic ceiling is real, (c) there is a **full audit
trail**, and (d) **no PAN and no full card hash reach the operator** — a scan of
the entire JSON response finds neither.

**METRIC / EVIDENCE:** the read model's keys `incident · entities · timeline ·
enforcement · contributions · client_evidence`; a full-JSON scan for a 16-digit
run or a 64-hex string finds nothing (one 14-digit false positive in both
rehearsals was `signal_value 4.60517...`, a log). (Rehearsal #1 Pass B Step 4;
Rehearsal #2 Step 4 — byte-for-byte identical read model.)

**IF ASKED:**
- *"Is the narrative from the LLM?"* — "Here it's the deterministic template. If
  you set `NARRATOR_BACKEND=gemini` with a key, a Gemini call runs **out of
  band, after** the decision and the SSE publish — never on the scoring path,
  never able to influence enforcement. Any failure keeps the template. A harness
  run makes zero LLM calls."
- *"Can the operator make it worse?"* — "They can confirm `step_up` or `block`
  for **this entity's subsequent attempts only** (Decision 99). They cannot
  retroactively re-score, and there's a hard cap — `K_max` — on how many
  entities can be under enforcement before the engine goes advisory."

---

## Step 5 — The CGNAT co-tenant

**SAY:** "Now a legitimate shopper checks out **from the exact same
carrier-grade NAT IP the attacker is on** — a real situation with mobile
networks, where a whole city can share one public address. The proxy stamps that
IP; the scorer trusts it because the proxy is the declared edge."

**DO:** LEFT -> back to the checkout -> **Checkout as CGNAT co-tenant**.

**SCREEN:** LEFT routes to **"Order confirmed"**; the `?demo=1` readout shows
`tier: allow · via co-tenant IP: 198.51.100.xxx`. RIGHT: a new ticker row —
`ALLOW`, from that IP.

**BACKEND:** the button calls `GET /v1/demo/cotenant-ip`, which returns an IP
currently in the live enforcement ledger. It then re-runs the checkout with an
`x-tg-demo-xff: <that IP>` header. The **Vite proxy** — a declared trusted edge
— promotes that to `X-Forwarded-For` (the browser is not allowed to set XFF
itself). The scorer's `resolve_client_ip` honours it *because the peer is in the
trusted-edge set*. The attempt hits the **real** `(ip, ua_class)` entity and the
**real** `challenge` auto-ceiling — and a single clean attempt does not cross
R1, and the ceiling makes `block` unreachable.

**WHY:** this is the whole CGNAT thesis in one click. The attacker's reputation
lives on `(ip)`; the co-tenant is a *different entity* (different UA class /
different card / just one attempt), so nothing about the co-tenant's decision
was special-cased — same entity resolution, same thresholds — and they got
through.

**METRIC / EVIDENCE:** `GET /v1/demo/cotenant-ip -> {ip: 198.51.100.249}`;
`POST /v1/score` with that XFF -> `200 allow`; `auth_attempt.ip` = that IP (real
XFF promotion via the declared edge). A non-edge peer's XFF is **ignored** —
verified in Phase 6. (Rehearsal #1 Pass B Step 5; Rehearsal #2 Step 5.)

**IF ASKED:**
- *"So you *do* trust a client header?"* — "Only `X-Forwarded-For`, and only
  when the TCP peer is in the merchant's declared edge set
  (`TOLLGATE_TRUSTED_EDGE_HOSTS`). Anyone else's XFF is dropped. That's Threat
  Model K8 — 'validated against the merchant's declared edge.'"
- *"What if the attacker sets that header?"* — "They're not the declared edge,
  so it's ignored. The `ScoreRequest` schema has no `ip` field at all — a
  body-supplied IP is dropped by Pydantic before any code sees it."

---

## Step 6 — Scorer fault -> fail-open

**SAY:** "If the model or a dependency fails, the scorer does not return a 500
and does not block the merchant. It **fails open** — returns `allow`, marks the
attempt `degraded_reason: fail_open`, and alerts once per window."

**DO:** RIGHT -> control strip **DEMO** group -> **Kill scorer**. Then LEFT ->
run a checkout. Then RIGHT -> **Kill scorer** again to clear.

**SCREEN:** a monochrome D0 fail-open banner appears. The checkout still routes
to **"Order confirmed"**, `tier: fail_open`, latency ~5 ms. Clearing the fault
-> the next checkout is `tier: allow`, `degraded_reason: null` — recovered, no
restart.

**BACKEND:** `POST /v1/demo/fault {enabled: true}` sets an in-process flag;
`/v1/score` then `raise`s **before** `score_attempt()` — driving the **identical**
`except -> _fail_open` path a real fault (dead Redis, exploded model) would.
`_fail_open` writes an `allow` `ScoreRecord` with `degraded_reason:
fail_open:model`, publishes an SSE frame with `availability.fail_open = true`,
and returns `allow`. `AvailabilityMonitor` raises one `alert` per 60 s window
past the threshold.

**WHY:** availability and safety are balanced deliberately. A card-testing
defence that takes the merchant's checkout down when *it* has a bug is worse
than the attack. The failure is **loud** (a row, a banner, a paged alert) but
never a customer-facing error and never a silent decision change.

**METRIC / EVIDENCE:** 3x `200 allow`, `latency_ms 0-7`, `degraded_reason:
fail_open:model` on every persisted row, **never a 5xx**; fault off -> full path
restored on the next call. (Rehearsal #1 Pass B Step 7; Rehearsal #2 Step 7 —
identical.)

**IF ASKED:**
- *"Isn't fail-open a security hole?"* — "It's a *bounded* one. It only applies
  to the risk *scoring* — the merchant's own payment processor still runs its
  checks. And authentication never fails open: a cold key cache plus an
  unavailable auth DB returns 503, never `allow` (Decision 89). Failing *closed*
  here would mean a Redis blip = the merchant can't sell anything."

---

## Step 7 — Flood -> shed (show, with the caveat)

**SAY:** "A volumetric flood. The per-merchant token bucket drains and the
scorer **sheds** — rules-only, no model, `X-Tollgate-Shed`. Watch the flood's
own requests being shed in the counter."

**DO:** RIGHT -> control strip **DEMO** group -> **Flood**. Let it run ~25 s.
**Flood** again to stop.

**SCREEN:** the flood status / scorer log shows `shed_responses` climbing.

**BACKEND:** `POST /v1/demo/flood {enabled: true}` starts a real **250-way
concurrent** `POST /v1/score` load against the scorer's own port. It drains the
per-merchant lazy-refill token bucket (`rate_per_s 50`, `burst 200`) through the
genuine `AdmissionController.try_consume`. Once empty, requests take the
**rules-only shed rung**: `INCR tg:{m}:shed:{ip}` (60 s TTL), R1 **only**
evaluated against that counter (Decision 15), `X-Tollgate-Shed: 1`, a `shed=True`
row — **`compute_features`, the model, and Layer 2 never run**. It is never a
flag that sets `shed`.

**WHY:** availability protection has a *middle* rung, not just on/off. Under a
flood the system keeps a cheap deterministic floor running for everyone rather
than either collapsing or turning off protection entirely.

**METRIC / EVIDENCE:** 664 / 784 real `X-Tollgate-Shed: 1` responses across the
two rehearsals; `test_admission_shed.py` green.

**KNOWN LIMITATION — say this, don't skip it:** "On this single-worker laptop
the shed is *intermittent* — the flood sheds about a third of its own requests
but does not keep the bucket continuously empty, so a lone interactive checkout
is shed only sometimes and the banner may not latch. **I'm not going to promise
you'll see my checkout throttled.** The shed *code path* is proven; on a
multi-worker deployment this rung is crisp. This is DEF-D9-004, documented."

**IF ASKED:**
- *"Why is it marginal?"* — "The single-worker scorer completes ~79 requests/s
  total, barely above the 50/s bucket refill, so the bucket refills almost as
  fast as the flood drains it. Same reference-machine ceiling as the throughput
  gate. Raising the flood concurrency doesn't move it."

---

## Step 8 — Reset / recovery

**SAY:** "Between runs, one button. The backend owns the lifecycle — this is
transactional: cancel the run, wait for it to actually stop, clear every layer,
publish, go idle."

**DO:** RIGHT -> control strip -> **Reset**.

**SCREEN:** `replay: idle`, threat band back to `o CALM`, tiles clear, incidents
cleared.

**BACKEND:** `POST /v1/replay/reset` -> cancel -> await termination -> clear
(window store, threat rollup, Layer-2 engines, incident registry, policy engine,
decision cache, persisted incidents) -> publish -> `idle`. Returns a per-layer
`cleared` map and a `degraded` flag, so a partial failure (Redis down) is
reported honestly rather than as a bare 500. `run_id` -> `null`, which is the
frontend's single reset signal — every event-derived surface reinitialises.
**DEF-D9-008 fix:** reset now also **releases** the incidents' `enforcement_action`
rows (Rehearsal #2: 0 orphan rows, vs 3 in Rehearsal #1).

**WHY:** the demo is repeatable from clean state, with no manual backend
intervention — the "Reset" is the operator's own control, nothing else.

**METRIC / EVIDENCE:** `200 · state: idle · run_id: null · degraded: false ·
cleared = {...}`; Redis `dbsize` -> 0 (its key floor); `enforcement_action WHERE
released_at IS NULL` = 0; `GET /v1/demo/cotenant-ip` -> 404 ("nothing enforced").
(Rehearsal #2 Step 9 — DEF-D9-008 verified resolved.)

**IF ASKED:**
- *"Full restart?"* — "For a fully clean slate — a fresh run of the whole demo —
  `docker compose down -v && docker compose up --build`. Reset is enough between
  takes of the same demo."

---

## Step 9 — The metrics

**SAY:** "This renders from a **committed** evaluation artifact — zero live
computation. The header shows the seed, the config hash, and whether the
configs have changed since it was generated." *(walk the panels — use Act 5's
numbers)* "Model recall by tier: easy zero, medium 0.97, hard 0.73, evasive
0.39. The model is **weaker** than the B0 rules baseline on average precision at
**every** tier — and decisively better on `hard`, where the rules don't fire at
all. We show both. Tier E — the adaptive adversary — 0.39 model, 0.28 rules, and
its target-FPR point is **UNRESOLVABLE**, which we print on the screen. Six
features excluded by the discriminability audit; the model runs on four. The
rupee gap at steady-state prevalence is structural — zero — so the headline is
the regime-switch saving."

**DO:** RIGHT -> **Metrics** (`#/metrics`).

**BACKEND:** `D6Metrics.jsx` does a **build-time `import`** of
`eval/outputs/d6.json`. No `fetch`, no scorer call, no SSE — the route makes
**zero** network activity (a Playwright test asserts it over a 10 s dwell). The
freshness line compares the build-time `TG_CONFIG_HASH` (from bootstrap) to the
artifact's `provenance.config_hash`.

**WHY:** the metrics you present cannot drift from what was measured, cannot be
massaged live, and disclose their own staleness.

**METRIC / EVIDENCE:** every honesty requirement is on screen and was verified
in Phase 11 — B0 not omitted, no fake `0.000` (`resolvable:false` renders "not
resolvable"), rupee gap structural, every metric with its measurement
conditions, "configs unchanged since".

**IF ASKED:**
- *"Your model is worse than rules — why ship it?"* — "On `hard` traffic — cards
  spread over enough IPs and BINs that no single count crosses a rule threshold
  — B0 gets recall 0.13 and the model gets 0.73. That's the regime the model
  exists for. And it feeds the *score*, never the *decision*, so a bad model
  day can't get past the rule floors."

---

# ACT 7 — What each J6 step proves

| Step | Evaluator sees | Happening technically | Why it matters | Security property | Proof | Failure case |
|---|---|---|---|---|---|---|
| 1 normal checkout | "Order confirmed", one `ALLOW` ticker row | full `score_attempt` path, `allow`, spooled + published | protection is invisible with no attack | PAN never sent; server-observed IP | `attempt_score` row with typed BIN | — |
| 2 launch | `running (n/821)` | seeded virtual-time replay through the real scorer | the thing under attack is real and deterministic | replay is authenticated (`X-Tollgate-Key`) | fresh `run_id`; exact 821 events | replay task failure -> `failed` state, `reset`-recoverable |
| 3 detection | threat band moves, incident opens | R2/R3 fire; SPRT crosses its bound; state machine -> ESCALATED | layered, store-relative, timely (TTD in event time) | no client value reaches a feature/decision | 2 drift incidents, TTD ~ 78 s, `{allow:269, challenge:552}` | if the SPRT were a single-window threshold: flapping / false alarms |
| 4 incident (D3) | full case, pseudonyms, `challenge` auto | read model from SQLite; template narrative; auto-ceiling | entity-scoped; audit trail; no operator-visible PAN | no PAN / 64-hex hash in the response | full-JSON scan finds neither | — |
| 5 co-tenant | legit checkout from the attacker's IP, `allow` | XFF promoted by the declared-edge proxy; real `(ip,ua_class)` entity; challenge ceiling | **CGNAT**: two entities can share an IP | XFF honoured only from the declared edge | `auth_attempt.ip` = enforced IP, decision `allow` | if enforcement were store-wide or IP-wide: the co-tenant is blocked |
| 6 fault -> fail-open | banner; checkout still confirms; `fail_open` | in-scorer flag -> the real `_fail_open` path | availability >= scoring; degrade loudly | auth still never fails open (503) | 3x `allow`, `fail_open:model`, never 5xx | if it failed *closed*: a Redis blip stops all sales |
| 7 flood -> shed | `shed_responses` climbing | 250-way real load drains the token bucket -> rules-only rung | availability has a *middle* rung | one merchant's flood cannot shed another's | 664 / 784 real `X-Tollgate-Shed` | if there were no shed rung: the scorer collapses under load |
| 8 reset | idle, clean | transactional cancel->await->clear->publish | the demo is repeatable with no backend surgery | reset is authenticated; destroys live state deliberately | `cleared` map, Redis floor 0, 0 orphan enforcement | if reset weren't transactional: "idle" while the old run still scores (AUDIT-004) |
| 9 metrics | committed artifact, honest numbers | build-time import, zero live computation | metrics can't drift or be massaged | route makes zero network calls | Playwright 10 s dwell = no traffic | — |

### The three beats an evaluator will push hardest on

**Co-tenant — why two entities can share an IP without being treated as one
actor.** Enforcement attaches to the **narrowest entity that covers the
evidence** — `(ip)`, `(ip, ua_class)`, or `(card)` — never the store, and the
schema has no store-wide row. The attacker's reputation is on `(ip)` with their
UA class and their enumeration pattern. The co-tenant is a different UA class,
one clean attempt, a real card — a different entity. Nothing is special-cased;
`resolve_entity` runs the same for both. The `challenge` auto-ceiling is the
backstop: even if the co-tenant *were* swept into the same entity, the worst
automatic outcome is one extra check, never a block.

**Flood -> shed — why availability protection exists and why it degrades to
rules-only rather than collapsing.** A per-merchant token bucket (`rate_per_s
50`, `burst 200`) is the volume mitigation. When it empties, the scorer does not
queue, does not 503, does not turn protection off — it drops to a **rules-only
rung** that runs R1 against a cheap merchant-scoped counter and nothing else
(no features, no model, no Layer 2). The deterministic floor stays up for
everyone; the expensive path is what's shed. One merchant's flood cannot affect
another's admission (the bucket is per `merchant_id`).

**Scorer fault -> fail-open — why availability and safety are balanced this
way.** The scoring layer is *advisory in front of* the payment processor's own
checks. If Tollgate's model or Redis dies, failing **closed** would take the
merchant's entire checkout offline to stop a risk *score* — strictly worse than
the attack it defends against. So `/v1/score` fails **open** to `allow`, writes a
`degraded_reason` row, and pages once per window. The failure is loud and
audited; it is never a customer-facing 5xx and never a silent decision change.
Authentication is the one thing that never fails open (Decision 89) — an
unauthenticated request is a bigger hole than fail-open closes.

---

# ACT 8 — Security

Prepare for these. For each: the property, and **"if the evaluator asks X,
answer Y."**

### Trust boundaries

- **Property:** the client asserts *nothing* that reaches a feature, the model,
  the decision, merchant identity, or `attempt_uid`. The `ScoreRequest` schema
  (`packages/contracts/wire.py`, `extra="ignore"`) has **no `ip` field** — a
  body-supplied IP is dropped by Pydantic before any code runs.
- **If asked "what stops a client injecting a high feature value / a `block`
  decision?"** -> "Phase 6's S-5 probe did exactly that — `attempts_per_ip_60s=
  999999`, `score_calibrated=0.999`, `decision='block'`, a PAN, a CVV. The
  persisted row had the server's values (`attempts_per_ip_60s=1`,
  `score_calibrated=9.57e-05`, `rules_fired=[]`, a server ULID, no PAN key) and
  the response was `allow`, not `block`. S-5 was armed and not triggered."

### Client IP / X-Forwarded-For

- **Property:** `resolve_client_ip` returns the TCP peer address, **unless** the
  peer is in `TRUSTED_EDGE_HOSTS` (`{127.0.0.1, ::1, testclient}` +
  `TOLLGATE_TRUSTED_EDGE_HOSTS`), in which case it takes the first
  `X-Forwarded-For` hop. Under Compose the extra set is the two Vite proxy
  container IPs — the merchant's **declared edge** (Threat Model K8).
- **If asked "so XFF is spoofable?"** -> "Only from the declared edge. A
  non-edge peer's XFF is ignored — Phase 6 verified a request from the `redis`
  container IP had its XFF dropped. `TOLLGATE_TRUSTED_EDGE_HOSTS` *adds* to the
  loopback set; it does not widen it by default, and off-Docker the boundary is
  unchanged."

### Authentication / authorization

- **Property:** `X-Tollgate-Key` -> SHA-256 -> `merchant.api_key_hash` lookup,
  with a warm in-process `{hash -> merchant_id}` cache. A warm cache + a locked
  DB still authenticates (then can fail open, merchant-scoped). A **cold** cache
  + an unavailable DB returns **503** — `AuthBackendUnavailable`, never `allow`
  (Decision 89). `/v1/replay/{start,stop,reset}` and every `/v1/incidents`
  mutation require the key; `/v1/replay/status` is deliberately open (Decision
  107) so a refresh reconstructs even with a misconfigured key.
- **If asked "why is `/v1/replay/status` open?"** -> "It discloses strictly less
  than `/v1/stream` already does, and the frontend's mount-time recovery poll
  has to work unconditionally for a refresh to reconstruct correctly. The
  *mutating* replay routes are all authenticated."

### PAN / CVV handling

- **Property:** the PAN never leaves the browser. `S2Checkout.jsx` computes
  `card_hash = hex(SHA-256(digits))` via `crypto.subtle` and sends only `bin`
  (first 6), `last4`, expiry, amount. No PAN, no CVV, no full card hash on the
  SSE stream, in D1/D3, or in scorer logs.
- **If asked "prove the fields are wired, not decorative"** -> "AUDIT-019:
  typing `5544 3322 1100 9988` produced the exact SHA-256 in the intercepted
  `/v1/score` body, `bin=554433`, `last4=9988` — and the PAN itself was not in
  the request."

### Outcome HMAC / nonce / staleness (replay protection)

- **Property:** `POST /v1/outcome` verifies `hmac_sha256(secret,
  "{merchant_id}\n{ts_ms}\n{nonce}\n{sha256(canonical_body)}")`, a **5-minute
  staleness window**, and a **single-use nonce** (`outcome_nonce` PK -> `409` on
  replay). The secret is `TOLLGATE_OUTCOME_SECRET`, bound to the merchant via
  `outcome_hmac_key_hash` — no secret at rest. Unsigned / tampered / stale ->
  `401`; unknown `event_id` -> `404`; unset secret -> `503`.
- **If asked "what stops a replayed webhook?"** -> "The nonce is single-use — a
  second delivery of the same signed body is a `409`. And a body older than five
  minutes is `401` regardless of signature."

### Demo controls

- **Property:** every `/v1/demo/*` route calls `_require_demo()` first, which
  raises **404** (not 403 — the route "does not exist") unless
  `TOLLGATE_DEMO_CONTROLS=1`. The Vite proxy's `x-tg-demo-xff -> X-Forwarded-For`
  promotion is likewise gated. Every control drives a **real** code path — no
  faked decision, tier, or availability state (stop condition S-3, checked, not
  triggered; a source test asserts the flood never sets `shed` directly).
- **If asked "could this ship to production by accident?"** -> "With the env var
  unset the routes 404 and the UI group doesn't render. Phase 6 verified it on a
  scorer with no env set. Confirmed again in Day-9 local deployment validation:
  `/v1/demo/cotenant-ip` returns 401 without a key and 404 when nothing is
  enforced — i.e. the route exists only because the stack sets the flag."

### Narrator isolation

- **Property:** the only admission point is `build_bundle()` — a frozen
  dataclass with a closed vocabulary that raises in `__post_init__`; it takes no
  `user_agent`, no raw identifier, no free text. `assemble_prompt()` runs a
  `CHARSET_RE` gate on the input side. Gemini runs **out of band** after the SSE
  publish (Decision 98). A hostile UA is kept as evidence in
  `auth_attempt.client_evidence` but has **no path to the prompt**.
- **If asked "prompt injection?"** -> "There is no attacker-controlled free text
  in the prompt. The bundle is built from a closed vocabulary and charset-gated.
  And even a successful injection can't do anything — the narrator is
  post-decision, post-publish, and cannot touch enforcement."

### Model / scoring separation

- **Property:** "score yes, decide no." The model produces `score_raw` /
  `score_calibrated`. The **decision** is `max(policy tier, rule floor)` clamped
  by `apply_auto_ceiling` to `challenge`. `allow_auto_block = False`.
- **If asked "what if the model is compromised / adversarial?"** -> "It can move
  the score, which moves the *proposed* tier up to `challenge`. It cannot get
  past the rule floors (they only raise the tier), cannot exceed the challenge
  ceiling, and cannot cause a `block` — that needs an operator confirm."

### Fail-open behaviour

- Covered in Act 6 Step 6 and Act 7. **If asked "isn't fail-open a
  vulnerability?"** -> "It's bounded: it only affects the risk score, the payment
  processor's checks still run, every fail-open writes a row and pages once per
  window, and auth never fails open. Failing closed here is a self-inflicted
  outage."

---

# ACT 9 — Reliability

Phase 7 injected six infrastructure faults against the running Compose stack.
Every one answers: *fails safely · UI tells the truth · recovers · data
preserved · demo continues.*

| Fault | What the user sees | What the backend does |
|---|---|---|
| **Redis killed** mid-scoring | checkout still confirms; D0 fail-open banner; `SSE` frames with `fail_open:true` | every `/v1/score` -> `200 allow` `fail_open:window_store`, **never 5xx**; `/healthz` stays responsive (it does no work, so a slow answer would mean a blocked event loop — and it didn't) |
| **Redis restarted** | banner clears on the next healthy attempt | scorer **auto-recovers, no restart** — `degraded_reason: null`, windows counting again |
| **Scorer restarted (SIGTERM)** | ~8 s blip | drainer resumes from its **persisted byte offset** — no re-drain, no double-write; `attempt_score` count unchanged; replay not stuck |
| **Scorer SIGKILL mid-replay** | replay shows `idle` / `terminal`, not a phantom `running` | scored events survived (spool fsync'd before the response); a fresh Launch works with **no manual intervention** |
| **SSE disconnects** | chip -> `polling`; ticker keeps updating | the hook falls back to 5 s polling of `/v1/stream/recent?after=<cursor>` — strictly-after, in-order; `: ping` flushes headers on re-subscribe |
| **SQLite locked** (`BEGIN EXCLUSIVE` 4 s) | nothing — no visible effect | reads use the WAL snapshot; the score path writes the **spool**, not SQLite; `drainer_failures: 0` — scoring is decoupled from DB contention |
| **Redis unavailable at startup** | — | explicit `ERROR ... falling back to InMemoryWindowStore`; a real in-memory window path (not fail-open); restore -> `RedisWindowStore` |

**Also:** replay is reset transactionally (Act 6 Step 8); a browser refresh
mid-attack reconstructs true state via the concurrent SSE + back-fill merge; a
duplicate `event_id` is idempotent (one `attempt_uid`, one row) even under 10x
concurrency; no swallowed background-task exceptions (AUDIT-007); no CPU loop
(`loop_lag_max_s = 0.0`).

**If asked "what's the worst failure mode?"** -> "A wedged event loop —
AUDIT-006's original bug. That's why there's a permanent loop-lag monitor that
logs any >= 2 s synchronous block, a `/healthz` that deliberately does no work
so a slow answer *is* the signal, and the `verify_60x` gates that inject a
wall-clock score at the exact point where replay time crosses serving time. All
green on a quiet machine."

---

# ACT 10 — Performance

| Metric | Value | Target | Verdict |
|---|---|---|---|
| `/v1/score` compute **p50 / p95 / p99** (sequential) | 4 / 8 / **12 ms** | p99 < 100 ms (TRD §1) | **met, wide margin** |
| p99 at 10 concurrent / burst | 17 / 59 ms | < 100 ms | met |
| fail-open rung compute p99 | 10 ms (skips model + Layer 2) | — | — |
| round-trip p50 | ~55 ms | — | Windows->container loopback, not compute |
| **actual 60x replay factor** | **~ 59x** | 60x nominal | marginal, documented (prior audit: 58.5x) |
| throughput (serial single client) | ~305 aps | >= 400 aps (`verify_60x`) | **advisory** — Decision 110 |
| throughput (10 concurrent) | ~400 req/s aggregate, all `200` | — | healthy |
| memory over 20-run + 3-run soaks | RSS growth **-0.4 / -2.9 MB** | no leak | pass (negative growth) |
| CPU / event loop | `loop_lag_max_s = 0.0` | no >= 2 s block | pass |
| **LLM on the scoring path** | `narrator_call = 0`; out of band (Decision 98) | **never** | pass — LLM off the path |

### Why the LLM is not on the scoring path

`_resolve_layer2` carries an explicit contract: **that block contains no
`await`**. The 100-concurrent-vs-sequential CUSUM guarantee
(`test_concurrent_cusum.py`) depends on the whole Layer-2 fold running to
completion under the single-threaded event loop before another coroutine's fold
starts. A network call cannot live there. So the template narrative is rendered
synchronously (deterministic, I/O-free), and the Gemini call — if configured at
all — is `asyncio.create_task`'d **after** the terminal `event_bus.publish`,
outside the atomic block and outside the latency window. The p99 you quote is
therefore a real property, not a "with the LLM disabled" caveat.

### The advisory throughput number — how to say it

> "`verify_60x --gate throughput` asserts >= 400 attempts per second over a
> serial single-client HTTP loop. On this Windows + Docker Desktop laptop it
> gets about 305. That's **advisory** per Decision 110 — it's the loopback
> round-trip and Python loop overhead, not request latency: the compute p99 is
> 12 milliseconds. **Every correctness, determinism and repeatability sub-check
> of that same gate passes and stays blocking** — identical event counts, no
> run swallowed, row parity, Redis returns to its key floor, drainer healthy.
> We did **not** lower the threshold — the number stands, its interpretation is
> what the decision fixes. On a multi-worker deployment behind a real load
> balancer this isn't a question."

**Do not call the throughput gate "passing." It is advisory.**

---

# ACT 11 — D6 / evaluation and reproducibility

### What D6 is

D6 is the **committed evaluation artifact** — `eval/outputs/d6.json` — rendered
by the dashboard's Metrics page with a **build-time `import`** and zero live
computation. It is the output of an entirely **offline** harness (`eval/`) that
is independent of the live scoring path.

### The D0 -> D1 -> D3 -> D6 ladder (why it's built this way)

- **D0 — the ruler.** Before any model existed, the harness was validated
  against **four analytically-known sanity scorers**: `perfect`, `random`,
  `inverted`, `always_positive`. If the harness can't score a perfect scorer at
  recall 1.0 and a random one at chance, the harness is broken — and you'd never
  know if you'd built the model first.
- **D1 — the model.** `l1-lgbm-v1` + B0 (the live rules), on the **same**
  `temporal_test` split as the sanity scorers, reported side by side. "If the
  model is weaker than B0, say so in exactly that form" (Eval Protocol §8) — and
  it is, and we do.
- **D3 — the discriminability audit.** The 24-feature univariate-AUC table;
  6 excluded, 14 un-fed -> 4 live.
- **D6 — the committed artifact.** Blocks 1-6 + `tier_e`, every figure with its
  measurement conditions, `resolvable:false` rendered as "not resolvable" and
  never a fake `0.000`.

### Why the evaluation corpus matters

The corpus (`data/corpus/tollgate.db`, gitignored, 18 MB) is the exact logged
`attempt_score.feature_snapshot` vectors from replaying `build_runs(42)` — 12
tier blocks + 7 negative-control scenarios — through the **identical**
`score_attempt` core. The model trains on the same feature vectors the serving
path produces. There is no train/serve skew because there is one feature
computation.

### How reproducibility is protected

- Everything seeded (`seed=42`), `deterministic=True`, `num_threads=1`.
- `scripts/diff_d6.py` is a leaf-wise structural diff with float tolerance and
  `--ignore` by prefix. The Day-9 gate: regenerate `d6.json` twice, diff both
  against the committed file with the plan's ignore set -> **run A == run B**,
  and vs the committed file -> **exactly 2 changed leaves, both provenance
  metadata**; `--ignore provenance` -> **0 substantive differences**.
- **Stop condition S-6:** if any frozen artifact SHA changes without a reviewed
  regeneration, the release is blocked. All four (`d6.json 29edcb22...`,
  `audit.json ce75cb7f...`, `l1-lgbm-v1.json 7cb7fa8a...`, `platt-v1.json
  22dc48f0...`) are **byte-identical** to the start of Day 9.

### Why byte-identical artifacts matter

Because "the model scores 0.73 on hard" is only a claim you can stand behind if
anyone can regenerate the artifact and get the same number. The committed JSON
plus the diff tool plus the frozen SHAs turn the metrics from a screenshot into
something checkable.

### DEF-D9-003 — accurately, neither worse nor better than the evidence

`test_d6_provenance::test_corpus_identity` asserts `sha256(corpus) ==
d6.json.provenance.corpus_db_sha256`. During Day-9 Phase 2, an early bootstrap
iteration ran `learn_store_baseline` + `tune_cusum` against the bind-mounted
reference corpus *once*, before the corpus-working-copy guard existed. That
stamped a wall-clock `store_baseline.updated_at` on 8 rows and appended 20
`policy_config` rows (since deleted). The byte hash drifted.

**What that does and does not mean:**
- **Does not** change any metric. Proven, not asserted: `eval.harness`
  regenerated twice (deterministic), `diff_d6.py` -> 0 substantive differences;
  `store_baseline.updated_at` is metadata read by no detector or metric; the
  removed policy rows were never referenced (`d6.json` pins `policy_version: 1`).
- **Does not** trigger S-6 — every *frozen* artifact SHA is unchanged.
- **Does** leave `test_corpus_identity` permanently RED. It is **not weakened
  and not deleted** (Plan §8). The original SHA was itself a snapshot of a
  non-byte-deterministic build (`learn_store_baseline` stamps wall-clock), so a
  documented rebuild breaks the exact-hash check anyway. Recurrence is prevented
  (`ensure_corpus_working_copy()`). Rework post-Day-9: hash only the
  eval-relevant tables.

**Say it as:** "One test is red — a byte-hash check on a gitignored corpus file
that got a wall-clock timestamp written into it during Day 9. Zero metric
impact, and we proved that by regenerating and diffing rather than just claiming
it. The test stays red and documented rather than being quietly loosened."

---

# ACT 12 — Known limitations

The honest, credible answer to *"what are the limitations of your project?"*.
Group them — it shows you know which kind each one is.

### Architectural (design choices with consequences)

1. **Single Uvicorn worker.** The token bucket, availability monitor, decision
   cache, window-store fallback, replay driver, incident registry and policy
   engine are all in-process (Decision 71/87). This keeps the one-Redis-round-trip
   invariant and the 12 ms p99, at the cost of horizontal scale-out. Production
   scale needs shared state — see `DEPLOYMENT-GUIDE.md` §9.
2. **SQLite + spool + drainer** is single-writer. One node, one demo. A
   multi-instance deployment needs a real database.
3. **The learned model is weaker than the B0 rules** on average precision at all
   four tiers; decisively better only on `hard`. This is by design (score yes,
   decide no; 6 features excluded as simulator artifacts -> 4 live) and it is on
   screen, but it means the model is currently earning its place on one regime,
   not all of them.
4. **`/v1/stream` is unauthenticated** (Decision 94). Loopback/bridge-bound for
   the demo; it publishes `rules_fired` / `feature_snapshot`.
5. **Outcome-derived and BIN-metadata features read `0.0`.** No completed
   authorization outcome on the pre-auth path; the BIN-metadata join hasn't
   landed. `nri_traffic` is marked inert; a tripwire test fails the moment that
   changes.
6. **Confirmation is forward-only** (Decision 99) — confirming `step_up`/`block`
   affects subsequent attempts from that entity only.

### Demo / environment (true of this laptop, not the design)

7. **`verify_60x --gate throughput` `throughput_ok`** is advisory on the
   reference machine (~305 aps vs >= 400) — a serial HTTP-loop artefact, not a
   serving inefficiency (Decision 110). Correctness sub-checks pass and stay
   blocking.
8. **60x replay runs at ~ 59x** on this machine.
9. **Flood -> shed is intermittent** on the single-worker laptop scorer
   (DEF-D9-004) — the shed *rung* is proven; the interactive-checkout shed and
   the banner latch are marginal. Crisp on multi-worker.
10. **`test_corpus_identity` is permanently RED** (DEF-D9-003) — a byte-hash on
    a non-deterministically-built gitignored corpus; zero metric impact, proven.

### Polish (P3, cosmetic or off-path)

11. **Unknown replay `tier`** -> recoverable `failed` state, not a `422`
    (DEF-D9-005); off the demo path.
12. **`stop` lags at `speed=1`** (DEF-D9-007) — not the demo speed; `reset` is
    the fast path.
13. **`--tg-primary` small text = 4.06:1 contrast** (DEF-D9-009) — below WCAG AA
    4.5:1 on 3 nav labels + one button; legible.

### The one-line version if you only get one sentence

> "The big ones are architectural: it's a single-worker design that would need
> shared state to scale out, the learned model currently only beats the rules
> baseline on the hardest tier, and `/v1/stream` auth is deferred. Everything
> else is either a documented reference-machine limit — the throughput gate, the
> 59x replay, the intermittent flood shed — or off-path polish. None of it is
> hidden; the metrics screen and the audit both say all of it plainly."

---

# ACT 13 — Closing statement

> "So — what did we build. Tollgate is a pre-authorization card-testing defence:
> it scores every checkout attempt before the bank call, in about twelve
> milliseconds, and it decides — allow, one friction step, or, only with a
> human, block.
>
> What did we prove. A layered detector — a deterministic rules floor that
> cannot be trained away, a store-relative statistical drift layer tuned only on
> benign traffic, and a calibrated model that adds resolution where the rules
> are blunt — opening real incidents on a real attack replay in about seventy-
> eight seconds of the attack's own time, and never escalating past `challenge`
> on its own. A legitimate shopper checking out from the attacker's own CGNAT IP
> gets through untouched, because enforcement is scoped to the narrowest entity
> and store-wide enforcement is unrepresentable. And when the scorer's own
> dependencies fail, it fails open and loud rather than taking the merchant's
> checkout down.
>
> What makes it technically strong. Determinism and reproducibility as
> first-class properties — the attack replay is byte-for-byte repeatable, the
> evaluation artifact is committed and diff-checked, and every metric is on
> screen with its measurement conditions, including the ones that don't flatter
> us: the rules baseline beats the model on average precision at every tier, and
> the adaptive adversary's FPR point is literally unresolvable.
>
> What was tested. Eleven QA phases and two full clean-state rehearsals — 643
> backend tests, 205 frontend, 68 browser, the stability and time-crossing
> gates, six injected infrastructure faults, and a security probe that tried to
> inject a decision and a card number and reached nothing. Zero P0, zero
> unresolved P1. The verdict is DEMO READY.
>
> What remains to improve. Scale-out — today it's a single worker with
> in-process state. The model — it earns its place on the hardest tier; it
> should earn it on all of them, which mostly means real features instead of the
> ones we excluded as simulator artifacts. `/v1/stream` authentication. And the
> BIN-metadata and outcome-derived features that are wired but not yet fed.
>
> Everything I just claimed has a row, a test, or a rehearsal transcript behind
> it. Happy to go to any of them."

---

# LIKELY EVALUATOR QUESTIONS

Answer from the **implementation first**. Where the implementation doesn't
support a strong answer, say so — don't invent.

### Detection design

**Q. Why not just use a machine-learning model?**
Because a model is the wrong thing to bet a *decision* on here. Three reasons in
the code: (1) the rule floors (R1-R3) are a guarantee a model can't provide — if
R2 fires, the tier is at least `challenge` no matter what the model says;
(2) the model is currently weaker than those rules on average precision at every
tier (it's stronger only on `hard`); (3) "score yes, decide no" means a bad
model day, or an adversarial model, can only move the *proposed* tier up to the
`challenge` ceiling — it can't cause a block and can't get under the floor. The
model adds resolution; the policy makes the call.

**Q. Why CUSUM?**
Card-testing shows up as the store's overall flag rate rising faster than
normal. CUSUM is the classical sequential change-point detector for exactly
that: it accumulates `(observed - expected)` per time bucket and alarms when the
cumulative sum crosses a threshold `h`. We tune `h` from the seven
negative-control runs only, to an average-run-length-under-null of >= 8,640
buckets — at most one false alarm per store per 24 hours. `tau_flag` (what
counts as "flagged") is derived from the cost model, not picked. Empty buckets
decay the statistic by exactly `(lambda_1 - lambda_0)` so quiet periods heal it.

**Q. Why SPRT?**
Per-IP, we want to say "this IP is enumerating cards" or "this IP is normal"
with *controlled* error, using as few observations as possible. Wald's SPRT does
that: it accumulates a log-likelihood ratio and stops when it crosses one of two
bounds set by the target type-I (1%) and type-II (5%) rates. We run it on how
often an IP's 30-minute distinct-card count exceeds the store's learned 95th
percentile. It's the operative Layer-2 detector in the demo (TTD ~ 78 s)
because, with the weak 4-feature model, the store-level flag rate `p_bar_0` is
high enough (~0.60) that CUSUM stays conservative.

**Q. Why distinct-card counting?**
It's the definitional shape of card testing — one source, many cards. A real
shopper uses one or two cards ever. `distinct_cards_per_ip_5m`,
`distinct_cards_per_bin_5m`, `distinct_cards_per_ip_30m` encode precisely that,
and R2, R3 and the SPRT are all built on them. Raw volume alone can't
distinguish a tester from a flash sale; enumeration can.

**Q. Why entity resolution?**
So enforcement attaches to the smallest thing that actually did something wrong.
`resolve_entity` picks `card`, `(ip, ua_class)`, or `ip` — the narrowest key
covering the evidence — and `asn` and store-wide are never options (the schema
has no store-wide enforcement row). This is what makes the CGNAT co-tenant work:
the attacker's reputation is on their `(ip)` with their UA and their pattern;
the co-tenant is a different entity.

**Q. Why challenge instead of block?**
Because a false positive on a block is a paying customer turned away, and at
realistic prevalence (~0.1%) precision is genuinely poor — the cost curve shows
F1 collapsing from 0.64 at the optimum to 0.00 at the next hull vertex. So the
automatic ceiling is `challenge` (`apply_auto_ceiling`, `allow_auto_block =
False`). `block` and `step_up` exist but are *proposed* rows that only an
operator's `POST /v1/incidents/{id}/confirm` applies.

**Q. How do you avoid false positives?**
Layered: the rules only *raise* the tier, so a mis-calibrated model can't create
one; the CUSUM threshold and the store baseline are tuned on **only** the seven
benign negative-control scenarios (flash sale, corporate NAT, CGNAT, retry
storm, subscription batch, NRI traffic, shared-IP-legit); hysteresis (`theta_T`
vs `theta_T - 0.08`) stops flapping; corroboration holds rules-only decisions to
a higher bar; and the ceiling means the *worst* automatic false positive is one
extra checkout step, not a block.

**Q. How do you handle CGNAT?**
Entity resolution + the challenge ceiling. Enforcement is on `(ip)` or
`(ip, ua_class)` or `(card)`, never the whole IP's traffic indiscriminately —
a co-tenant with a different UA class, a different card, or just one clean
attempt is a different entity. And even worst-case, the ceiling caps automatic
action at `challenge`. Shown live in demo Step 5.

**Q. How do you trust client IPs?**
We don't, by default — `resolve_client_ip` returns the TCP peer address. We take
`X-Forwarded-For` **only** when the peer is in the merchant's declared edge set
(`TOLLGATE_TRUSTED_EDGE_HOSTS` — under Compose, the two Vite proxy containers).
A non-edge peer's XFF is ignored (Phase 6 verified). The request body can't
carry an IP at all — the schema has no such field.

### Failure / availability

**Q. What happens if Redis fails?**
On startup: the scorer logs a fallback and runs on `InMemoryWindowStore` — same
protocol, single-process, not restart-durable. Mid-request: the Redis client has
a 150 ms socket timeout, so a dead socket raises promptly and `/v1/score`
**fails open** to `allow` with `degraded_reason: fail_open:window_store`. When
Redis comes back the scorer auto-recovers with no restart. All verified in Phase
7.

**Q. What happens if the scorer fails?**
`/v1/score` never surfaces the failure as a 5xx — any exception from
`score_attempt()` is caught and the response is `allow` with a `fail_open`
`degraded_reason` row and one paged `alert` per window. On a full process
restart, the drainer resumes from its persisted byte offset (no re-drain, no
double-write) and a killed replay shows `idle`/`terminal`, never a phantom
`running`.

**Q. Why fail-open?**
Because this layer is advisory in front of the payment processor's own fraud
checks. Failing *closed* would take the merchant's entire checkout offline to
protect a risk *score* — strictly worse than the card-testing it defends
against. The failure is loud (a row, a banner, a page) but never customer-facing
and never a silent decision change. The one exception: **authentication never
fails open** (Decision 89) — a cold key cache + an unavailable auth DB is a
`503`, not an `allow`.

**Q. Why is the LLM / narrator not in the scoring path?**
The Layer-2 fold is guaranteed to run to completion under the single-threaded
event loop with no `await` in it — that's what makes 100 concurrent scores
behave like 100 sequential ones (`test_concurrent_cusum.py`). A network call
can't live there. The template narrative is rendered synchronously; the Gemini
call, if configured, is scheduled **after** the terminal SSE publish, outside
the latency window. It can fail in any way and the operator sees the template.
It cannot influence a decision, a tier, or enforcement.

### Data protection

**Q. How do you prevent PAN / CVV leakage?**
The PAN never leaves the browser — `S2Checkout.jsx` hashes it with
`crypto.subtle.digest("SHA-256", ...)` and sends only `bin` (first 6), `last4`,
expiry, amount. No PAN, no CVV, no full card hash on the SSE stream, in D1/D3,
or in scorer logs. Phase 6's hostile probe put a PAN and a CVV in the body; the
persisted row had neither key. AUDIT-019 confirmed the hash sent is the exact
SHA-256 of the typed digits and the digits themselves aren't in the request.

**Q. How do you prevent replay attacks (on the outcome webhook)?**
`POST /v1/outcome` requires an HMAC over `{merchant_id}\n{ts_ms}\n{nonce}\n
{sha256(body)}`, enforces a 5-minute staleness window, and burns the nonce
(`outcome_nonce` PK -> `409` on any re-delivery). Unsigned / tampered / stale ->
`401`.

**Q. How is idempotency implemented?**
The window-store Lua script does `SET NX` on `tg:{m}:idem:{ns}{digest}` where
`digest = sha256(merchant | event_id | payload_digest)`. The SET-NX winner
scores normally and its `(attempt_uid, decision)` is cached in-process; a
concurrent or retried identical request finds the key, gets the winner's
decision replayed, and **skips the spool append and the SSE publish** — so no
duplicate `auth_attempt`/`attempt_score` row and no duplicate event. Verified
under 10x concurrency: one `attempt_uid`, one row. A same-`event_id`-different-
payload request gets a new `attempt_uid` by design (Threat Model §3).

**Q. How do you guarantee replay repeatability?**
The replay driver uses a `VirtualClock` and a **seed-derived** `UlidGenerator`,
so even `attempt_uid` minting is reproducible — not just decisions. Idempotency
keys are namespaced per run (`tg:{m}:idem:r{run_id}:{digest}`) and `attempt_uid`
is run-scoped, so a repeat run of the same tier isn't silently swallowed by
Redis or SQLite (Decision 103). Phase 8: 19 launches, 19 distinct `run_id`s;
the speed-0 matrix produced exactly 821 / 701 / 508 / 390 events for
easy/medium/hard/evasive, identical across both reps.

**Q. How do you know the evaluation results are reproducible?**
`eval.harness` is seeded, `deterministic=True`, `num_threads=1`. The Day-9 gate
regenerated `d6.json` twice and ran `scripts/diff_d6.py` (a leaf-wise structural
diff with float tolerance): run A == run B, and vs the committed artifact only
two provenance-metadata leaves moved — `--ignore provenance` -> 0 substantive
differences. All four frozen artifact SHAs are byte-identical to the start of
Day 9 (stop condition S-6, checked, not triggered).

### Metrics literacy

**Q. What does p99 latency mean here?**
The 99th percentile of `latency_ms` — the time inside the scorer's measured
window (features -> rules -> model -> Layer 2 -> decision), stamped before the
SSE publish. p99 = 12 ms sequential. The TRD budget is p99 < 100 ms. The
round-trip a client sees is ~55 ms, dominated by Windows->container loopback,
not by the compute.

**Q. Why is 60x important?**
So a multi-hour recorded attack is watchable in a demo. It's a *pacing* control
only — `pace_from: "episode"` scores the pre-attack hours at full tilt and only
slows the ~20 s around the attack. Same events, same order, same virtual times,
same decisions (Decision 106). Time-to-detect is reported in **event time**, so
60x doesn't flatter it. On this machine it actually runs at ~59x, documented.

**Q. What's the difference between detection and enforcement?**
Detection = the layers that produce a signal and open an incident (rules, CUSUM,
SPRT, the state machine). Enforcement = what the `PolicyEngine` *does* about it —
resolving an entity, choosing a tier off the cost-derived ladder, applying it
(capped at `challenge`) or proposing it (`step_up`/`block`, needs a human),
writing an `enforcement_action` row with a TTL. Detection can be certain and
enforcement can still be `challenge` — that's the ceiling, and it's deliberate.

**Q. What is D0 / D1 / D3 / D6?**
Stages of the evaluation build. **D0**: four analytically-known sanity scorers
that validate the *harness* before any model exists to flatter it. **D1**: the
real model + the B0 rules baseline on the same split, side by side. **D3**: the
discriminability audit (which features are too-good-to-be-true on synthetic data
and get excluded from the model). **D6**: the committed artifact the dashboard
renders — blocks 1-6 + `tier_e`, every number with its measurement conditions.

**Q. Why does the system have degraded availability modes?**
Because a card-testing defence that fails hard is a self-inflicted outage. Three
rungs: **full** (token available), **rules-only / shed** (bucket empty under a
flood — keep the cheap deterministic floor up for everyone, shed the expensive
path), **fail-open** (a dependency raised — return `allow`, write a row, page
once per window). Every rung is loud and audited; none returns a 5xx.

### Production / scale

**Q. What would you change for production scale?**
Externalize the in-process state so the scorer can run more than one instance:
the token bucket and availability monitor -> Redis or a sidecar; the
stored-decision cache -> already backed by the Redis idempotency key, just needs
the cross-process read path; the replay driver / incident registry / policy
engine -> a shared store. Move `tollgate.db` off SQLite to a managed database.
Put an auth check on `/v1/stream`. Land the BIN-metadata join and the
outcome-derived features. Retrain the model on features that aren't simulator
artifacts so it beats B0 on more than `hard`.

**Q. Why AWS?**
It's what the task targets, and the app's shape — a small set of containers, a
private network between them, one shared writable volume, SSE, and a
*single-instance* scorer — maps cleanly onto a single EC2 host running the exact
`docker compose` stack, with TLS terminated in front. See `DEPLOYMENT-GUIDE.md`
for why that beats ECS Fargate *for this architecture* (the single-writer SQLite
volume, the one-shot init-container ordering, the repo-bind-mount model, and a
scorer that can't scale out all point away from Fargate's strengths).

**Q. How would you scale the scorer?**
You can't, as built — one worker, in-process state (Decision 71/87). To scale
horizontally you'd move that state to a shared store (above) and put the
instances behind a load balancer with sticky sessions for SSE. The window store
is already shared (Redis); it's the *policy/admission/replay* state that's local.

**Q. How would you make Redis highly available?**
ElastiCache for Redis with a replication group (primary + replica,
Multi-AZ, automatic failover) instead of the single `redis:7-alpine` container.
The app already tolerates a Redis blip — it fails open mid-request and
auto-recovers — so a failover is a few seconds of `fail_open` rows, not an
outage. Nothing in the code needs to change; `TOLLGATE_REDIS_URL` points at the
cluster endpoint.

**Q. How would you handle multiple application instances?**
Today: you don't — the scorer is single-instance by design and the frontends are
dev servers. For real multi-instance you'd (1) externalize the scorer's
in-process state, (2) build the frontends to static bundles served by a CDN
instead of running Vite dev servers, (3) put everything behind an ALB with a
long idle timeout for SSE and sticky routing.

**Q. How would you handle secrets?**
Today the bootstrap writes `deploy/compose.env` (gitignored) with the merchant
API key, `TOLLGATE_OUTCOME_SECRET`, and `TG_CONFIG_HASH`, and the containers
source it at start. On AWS: AWS Secrets Manager (or SSM Parameter Store
SecureString) for `TOLLGATE_OUTCOME_SECRET`, `GEMINI_API_KEY`, and the merchant
key, injected as environment at container start; the bootstrap either reads from
Secrets Manager or its output is written there. Never in Git, a Dockerfile, the
frontend bundle, or the README — `.gitignore` already excludes `.env*` and
`deploy/compose.env`. See `DEPLOYMENT-GUIDE.md` §13.

**Q. How would you monitor this in production?**
The signals already exist: `/healthz` returns drainer liveness + connect count +
row count + consecutive failures; the loop-lag monitor logs any >= 2 s
synchronous block; every degradation writes a `degraded_reason` row and, past
budget, a paged `alert` on the SSE stream. In production: scrape `/healthz` on a
target group health check, ship the structured `tollgate.scorer` logs to
CloudWatch, alarm on `fail_open` / `shed` row rate, `drainer_failures > 0`,
`loop_lag` warnings, and the 60x/crossing gates run in CI on every change.

### Curveballs

**Q. Your model loses to the rules — is the ML a gimmick?**
No — it's the honest result of refusing to score on features the *simulator*
made separable. On `hard` traffic, where the rules get recall 0.13, the model
gets 0.73. That's a real regime it covers. The path to it beating B0 everywhere
is real features (BIN metadata, outcome-derived signals) instead of the six we
excluded as artifacts — that's stated as future work, not hidden.

**Q. The demo is a replay, not live traffic — isn't that cheating?**
The *attack* is recorded (from the deterministic simulator, which never touches
a real card or opens a socket). It's replayed through the **live** scorer — the
identical `score_attempt()` the storefront calls, real Redis, real SQLite, real
SSE, real detection, real enforcement. Nothing is stubbed. The replay being
deterministic is a feature: you can re-run the demo and get the same incidents,
the same TTD, the same decision histogram.

**Q. You have a failing test and an advisory gate — is it actually ready?**
The failing test is a byte-hash on a gitignored corpus file that got a
wall-clock timestamp written into it; zero metric impact, proven by
regeneration, and left red-and-documented rather than loosened. The advisory
gate is a serial-HTTP-loop throughput number on a laptop — its correctness,
determinism and repeatability sub-checks all pass and stay blocking; the compute
p99 is 12 ms. Both are called out in the audit and this script. Zero P0, zero
unresolved P1, two clean-state rehearsals with identical results. The verdict is
DEMO READY with those two exceptions named.
