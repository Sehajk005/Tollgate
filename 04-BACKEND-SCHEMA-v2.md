# Tollgate — Backend Schema

**Version:** v2.0 — 22 August 2026 (supersedes v1.0)
**Companions:** TRD v2 · Threat Model v2 · Eval Protocol v2

---

## 0. What changed and why

| Change | Fixes |
|---|---|
| `attempt_uid` (server-minted ULID) replaces `event_id` as primary key everywhere | S2 — caller-supplied, load-bearing id |
| `ingest_time` is the only timestamp anything windows on | F6 — event time vs processing time was unresolved |
| Every Redis key is merchant-scoped | F16 — `tg:z:ip:…` collided across merchants while `tg:cusum:{merchant}` didn't |
| `auth_outcome` carries signature metadata; nonce table added | S3/P5 — forged outcomes poison features and labels |
| `attempt_score` gains `control_arm`, `prior_used`, `shed`, `detector` | F13 selective labelling, F12 prior shift, admission control |
| `incident` gains `cards_exposed_before_alert`, `detector`, `pinned_policy_version` | F20 wrong headline metric; config change landing mid-incident |
| `enforcement_action` gains `requires_confirmation` / `confirmed_by` | S3/P1 — auto-ceiling at `challenge` |
| Alembic replaced by one `schema.sql` | 10-day budget; migrations buy nothing here |
| `email_hash`, `phone_hash`, `checkout_path_depth`, `time_on_site_ms`, `is_guest` demoted to an evidence blob | Threat Model TB-1 — C-class fields must not be mistakable for features |
| **v2.1** — Buffered writer replaced by **spool-always** | An in-memory queue flushed on failure could not satisfy the SIGKILL acceptance test; see §1 |

**Unchanged and still correct from v1:** attempts and scores in separate tables (a fact vs an opinion); labels physically isolated; config versioned rather than mutated; enforcement keyed on an entity so a store-wide block is structurally unreachable; Redis holding nothing that cannot be rebuilt from SQLite.

---

## 1. Storage tiers

```
TIER 1 — Redis (derived, ephemeral)
  Sliding windows · CUSUM buckets · enforcement · idempotency · live counters
  ── Rebuildable by replaying Tier 2. Never source of truth.
TIER 2 — SQLite/WAL (durable, source of truth)
  Attempts · scores · outcomes · incidents · config · audit
TIER 3 — Filesystem (reproducible artifacts)
  Seeded JSONL · labels · eval outputs · plots · golden fixtures + hashes
```

**Durability: spool-always** *(v2.1 — replaces the in-memory queue design below)*. v1 buffered inserts in memory and flushed every 250 ms and said nothing about what happens if the process dies mid-flush. An in-memory queue cannot survive that: anything not yet flushed at the moment of death is gone by definition, so it cannot satisfy a "nothing acknowledged is lost" guarantee. v2 removes the queue:

- Every accepted attempt is appended to **`spool/attempts-N.jsonl`** with a single `write()` **before the response returns**. This happens **always** — not only after a flush failure.
- A background drainer batches the spool into SQLite, one transaction per batch, and truncates/rotates a spool segment only after that transaction commits.
- Startup drains any surviving segments before the service accepts traffic. Drain is idempotent because `attempt_uid` is a server-minted ULID primary key and inserts use `INSERT OR IGNORE`.
- **Durability boundary: process death, not power loss.** A `SIGKILL` destroys the process but not bytes already handed to the kernel, so a restart recovers everything acknowledged. Machine crash and power loss are explicitly **out of scope** — no `fsync` is required and none is performed. SQLite stays `journal_mode = WAL`, `synchronous = NORMAL`.
- **The guarantee, stated as the caller experiences it:** *every attempt that received a 200 response is present in SQLite exactly once after restart.* An attempt that never received a 200 carries no guarantee — nothing was promised to the caller.
- Rebuild and eval open SQLite **read-only** (`file:…?mode=ro`), so they cannot contend for the write lock; WAL is what actually permits the concurrent read.
- Tested: send attempts, collect the 200s, SIGKILL mid-drain, restart, drain, assert `acknowledged attempts == SQLite rows` and zero duplicates.

---

## 2. Trust classes in the schema

Columns are annotated with their class so nobody has to remember the table in Threat Model §2. **The rule is mechanical: a column marked `C` may never appear in a feature vector, an enforcement key, or an LLM prompt.**

`S` = server-observed · `M` = merchant-attested · `C` = client-asserted

---

## 3. Tables

### 3.1 Configuration

```sql
CREATE TABLE merchant (
    merchant_id      TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    currency         TEXT NOT NULL DEFAULT 'INR',
    timezone         TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    api_key_hash     TEXT NOT NULL,     -- score path
    outcome_hmac_key_hash TEXT NOT NULL,-- SEPARATE secret for /v1/outcome
    created_at       TIMESTAMP NOT NULL
);

CREATE TABLE store_baseline (
    merchant_id           TEXT PRIMARY KEY REFERENCES merchant(merchant_id),
    hourly_volume_profile TEXT NOT NULL,   -- JSON: 24 floats, EWMA
    decline_rate_mean     REAL NOT NULL,
    decline_rate_std      REAL NOT NULL,
    amount_p05_minor      INTEGER NOT NULL,
    amount_p50_minor      INTEGER NOT NULL,
    amount_p95_minor      INTEGER NOT NULL,
    bin_entropy_mean      REAL NOT NULL,
    bin_entropy_std       REAL NOT NULL,
    foreign_bin_share_mean REAL NOT NULL,  -- NEW: core family per Threat Model §7b
    foreign_bin_share_std  REAL NOT NULL,
    cards_per_ip_quantiles TEXT NOT NULL,  -- NEW: JSON deciles. The CGNAT answer.
    flagged_rate_mean     REAL NOT NULL,   -- NEW: p̄₀ for the Poisson CUSUM
    sample_count          INTEGER NOT NULL DEFAULT 0,
    is_stable             BOOLEAN NOT NULL DEFAULT 0,
    updated_at            TIMESTAMP NOT NULL
);
```

`cards_per_ip_quantiles` is the single most important addition here. It converts `distinct_cards_per_ip_5m` from an absolute threshold — which Indian carrier-grade NAT shreds — into a quantile against *this store's own* observed distribution.

```sql
CREATE TABLE policy_config (
    merchant_id      TEXT NOT NULL REFERENCES merchant(merchant_id),
    version          INTEGER NOT NULL,
    thresholds       TEXT NOT NULL,   -- JSON, DERIVED from cost_model, not hand-set
    hysteresis_gap   REAL NOT NULL DEFAULT 0.08,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    cusum_rho        REAL NOT NULL DEFAULT 5.0,
    cusum_h          REAL NOT NULL,
    cusum_bucket_s   INTEGER NOT NULL DEFAULT 10,
    drift_window_s   INTEGER NOT NULL DEFAULT 1800,
    allow_auto_block BOOLEAN NOT NULL DEFAULT 0,   -- ships FALSE
    auto_ceiling     TEXT NOT NULL DEFAULT 'challenge',
    k_max_entities   INTEGER NOT NULL DEFAULT 10,  -- blast-radius cap
    control_fraction REAL NOT NULL DEFAULT 0.05,
    rules_config     TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (merchant_id, version)
);

CREATE TABLE cost_model_config (
    merchant_id            TEXT NOT NULL REFERENCES merchant(merchant_id),
    version                INTEGER NOT NULL,
    auth_fee_minor         INTEGER NOT NULL,
    downstream_exposure_minor INTEGER NOT NULL,
    aov_minor              INTEGER NOT NULL,
    margin_pct             REAL NOT NULL,
    abandonment_by_tier    TEXT NOT NULL,  -- JSON
    prior_steady_state     REAL NOT NULL DEFAULT 0.001,  -- π₀ — NEW, and load-bearing
    prior_under_attack     REAL NOT NULL DEFAULT 0.9,    -- π₁ — NEW
    source_notes           TEXT NOT NULL,  -- every figure's provenance; NOT NULL is the point
    created_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (merchant_id, version)
);
```

`prior_steady_state` and `prior_under_attack` are new and they are the fix for F3. v1's cost model had no prevalence term at all, which made the headline rupee gap arbitrary. Storing them here means the number on the slide can always be traced to a row.

**Config version pinning (was an unhandled edge case).** Both tables are append-only, so a threshold change during days 8–9 creates a new version. An **incident pins the policy version live at the moment it opened** (`incident.pinned_policy_version`) and resolves tiers against that version for its whole lifetime. Without this, a config change landing mid-incident silently changes the meaning of an escalation already in flight.

### 3.2 Event stream

```sql
CREATE TABLE auth_attempt (
    attempt_uid         TEXT PRIMARY KEY,     -- S: server-minted ULID
    merchant_id         TEXT NOT NULL REFERENCES merchant(merchant_id),  -- S: from API key
    event_id            TEXT,                 -- C: caller correlation id ONLY
    payload_digest      TEXT NOT NULL,        -- S: sha256 over M-class fields
    ingest_time         TIMESTAMP NOT NULL,   -- S: injected clock. THE windowing timestamp.
    client_ts           TIMESTAMP,            -- C: audit + clock_skew_s only
    session_id          TEXT,                 -- M: merchant-minted, unguessable

    card_hash           TEXT NOT NULL,        -- M
    bin                 TEXT NOT NULL,        -- M
    last4               TEXT,                 -- M
    exp_month           INTEGER,              -- M
    exp_year            INTEGER,              -- M

    amount_minor        INTEGER NOT NULL,     -- M
    currency            TEXT NOT NULL,        -- M

    ip                  TEXT,                 -- S: TCP peer / validated XFF
    asn                 INTEGER,              -- S: offline lookup
    ua_class            TEXT,                 -- S: deterministic classifier over the UA string
    ipua_key            TEXT,                 -- S: sha1(ip ‖ ua_class) — composite entity

    client_evidence     TEXT                  -- C: JSON blob. user_agent, device_id,
                                              --    fingerprint_hash, checkout_path,
                                              --    time_on_site_ms, is_guest, cart_item_count.
);
```

**Why the C-class fields are one opaque blob.** In v1 they were first-class columns, indistinguishable from `ip` or `amount_minor`, and they duly ended up in the feature list. Collapsing them into `client_evidence` makes "use this as a feature" an awkward act requiring a JSON extract, and makes the trust-boundary test trivial to write. The UI renders the blob under a *client-asserted, unverified* header.

`user_agent` lives inside that blob and **never leaves the database** — the model sees `ua_class`, the narrator sees nothing.

```sql
CREATE TABLE attempt_score (
    attempt_uid       TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    score_raw         REAL NOT NULL,
    score_calibrated  REAL NOT NULL,     -- AFTER prior correction
    prior_used        REAL NOT NULL,     -- NEW: π_s at decision time
    regime            TEXT NOT NULL,     -- NEW: in_control|alarm — which prior applied
    decision          TEXT NOT NULL,     -- one of the six Decision values
    tier_ladder       TEXT NOT NULL,     -- NEW: domestic|foreign — AFA-aware ladder used
    control_arm       BOOLEAN NOT NULL DEFAULT 0,  -- NEW: enforcement withheld deliberately
    shed              BOOLEAN NOT NULL DEFAULT 0,  -- NEW: scored in rules-only mode
    model_version     TEXT NOT NULL,
    calibrator_version TEXT NOT NULL,    -- NEW
    policy_version    INTEGER NOT NULL,
    rules_fired       TEXT,
    feature_snapshot  TEXT NOT NULL,     -- JSON. THE training substrate — see below.
    top_contributors  TEXT,
    incident_id       TEXT REFERENCES incident(incident_id),
    latency_ms        INTEGER NOT NULL,
    scored_at         TIMESTAMP NOT NULL
);
```

**`feature_snapshot` is now actually read.** v1 called it the most valuable column in the schema and then routed training through a separate pandas path, so it would never have been opened. In v2 it is the *only* training input (TRD §6.4). Point-in-time correctness stops being a claim and becomes the mechanism.

**`control_arm`** marks attempts where enforcement was deliberately withheld (default 5%, seeded). These are the only attempts that produce unbiased outcomes while an entity is under enforcement — without them, blocking an attacker destroys the decline-rate signal that justified blocking, and the retraining loop feeds on its own censorship (Eval Protocol §6.1).

```sql
CREATE TABLE auth_outcome (
    attempt_uid       TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    gateway_status    TEXT NOT NULL,        -- authorized|declined|error
    decline_code      TEXT,                 -- closed vocabulary, 9 values
    gateway_latency_ms INTEGER,
    auth_fee_minor    INTEGER,
    reached_gateway   BOOLEAN NOT NULL,     -- NEW: false ⇒ censored by enforcement
    sig_verified      BOOLEAN NOT NULL,     -- NEW
    ingest_time       TIMESTAMP NOT NULL    -- S: when the info became available.
                                            --    Decline windows are written at THIS time.
);

CREATE TABLE outcome_nonce (              -- NEW: replay protection for the signed webhook
    nonce       TEXT PRIMARY KEY,
    seen_at     TIMESTAMP NOT NULL
);
```

Nullable one-to-one; **the code must never assume it exists.** `reached_gateway = false` is the explicit representation of selective labelling: the attempt was stopped, so there is no outcome and there never will be. `outcome_coverage_ratio` is computed from it.

```sql
CREATE TABLE bin_metadata (
    bin        TEXT PRIMARY KEY,
    issuer     TEXT,
    country    TEXT,
    is_foreign BOOLEAN NOT NULL,   -- NEW: promoted to first class per Threat Model §7b
    brand      TEXT,
    card_type  TEXT
);
```

Static, offline, **entirely synthetic** — fictional ranges, no real issuer data.

### 3.3 Incidents

```sql
CREATE TABLE incident (
    incident_id           TEXT PRIMARY KEY,
    merchant_id           TEXT NOT NULL REFERENCES merchant(merchant_id),
    state                 TEXT NOT NULL,   -- OPEN|ESCALATED|COOLING|CLOSED
    detector              TEXT NOT NULL,   -- NEW: cusum|drift|both
    opened_at             TIMESTAMP NOT NULL,
    escalated_at          TIMESTAMP,
    cooling_at            TIMESTAMP,
    closed_at             TIMESTAMP,

    peak_tier             TEXT NOT NULL,
    attempts_total        INTEGER NOT NULL DEFAULT 0,
    attempts_before_alert INTEGER,
    cards_exposed_before_alert INTEGER,    -- NEW: the harm unit, and the headline
    time_to_detect_s      REAL,            -- event time, demoted to third
    cusum_stat_at_alert   REAL,
    decline_mix           TEXT,

    narrative             TEXT,
    narrative_source      TEXT,            -- llm|template
    recommended_tier      TEXT,            -- from the POLICY ENGINE, never from the LLM

    resolution            TEXT,            -- attack_confirmed|false_positive|expired
    resolved_by           TEXT,            -- auto|operator
    pinned_policy_version INTEGER NOT NULL -- NEW: pinned at open; see §3.1
);
```

`cards_exposed_before_alert` leads because it is what the merchant actually loses. For a low-and-slow attack, time-to-detect is measured in hours, looks terrible, and is a property of the attacker's pacing rather than the detector's sensitivity (Eval Protocol §2.2).

```sql
CREATE TABLE incident_entity (
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    entity_type   TEXT NOT NULL,   -- ip|ipua|bin|card|asn
    entity_key    TEXT NOT NULL,
    pseudonym     TEXT NOT NULL,   -- NEW: 'ip_1', 'bin_A' — what the narrator sees
    attempt_count INTEGER NOT NULL DEFAULT 0,
    first_seen    TIMESTAMP NOT NULL,
    last_seen     TIMESTAMP NOT NULL,
    PRIMARY KEY (incident_id, entity_type, entity_key)
);

CREATE TABLE tier_transition (
    transition_id TEXT PRIMARY KEY,
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    from_tier     TEXT,
    to_tier       TEXT NOT NULL,
    trigger       TEXT NOT NULL,   -- cusum|drift|score|manual|cooldown
    signal_value  REAL,
    at            TIMESTAMP NOT NULL
);

CREATE TABLE enforcement_action (
    action_id     TEXT PRIMARY KEY,
    incident_id   TEXT REFERENCES incident(incident_id),
    merchant_id   TEXT NOT NULL REFERENCES merchant(merchant_id),
    entity_type   TEXT NOT NULL,        -- NOT NULL: store-wide is unrepresentable
    entity_key    TEXT NOT NULL,        -- NOT NULL: same
    tier          TEXT NOT NULL,
    requires_confirmation BOOLEAN NOT NULL DEFAULT 0,  -- NEW: true for step_up/block
    confirmed_by  TEXT,                                -- NEW: NULL ⇒ not yet in force
    applied_at    TIMESTAMP,
    expires_at    TIMESTAMP NOT NULL,
    released_at   TIMESTAMP,
    applied_by    TEXT NOT NULL         -- auto|operator
);
```

The `requires_confirmation` / `confirmed_by` pair is the schema-level expression of the auto-ceiling. A `block` row can exist with `confirmed_by IS NULL` and `applied_at IS NULL` — proposed, visible on D3, not in force. This is what makes the enforcement-poisoning primitive in Threat Model §4 worth so little.

The `pseudonym` column exists so the narrator's evidence bundle can be built by a query rather than by a mapping held in application memory that someone will eventually forget to apply.

```sql
CREATE TABLE narrator_call (
    call_id       TEXT PRIMARY KEY,
    incident_id   TEXT NOT NULL REFERENCES incident(incident_id),
    backend       TEXT NOT NULL,   -- template|gemini
    requested_at  TIMESTAMP NOT NULL,
    status        TEXT NOT NULL,   -- ok|timeout|rate_limited|schema_invalid|charset_rejected
    latency_ms    INTEGER,
    fallback_used BOOLEAN NOT NULL DEFAULT 0
);
```

`charset_rejected` is new: it is how you find out the injection gate fired.

### 3.4 Ground truth and evaluation

```sql
CREATE TABLE episode_truth (
    episode_id     TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,   -- attack|negative_control
    tier           TEXT,            -- easy|medium|hard|evasive
    scenario       TEXT,            -- flash_sale|cgnat|retry_storm|subscription_batch|
                                    -- nri_traffic|shared_ip_legit
    started_at     TIMESTAMP NOT NULL,
    ended_at       TIMESTAMP NOT NULL,
    attempt_count  INTEGER NOT NULL,
    distinct_cards INTEGER NOT NULL,  -- NEW: denominator for cards_exposed
    generator_seed INTEGER NOT NULL,
    evasion_params TEXT               -- NEW: the vector Tier E's search converged on
);

CREATE TABLE attempt_label (
    attempt_uid TEXT PRIMARY KEY REFERENCES auth_attempt(attempt_uid),
    is_attack   BOOLEAN NOT NULL,
    episode_id  TEXT REFERENCES episode_truth(episode_id),
    entity_overlap BOOLEAN NOT NULL DEFAULT 0,  -- NEW: legit event sharing an entity
                                                -- with a concurrent attack — the F14 case
    source      TEXT NOT NULL DEFAULT 'simulator'
);

CREATE TABLE eval_run (
    run_id         TEXT PRIMARY KEY,
    created_at     TIMESTAMP NOT NULL,
    model_version  TEXT NOT NULL,
    calibrator_version TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    split_name     TEXT NOT NULL,
    prior_assumed  REAL NOT NULL,     -- NEW: no metric without its prevalence
    eval_prevalence REAL NOT NULL,    -- NEW: after resampling to π_eval
    config_hash    TEXT NOT NULL,
    fixture_sha256 TEXT NOT NULL,     -- NEW: tamper-evidence, see §7
    stream_seed    INTEGER NOT NULL,
    metrics        TEXT NOT NULL,
    artifacts_path TEXT NOT NULL
);
```

`entity_overlap` is what makes the "clean subset" reporting possible: instance-dependent label noise is measurable rather than merely acknowledged.

**Labels stay in their own table**, and the scoring path still never touches it. In production the table does not exist, and the fact that the same scoring code runs in both cases is itself the evidence that no leakage is possible.

---

## 4. Redis key schema

Every key is `tg:{merchant_id}:…`. **No exceptions** — v1's unscoped `tg:z:ip:203.0.113.4` made the multi-tenancy claim false at the hot path while `tg:cusum:{merchant}` was scoped, which is worse than being consistently single-tenant.

| Pattern | Type | Purpose |
|---|---|---|
| `tg:{m}:w:{space}:{key}:{metric}` | Sorted set | Sliding windows. Score = `ingest_ms`, member = `attempt_uid` or the distinct value. `metric ∈ ev·card·bin·amt` |
| `tg:{m}:decl:{space}:{key}` | Sorted set | Decline events, written at the **outcome's** ingest time |
| `tg:{m}:card24:{card_hash}` | String | `INCR` + TTL. The only 24 h datum. |
| `tg:{m}:baseline` | Hash | Hot copy of `store_baseline` |
| `tg:{m}:cusum` | Hash | `S_t`, `last_bucket`, bucket counter. **Updated inside the Lua script.** |
| `tg:{m}:drift:{entity}` | Sorted set | L2b distinct-card accumulation over 30 m |
| `tg:{m}:incident:active` | String | Current open incident id |
| `tg:{m}:enforce:{type}:{key}` | String | Active enforcement. TTL is the expiry mechanism. |
| `tg:{m}:enforce:count` | String | Live count against `k_max_entities` |
| `tg:{m}:idem:{digest}` | String | `SET NX PX` — idempotency. Value = `attempt_uid`. |
| `tg:{m}:eidr:{event_id}` | Set | Distinct payload digests seen per `event_id` → `event_id_reuse_count` |
| `tg:{m}:shed:{ip}` | String | Volume counter for requests shed in rules-only mode |
| `tg:{m}:counters:{win}` | Hash | Live dashboard counters |

**Three properties that are now mechanisms rather than intentions:**

- **TTL is memory hygiene, not correctness.** Trimming is an explicit `ZREMRANGEBYSCORE` against the injected clock inside the Lua script. No feature's value depends on a TTL's phase — which was exactly the defect that made HyperLogLog unusable.
- **Idempotency is atomic.** `SET NX` in one operation, not `GET` then `SET`. Two concurrent duplicates: one wins, the other reads the stored decision.
- **Enforcement expiry is TTL.** No cron, no sweeper, no stuck block outliving its incident. `enforcement_action.expires_at` is the audit record of the same fact.

---

## 5. API to table mapping

| Endpoint | Reads | Writes |
|---|---|---|
| `POST /v1/score` | Lua: windows + CUSUM (one round trip); `tg:{m}:baseline`, `tg:{m}:enforce`; in-memory model + BIN table | `auth_attempt`, `attempt_score` (buffered), windows, `tg:{m}:idem`, `tg:{m}:eidr` |
| `POST /v1/outcome` | `outcome_nonce` | `auth_outcome`, `outcome_nonce`, decline windows |
| `GET /v1/incidents/{id}` | `incident`, `incident_entity`, `tier_transition`, `enforcement_action`, `attempt_score` | — |
| `POST /v1/incidents/{id}/action` | `incident` | `enforcement_action.confirmed_by`, `tier_transition`, `incident.resolution` |
| `GET /v1/metrics/live` | `tg:{m}:counters`, `tg:{m}:cusum` | — |
| `SSE /v1/stream` | Redis pub/sub | — |

### Write path (v2)

```
POST /v1/score
  ├─ auth: API key → merchant_id .............. in-process
  ├─ admission control: token bucket .......... in-process   ← rules-only rung
  ├─ mint attempt_uid, ingest_time = clock.now()
  ├─ ONE Lua script: idem SET NX → ZADD writes →
  │  trim → read window vector → CUSUM bucket incr ... 1 round trip
  ├─ feature assembly (S/M only) .............. in-process + BIN table
  ├─ rules → model → Platt → prior correction . in-process
  ├─ policy: ladder by card provenance, hysteresis,
  │          auto-ceiling, blast-radius cap ... in-process + tg:enforce
  ├─ RESPOND ← p99 < 100 ms
  └─ async: buffered SQLite insert, SSE publish
```

The two changes from v1 that matter: **window writes are inside the atomic script and precede the response** (so attempt *N* is visible when *N+1* is scored — v1 undercounted velocity exactly under attack), and **the CUSUM increment is inside the same script** (so concurrent workers cannot lose updates during the burst regime where the statistic must climb).

### Rebuild path

```
Redis lost
  └─ SELECT * FROM auth_attempt WHERE ingest_time > now() - 6h ORDER BY ingest_time
      └─ replay through the windowing layer only (no scoring, no incidents)
          └─ recompute CUSUM from attempt_score.score_calibrated
```

Worth an hour. Converts a stage-side Redis failure from fatal to a twenty-second pause. Six hours rather than 24 now that the widest window is 30 minutes.

---

## 6. Indexes

```sql
CREATE INDEX ix_attempt_merchant_ing  ON auth_attempt(merchant_id, ingest_time DESC);
CREATE INDEX ix_attempt_ip_ing        ON auth_attempt(ip, ingest_time DESC);
CREATE INDEX ix_attempt_bin_ing       ON auth_attempt(bin, ingest_time DESC);
CREATE INDEX ix_attempt_card_ing      ON auth_attempt(card_hash, ingest_time DESC);
CREATE INDEX ix_attempt_event_id      ON auth_attempt(merchant_id, event_id);
CREATE INDEX ix_score_incident        ON attempt_score(incident_id);
CREATE INDEX ix_score_control_arm     ON attempt_score(control_arm, scored_at DESC);
CREATE INDEX ix_incident_state        ON incident(merchant_id, state, opened_at DESC);
CREATE INDEX ix_entity_lookup         ON incident_entity(entity_type, entity_key);
CREATE INDEX ix_enforce_active        ON enforcement_action(entity_type, entity_key, released_at);
CREATE INDEX ix_label_episode         ON attempt_label(episode_id);
```

All `ts DESC` composites are now `ingest_time DESC`, because that is the axis every query actually uses.

---

## 7. Fixture integrity (fixes the golden-fixture circularity)

The golden fixture was generated by the builder, the golden answers were generated by the builder, and the builder was then measured against both. "Frozen after Phase 3" was a sentence in a document, not a mechanism.

**v2 mechanisms:**

- `tests/fixtures/golden.jsonl` ships with `tests/fixtures/golden.sha256`. `tests/acceptance/test_fixture_integrity.py` asserts the hash on every run, and `eval_run.fixture_sha256` records which fixture produced each number.
- **`tests/fixtures/handmade_40.jsonl`** — 40 events written by hand, event by event, with expected feature values and incident timing computed by hand. This is the independent oracle the v1 plan never had for Layer 2. An hour of work; it is the ungameable core of the suite. **v2.1 carve-out: this fixture and its expected values must NOT be generated by the implementation agent.** An agent that authors both the fixture and its expected values produces a self-consistent artifact with zero oracle value — the fixture's entire purpose is to be independent of any code the builder wrote. Forty events and their expected feature values and alert point are computed independently, on paper, by a human.
- Expectations are split: `tests/acceptance/analytic/` (derivable from the spec — ungameable) and `tests/characterization/` (observed values — change detectors only, explicitly **not** acceptance criteria). See Implementation Plan §1.

---

## 8. Privacy and retention

**Never present in any table:** raw PAN, CVV in any form, raw email or phone, cardholder name, billing address. Only `card_hash` (caller-supplied, salted merchant-side), `bin`, `last4`.

Truncated PAN as first-six plus last-four is the standard accepted form and keeps Tollgate outside full PCI DSS scope. State it in the README — a Razorpay judge is likely to ask, and having the answer in the schema is stronger than having it in prose.

**IP addresses are stored** because velocity features require them; under real deployment that is personal data in several jurisdictions, so retention is bounded.

| Table | Retention |
|---|---|
| `auth_attempt`, `attempt_score`, `auth_outcome` | 30 days |
| `incident` and children | 1 year |
| Config tables | Indefinite (versioned; needed to interpret historical metrics) |
| Redis | ≤ 2× widest window |

Retention is disabled in the demo build so the seeded stream stays queryable. Say so in the README rather than letting it look like the policy was never considered.

---

## 9. Bootstrap

```
1. sqlite3 tollgate.db < schema.sql          → schema (no Alembic)
2. python -m scripts.seed_merchant           → merchant + baseline + config v1
3. python -m scripts.load_bin_table          → bin_metadata (synthetic)
4. python -m simulator.generate --seed 42    → data/streams/{events,labels}.jsonl
5. python -m scripts.replay --speed 0        → events through /v1/score at full tilt,
                                                writing attempt_score.feature_snapshot
6. python -m scripts.train_l1                → model + Platt calibrator FROM the snapshots
7. python -m eval.harness --split all        → eval_run rows + artifacts
```

**Step 5 is new and it is the structural fix for F8.** Training reads what the online path logged, so there is exactly one feature implementation and point-in-time correctness is free. It also means the walking skeleton must exist before the model does — which is why the Implementation Plan front-loads it.
