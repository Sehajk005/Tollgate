# Day 6 — Layer 2 + Policy

> **First action on approval:** copy this document verbatim to
> `D:\Projects\Tollgate\08-DAY-6-IMPLEMENTATION-PLAN.md`. Plan mode restricts edits to
> this file, so the deliverable the brief asked for is produced as execution step 0.

---

## Context

Days 1–5 are complete. The system today **scores but does not decide**:
`services/scorer/scoring.py:125` reads `decision = apply_auto_ceiling(evaluation.minimum_tier)`
— the R1–R3 rule floors are the only thing that moves a decision, while the Layer-1
calibrated posterior is computed, logged to `attempt_score.score_calibrated`, and thrown away.
`packages/detect/policy.py` is 34 lines: one `apply_auto_ceiling` clamp. There is no CUSUM
statistic, no drift test, no incident, no entity resolution, no enforcement.

Day 6 closes that loop. Layer 2a (Poisson CUSUM over τ_flag-gated counts) and Layer 2b
(a sequential distinct-card drift test) open real incidents; an episode state machine gives
those incidents a lifecycle; and a policy engine turns `p_calibrated` + Layer-2 evidence into
an **entity-scoped, cost-derived, hysteresis-damped, blast-radius-capped** enforcement
proposal that can never automatically exceed `challenge`.

Three things make this day unusually constrained, and the plan is shaped around them:

1. **Layer 2 has no independent oracle and never will** (Impl Plan §1.4). The gates are
   analytic closed forms and metamorphic relations M1–M8, not recorded observations.
2. **The Day-5 artifacts must not shift.** `models/`, `models/audit.json`, and the
   `eval_run` rows are all derived from `eval/corpus.py`'s replay through `score_attempt`.
   Every Day-6 addition is therefore **guarded and opt-in**, byte-identical to Day 5 when
   the Layer-2 objects are absent — exactly the pattern Day 5 used for `state.model`.
3. **`tests/fixtures/handmade_40.*` does not exist.** Decision 14 forbids an agent
   generating it. Per your ruling, Day 6 ships complete and is tagged `day-6-done` only
   after you hand-compute the fixture and its incident gate goes green.

---

## 1. Day 6 objective

Ship `packages/detect/{cusum,drift,episode,policy}.py`, wire them into the single existing
`score_attempt()` path behind a guard, persist incidents and enforcement through the existing
spool→drainer→SQLite discipline, and surface enforcement on the SSE stream and the D1
`ENFORCEMENT` tile.

**Exit:** one incident opens on `handmade_40.jsonl` at the hand-counted alert point.
**Cut rule (20:00):** cut L2b — keep L2a, episode, and policy — and report the `hard` tier
as undetected, honestly.

---

## 2. Current state from Days 1–5 (what Day 6 reuses, and must not break)

### Already exists — reuse, do not rebuild

| Asset | Location | Day-6 use |
|---|---|---|
| **Full Day-6 schema** | `schema.sql` (repo **root**, not `packages/storage/`) | `incident`, `incident_entity`, `tier_transition`, `enforcement_action`, `policy_config`, `store_baseline`, `cost_model_config` all exist with the right columns, FKs and indexes. **Zero migration** except one CHECK (§3.5). |
| **Every Day-6 knob is already a column** | `policy_config` | `cusum_rho(5.0)`, `cusum_h`, `cusum_bucket_s(10)`, `drift_window_s(1800)`, `hysteresis_gap(0.08)`, `cooldown_seconds(300)`, `k_max_entities(10)`, `control_fraction(0.05)`, `auto_ceiling('challenge')`, `allow_auto_block(0)`, `thresholds` |
| **θ_T derivation** | `eval/cost.py::CostModel.tier_ladder()` | Already implements Eval Protocol §1.3 and is tested against the literals `{0.065, 0.257, 0.509, 0.874}` (`test_cost_thresholds.py`). **Orphaned today — nothing in `services/` calls it.** Day 6 must not re-derive thresholds by hand. |
| **Alarm-regime prior** | `packages/detect/calibrate.py::serving_prior(regime, cost_model, *, rate_ratio)` | Implemented and unit-tested, docstring says outright it is **UNWIRED pending Day 6's rate_ratio→prior map**. |
| **Auto-ceiling clamp** | `packages/detect/policy.py::apply_auto_ceiling` | Keep calling it; it is Threat Model §4/P1's mechanism. |
| **Raw CUSUM bucket counter** | `packages/features/windows.lua` step 6; `ScorePathSnapshot.cusum_bucket_index/_count` | Bucket rollover on `floor(ingest_ms / bucket_ms)` already exists in both backends. |
| **Injected-stream replay seam** | `ReplayDriver.run(request, stream=...)` + `VirtualClock` | Gives every Day-6 detector test deterministic event time for free; already used by `eval/corpus.py::_replay_one`. |
| **Negative-control corpus** | `eval/corpus.py::build_runs(42)` → runs 12–18 (`m-eval-12`…`m-eval-18`), one per scenario | The only data `h` tuning and baseline learning may read. |
| **Evidence bundle** | `packages/narrator/bundle.py` | Its docstring already says the shape is *"deliberately the same one Day 6's incident-level narrator call will use"*; `incident_entity.pseudonym` is the column it anticipates. |
| **Versioned policy writer** | `repository.py::append_policy_config` / `get_latest_policy_version` | Insert-only, every Day-6 knob a kwarg. `test_policy_versioning.py` already locks the append-only behaviour. |

### Missing — Day 6 builds

`S_t` arithmetic · τ_flag gating · drift test · incident lifecycle · entity resolution ·
θ_T application on the serving path · hysteresis · `K_max` · control arm · repository writers
for incident/entity/transition/enforcement · a `store_baseline` row (**the table has 0 rows**)
· `config/policy.yaml`.

### Hard constraints Day 6 must not break

| Constraint | Enforced by | Consequence for the design |
|---|---|---|
| Exactly one `store.score_path()` per score | `test_one_round_trip.py` | The τ_flag-gated count **cannot** be a second Redis write. §3.1 resolves this. |
| No `time.time()` / `datetime.now()` outside `packages/clock` | `test_clock_discipline.py` (repo-wide AST scan) | Every incident timer rolls on `ingest_ms`. |
| p99 < 5 ms for the serving step | `test_inference_latency.py` | Layer 2 + policy must be in-process arithmetic, no I/O. |
| `compute_features` is a pure function of the event prefix | `test_time_travel.py` | Layer-2 state is a **pure fold over the same prefix**, asserted by M8. |
| `packages/detect/` imports no ground-truth-label source | `test_detect_label_isolation.py` | The `h`-tuning script lives in `scripts/`, never in `packages/detect/`. |
| `InMemoryWindowStore.clear()` clears all state | `ReplayDriver.reset()` | Any new per-entity dict must be cleared, or Reset leaks across demo runs. |
| `Drainer.drain_once` hardcodes `payload["attempt"]` / `payload["score"]` | `drainer.py:62-63` | New record types need explicit handling (§3.4). |
| `FEATURE_NAMES` is exactly 24 and the model's contract | `test_model_feature_list.py`, `assert len(...) == 24` | Day 6 adds **no** model feature. New window outputs ride on `FeatureVector` fields, not `FEATURE_NAMES`. |
| Day-5 corpus/model/eval_run must not shift | `eval/corpus.py`, `models/`, `test_eval_run_row.py` | Layer 2 is guarded: absent → byte-identical to Day 5. |

---

## 3. Required changes

### 3.0 New configuration — `config/policy.yaml`

**Why:** every CUSUM/policy tunable today lives only as a `policy_config` column default;
four Day-6 quantities have no home anywhere (`τ_flag`, the ARL₀ target, L2b's statistic
parameters, the `hysteresis_gap → T_enter/T_exit` mapping). *Source: TRD §6.5/§6.6/§6.7;
Decision 45 explicitly deferred τ_flag to today.*

Same `{value, unit, source}` leaf shape as `config/features.yaml`. Added to
`eval/provenance.py::DEFAULT_CONFIG_PATHS` (line 39) so it is covered by `config_hash` —
this changes hash **values**, but `test_config_hash.py` is fully relative and asserts nothing
absolute (its own header says so).

```yaml
cusum:
  tau_flag_source: "theta_throttle"   # DERIVED, never a literal
  lambda_min:      0.01               # TRD §6.5, verbatim
  rho:             5.0                # TRD §11 row 5 (mirrors policy_config.cusum_rho)
  bucket_s:        10                 # TRD §11 row 3
  target_arl0_buckets: 8640           # = 24 virtual hours at 10 s buckets  [DECIDED TODAY]
drift:
  window_s:             1800          # TRD §6.6 "30 virtual minutes"
  exceedance_quantile:  0.95          # [DECIDED TODAY]
  p1:                   0.5           # [DECIDED TODAY]
  alpha:                0.01
  beta:                 0.05
  enabled:              true          # the L2b cut switch (§9)
policy:
  hysteresis_gap:       0.08          # mirrors policy_config
  enforcement_ttl_s:    900
  control_fraction:     0.05
```

**τ_flag = θ_throttle.** Not a literal: `CostModel.tier_ladder()["throttle"]` ≈ 0.0645 — the
point at which acting is already cost-justified. Invents no number, ties L2a to the same cost
model as the policy ladder, and moves automatically if `cost_model.yaml` changes.

### 3.1 `packages/detect/cusum.py` — Layer 2a

**Why:** TRD §6.5 is the authoritative formulation and nothing implements it. Decision 45
left the gating question explicitly open for today.

```
n_t   = # attempts in bucket t with p_calibrated ≥ τ_flag
λ₀(t) = baseline_rate(hour_of_day) × Δ × p̄₀        floored at λ_min = 0.01
λ₁    = ρ · λ₀(t)
S_t   = max(0, S_{t−1} + n_t·ln(λ₁/λ₀) − (λ₁ − λ₀))
alarm when S_t > h
```

- `Δ` = `cusum_bucket_s` seconds. `baseline_rate(hour_of_day)` reads
  `store_baseline.hourly_volume_profile` (24 EWMA floats); `p̄₀` reads
  `store_baseline.flagged_rate_mean`. Both come from §3.7.
- `hour_of_day` is derived from `ingest_ms` **arithmetically** (`(ingest_ms // 3_600_000) % 24`)
  — no `datetime`, so `test_clock_discipline.py` stays green and M1 (shift all ingest times by
  Δ) holds when Δ is a whole number of hours.
- **Bucket index comes from `ScorePathSnapshot.cusum_bucket_index`**, which today is computed,
  returned across the protocol boundary, and *dropped on the floor* by `compute_features`.
  Plumbing it through closes an existing gap rather than adding a mechanism.
- **Where `n_t` is counted — the decision Decision 45 deferred.** The Lua increment happens
  *before* `p_calibrated` exists, and a second Redis write would break the one-round-trip
  invariant and the latency budget. So the gated count and `S_t` are maintained **in-process**,
  on `ScorerState`, exactly as `ThreatRollup` already is. The raw Lua counter is left
  untouched and is used only as a cross-check. *Limitation, stated: CUSUM state is
  per-process and does not survive restart or span multiple Uvicorn workers. The
  Redis-backed `tg:{m}:cusum` `S_t` that Backend Schema §4 describes is deferred.*
- Alarm behaviour: on `S_t > h`, emit an alarm carrying `(bucket_index, S_t, rate_ratio =
  n_t / λ₀)` and **hold** `S_t` (no reset) so a sustained attack stays in alarm; `S_t` decays
  naturally through empty buckets. `incident.cusum_stat_at_alert` records `S_t` at first alarm.
- API: `PoissonCusum(params).observe(bucket_index, n_flagged, lambda0) -> CusumStep` plus a
  pure `steps_to_alarm(h, lam0, lam1)` returning the closed form
  `h / (λ₁·ln(λ₁/λ₀) − (λ₁ − λ₀))` — **the same function the analytic test calls**, so the
  test compares the recursion against the formula rather than against a recorded number.

### 3.2 `packages/detect/drift.py` — Layer 2b

**Why:** TRD §6.6 names L2b as the instrument for low-and-slow, where a 10 s bucket is empty.
The spec gives the shape ("sequential test on distinct card hashes per entity over 30 virtual
minutes, scored as a quantile against the store's own learned distribution") but **not the
statistic, the firing quantile, or the threshold** — all three are decided here.

- **Entity/key:** `ip`, and `ipua` — the two spaces the window store already maintains and the
  two `_q` features TRD §6.8 names. Never `bin` (that is R3's geometry), never `asn`.
- **Required feature input:** `distinct_cards_per_ip_30m`. This window **does not exist today**
  (`compute_features` builds ten windows; the only 30 m one is `attempts_per_session`).
  Add it as an **11th `WindowRequest` inside the same `score_path()` call** —
  `w("ip", ctx.ip, "card", ctx.card_hash, WINDOW_30M_MS)` — appended at index 10 so no
  existing positional index shifts, and still exactly one round trip. Surfaced as a new
  defaulted `FeatureVector.distinct_cards_per_ip_30m_raw` field, **not** in `FEATURE_NAMES`
  and **not** in `snapshot()`, so the model contract and the training corpus are untouched.
  *(This is the same pattern Decision 17 already established with
  `distinct_cards_per_ip_5m_raw`.)*
- **Statistic — a one-sided Wald SPRT on quantile exceedance.** Per entity, per attempt:
  `z_i = 1[distinct_cards_per_ip_30m ≥ q_hi]`, where `q_hi` is the store's learned 95th
  percentile of that statistic. Under H₀ the exceedance rate is `p₀ = 1 − 0.95 = 0.05` **by
  construction of the quantile**; under H₁ it is `p₁ = 0.5`.
  `Λ_i = max(0, Λ_{i−1} + z_i·ln(p₁/p₀) + (1−z_i)·ln((1−p₁)/(1−p₀)))`; fire when
  `Λ ≥ A = ln((1−β)/α) ≈ 4.55`. Sequential, accumulation-driven, quantile-scored, and — like
  the CUSUM — analytically checkable.
- **Learned distribution:** `store_baseline.cards_per_ip_quantiles`, written by §3.7 as
  `{"5m": [...deciles...], "30m": [...deciles...]}`. *Decision: the column's schema comment
  says "JSON deciles"; the 30 m window L2b needs has no baseline anywhere, so the column
  carries both windows keyed by width. The table has 0 rows today, so there is no
  compatibility cost.*
- **Integration with L2a:** an incident opens if **either** detector fires (TRD §6.6).
  `incident.detector` records `cusum` | `drift` | `both`; `tier_transition.trigger` records
  which detector drove each transition. Per-detector attribution is what lets the report say
  which shape each tier was caught by.

### 3.3 `packages/detect/episode.py` — the incident state machine

**Why:** Impl Plan Day 6 deliverable; `packages/detect/threat_state.py::ThreatRollup` is the
declared Day-2 stand-in and its own docstring names today as its replacement point
(Decision 33).

`IncidentState = OPEN | ESCALATED | COOLING | CLOSED` (matching `incident.state`'s comment).

| From | To | Trigger |
|---|---|---|
| — | OPEN | either detector fires on an entity with no live incident |
| OPEN | ESCALATED | proposed tier rises, or the second detector also fires |
| OPEN / ESCALATED | COOLING | no detector fire for `cooldown_seconds` of **event time** |
| COOLING | OPEN | **re-fire during cooldown — merge, same `incident_id`**, `cooling_at` cleared |
| COOLING | ESCALATED | re-fire that also strengthens evidence |
| COOLING | CLOSED | `cooldown_seconds` elapses with no re-fire; `resolved_by='auto'` |
| CLOSED | *(nothing)* | any transition raises `IllegalTransition` — `CLOSED → ESCALATED` is the named test case |

- **Identity & merging.** `IncidentRegistry` is a `Dict[EntityKey, Incident]` per merchant.
  Re-fire during cooldown resolves to the same key → the same `Incident` object → **merge, not
  a second row**. This is what makes the cooldown-merge test pass structurally rather than by
  a special case.
- **Overlapping incidents** are simply distinct keys in the registry: two entities can hold
  simultaneous OPEN incidents with independent cooldown timers, neither clobbering the other.
- **An episode spanning the fixture boundary** works because the machine holds no
  end-of-stream assumption and is a pure fold over `ingest_ms`; feeding a stream in two halves
  against a warm registry yields one incident. This is M8 at incident level and is tested as
  both.
- **Pinning.** `Incident.pinned_policy_version` is stamped from the live `PolicySnapshot` at
  open and every later tier resolution for that incident reads the pinned snapshot, never the
  current one (Backend Schema §3.1, verbatim).
- **Harm fields Day 6 owns and must populate:** `attempts_total`, `attempts_before_alert`,
  `cards_exposed_before_alert` (distinct card hashes on the entity before first fire — Eval
  Protocol §2.2's headline harm unit), `time_to_detect_s` in **event time**,
  `cusum_stat_at_alert`, `peak_tier`.
- **`threat_state` continuity.** `score_attempt` sources `threat_state` from the registry
  (`none/CLOSED→calm`, `OPEN→elevated`, `ESCALATED→under_attack`, `COOLING→resolved`) when a
  policy is attached, and falls back to `ThreatRollup` when it is not. The four strings and
  the SSE key are unchanged, so `services/dashboard/src/App.jsx` and `test_day2_e2e.py` keep
  passing unmodified, and the Day-5 corpus replay (which attaches no policy) is byte-identical.

### 3.4 Persistence — `packages/storage/repository.py` + `drainer.py`

**Why:** the tables exist but nothing writes them; only `insert_attempt`, `insert_score`,
`append_policy_config`, `get_latest_policy_version` exist today.

New writers, following the existing `INSERT OR IGNORE` / stable-PK pattern:
`upsert_incident` (`ON CONFLICT(incident_id) DO UPDATE` — state changes over the incident's
life), `upsert_incident_entity`, `insert_tier_transition`, `insert_enforcement_action`,
`read_active_enforcement_count`, plus readers `load_policy_config(conn, merchant_id, version)`
→ `PolicySnapshot` and `load_store_baseline(conn, merchant_id)` → `StoreBaseline`.

**Route through the existing spool, not a new path.** `score_attempt` already appends
`{"attempt": …, "score": …}` before responding; Day 6 adds optional
`"incident" / "incident_entity" / "tier_transition" / "enforcement"` keys to that same
payload. `Drainer.drain_once` (currently hardcoding two keys at `drainer.py:62-63`) gains
`if "incident" in payload:` branches. This keeps the spool-always durability invariant
(Decision 7/8) and keeps SQLite off the hot path. Upserts make the drainer's byte-0 re-drain
idempotent — the incident's final state is re-derived by replaying its transitions in order.

`attempt_score.incident_id` (currently hardcoded `None`) becomes the live incident id.

### 3.5 Entity resolution — in `packages/detect/policy.py`

**Why:** Impl Plan Day 6 lists entity resolution as a `policy.py` deliverable; TRD §6.7 says
"entity-scoped, never store-wide — **enforced in the schema, not just in code**."

- **Narrowest key that covers the evidence** (TRD §6.2 rule 2):
  `card_hash` → `(ip, ua_class)` → `ip` → **never `asn` alone**.
- `EntityKey` is a frozen dataclass whose `__post_init__` raises unless
  `entity_type ∈ {"card","ipua","ip","bin"}` and `entity_key` is a non-empty, non-whitespace
  string. `EnforcementProposal.entity: EntityKey` is **not Optional** — store-wide enforcement
  is not merely forbidden, it is unrepresentable in the type.
- **Only S/M-derived identifiers participate.** `ip` (S), `ipua_key = sha1(ip‖ua_class)` (S,
  and only the five-value `ua_class` enum, never the raw UA string), `card_hash` (M), `bin` (M).
  C-class fields — `event_id`, `user_agent`, and everything in the `client_evidence` blob —
  are structurally unreachable: `resolve_entity` takes only an `AttemptRecord`'s S/M fields as
  arguments, so a C-class value has no path into the function.
- **Schema change (the one migration):** add
  `CHECK (entity_type IN ('ip','ipua','bin','card'))` and `CHECK (length(entity_key) > 0)` to
  both `enforcement_action` and `incident_entity` in `schema.sql`. *This is what makes TRD
  §6.7's "enforced in the schema" literally true; `episode_truth.scenario` already precedents a
  repo-added CHECK the doc doesn't carry.* Because `schema.sql` uses `CREATE TABLE IF NOT
  EXISTS`, existing DBs won't pick it up — both (`tollgate.db`, `data/corpus/tollgate.db`)
  are gitignored and regenerable, so the plan rebuilds them.

### 3.6 Policy engine — `packages/detect/policy.py`

**Why:** Impl Plan Day 6's largest deliverable; Decision 57 deferred applying θ_T to the
calibrated posterior to exactly today.

```
PolicySnapshot(frozen): version, thresholds{tier→θ}, hysteresis_gap, cooldown_seconds,
    cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
    auto_ceiling, k_max_entities, control_fraction, rules_config
```

Decision assembly, in order:

1. **Ladder selection (AFA-aware).** `select_ladder(bin_is_foreign_issued) -> "domestic"|"foreign"`.
   Domestic drops `step_up` from the ladder — AFA already binds, so forcing 3DS is not an
   escalation (TRD §6.7 / Threat Model §7a). Written to `ScoreRecord.tier_ladder`, which is
   hardcoded `"domestic"` today.
2. **Threshold ladder — never re-derived by hand.** `policy_config.thresholds` is populated at
   seed time from `CostModel.tier_ladder()` (§3.8); the serving path reads the JSON column and
   the pinned version, so the live path takes **no dependency on `eval/`**.
   `tier_from_score(p, thresholds, ladder)` = the highest tier whose θ_T the posterior clears.
3. **P3 corroboration** (Threat Model §4/P3). Layer-2-driven enforcement above `monitor`
   requires evidence from **≥2 independent feature families** across **≥2 CUSUM buckets**.
   A module constant maps `FEATURE_NAMES` → `{velocity, bin_structure, amount,
   decline_composition}`; the incident tracks which families contributed non-neutral evidence
   in which bucket. Uncorroborated → capped at `monitor`. **R1–R3 floors are exempt**
   (Decision 17) and are not routed through this gate.
4. **Rule floor.** `proposed = max(layer2_tier, evaluation.minimum_tier)` — rules set a floor,
   never a ceiling (TRD §6.10).
5. **Hysteresis.** Per-entity `current_tier`. Rise to `T` requires `p ≥ θ_T`; fall below `T`
   requires `p < θ_T − hysteresis_gap`. *Decision: the specs give `hysteresis_gap = 0.08` and
   "enter at `T_enter`, exit below `T_exit < T_enter`" but never connect them; this is the
   mapping.* An oscillating score inside the band produces one tier change, not many.
6. **Auto-ceiling** (P1). `apply_auto_ceiling(proposed, snapshot.auto_ceiling)` — unchanged
   function, now with a real argument. `step_up`/`block` are **proposed**, never in force.
7. **`K_max` / advisory mode** (P2). Count of distinct entities with a live
   `enforcement_action`. At `k_max_entities` the engine enters advisory mode: it stops issuing
   **new** enforcement on **new** entities, keeps scoring, keeps entities already under
   enforcement, and raises the operator alert. *Decision: use the scalar
   `policy_config.k_max_entities` (10). Threat Model §4/P2's `max(10, 1% of distinct active
   entities in 30m)` needs an active-entity-count statistic nothing computes; recorded as
   future work, not invented here.*
8. **Control arm** (Eval Protocol §6.1). See §3.9.

**Proposed vs in-force**, written to `enforcement_action`:

| Tier | `requires_confirmation` | `confirmed_by` | `applied_at` | In force? |
|---|---|---|---|---|
| `throttle`, `challenge` | 0 | `'auto'` | `ingest_ms` | yes |
| `step_up`, `block` | 1 | **NULL** | **NULL** | **no** |

**Regime coupling** (Eval Protocol §3.3 — "the threshold moves when the prior moves"). When
the CUSUM is in alarm, `regime = "alarm"` and
`pi_s = serving_prior("alarm", state, rate_ratio=n_t/λ₀)` — the already-written, already
unit-tested, currently unwired branch of `calibrate.py:196`. `ScoreRecord.regime` and
`prior_used` become real values instead of the constant `"in_control"`.

### 3.7 `scripts/learn_store_baseline.py` — the missing baseline row

**Why:** `store_baseline` has **0 rows**. λ₀(t) needs `hourly_volume_profile` and
`flagged_rate_mean` (p̄₀); L2b needs `cards_per_ip_quantiles`. Nothing has ever written this
table, so no Day-6 detector can run without it.

Reads the **7 negative-control runs already in `data/corpus/tollgate.db`**
(`m-eval-12`…`m-eval-18`) via the existing `eval/corpus.py` seam, and writes one
`store_baseline` row per eval merchant plus one aggregated row for `merchant_demo`:
24-bin `hourly_volume_profile` from `auth_attempt.ingest_time`; `flagged_rate_mean` = share of
attempts with `score_calibrated ≥ τ_flag`; `cards_per_ip_quantiles` = `{"5m":[…],"30m":[…]}`
deciles; the NOT-NULL amount/decline/BIN columns from the same corpus (decline stats are
`0.0` with `is_stable=0` until `/v1/outcome` exists on Day 7).

**Explicit scope boundary:** the row is consumed **only by `packages/detect/`**. It is
deliberately **not** wired into `compute_features`, so `distinct_cards_per_ip_5m_q`,
`amount_percentile_vs_store` and the `*_sigma` features stay at their neutral `0.0`. Populating
them would change the model's inputs and invalidate `models/`, `models/audit.json` and every
`eval_run` row — a blast radius this day cannot absorb. Reinstating them remains Decision
16/64's deferred work.

### 3.8 `scripts/tune_cusum.py` — `h` from negative controls only

**Why:** TRD §6.5 — "`h` is tuned on **negative controls only** to hit a target ARL₀
(asserted: the tuning script never opens attack data)". `policy_config.cusum_h` is seeded as a
placeholder `5.0` today, identical to `cusum_rho`, and `policy_config.thresholds` is `{}`.

- **Target: ARL₀ ≥ 8,640 buckets** = ≤1 false alarm per merchant per 24 virtual hours at the
  10 s bucket width. *(No document states a number; this is decided today and recorded as an
  operator-facing SLO, the form the eval report can actually justify.)*
- Bisects `h` over the 7 negative-control scenarios, replaying their logged
  `score_calibrated` / `ingest_time` through `PoissonCusum` at τ_flag, until the mean run
  length to first alarm clears the target.
- Writes a **new `policy_config` version** via the existing `append_policy_config`
  (never an update — `test_policy_versioning.py` already locks this), carrying the tuned
  `cusum_h` **and** `thresholds = CostModel.tier_ladder()`.
- Returns a `TuningProvenance` naming every `merchant_id` it read. **This is the assertion
  surface** for "reads only negative-control data": the test compares that set against the
  negative-control merchant set and asserts no `episode_truth` row with `kind='attack'` was
  ever touched, backed by an AST check that the script never references the tier-block
  construction.
- Lives in `scripts/`, never `packages/detect/`, so `test_detect_label_isolation.py` stays green.

### 3.9 Control arm

**Why:** Eval Protocol §6.1 — enforcement destroys the signal that justified it; the control
arm is what makes "cards saved" an estimate rather than an assertion. `attempt_score.control_arm`
and `ix_score_control_arm` already exist; nothing sets the column.

The acceptance test says "**exactly** `control_fraction`", while §6.1 says "seeded random".
Independent Bernoulli draws satisfy the second and not the first. **Deterministic block
selection satisfies both:** for each consecutive block of `N = round(1/control_fraction) = 20`
enforcement-eligible attempts, one position is chosen pseudo-randomly from the seed —

```
block  = eligible_ordinal // N
j      = int(sha256(f"{merchant_id}:{policy_version}:{block}").hexdigest()[:16], 16) % N
control_arm = (eligible_ordinal % N == j)
```

Exactly one per block (so exactly 5% up to the trailing partial block), seeded, and bit-for-bit
reproducible across runs. `eligible_ordinal` is an in-process per-merchant counter of
enforcement-eligible attempts, cleared by `ReplayDriver.reset()`. **No new seed column** — the
seed is `merchant_id` + the pinned `policy_version`.

**Eligibility:** an attempt whose resolved tier is above `allow` and which is not already in
advisory mode. A control attempt returns the un-enforced decision, is flagged
`control_arm = true`, and **no `enforcement_action` row is written**.

> **Decision to record:** a control attempt passes unenforced *including past the R1–R3 rule
> floors*. This is in tension with Decision 17's "unconditional" floors, and is resolved in the
> control arm's favour because an attempt that is still challenged by R2 is not a control at
> all — Eval Protocol §6.1's unbiasedness claim would be false. Advisory mode likewise
> suppresses new enforcement. Both are narrow, seeded, logged carve-outs, not a weakening of
> the floors in the general case.

Day 7's outcome/HMAC work is **not** pulled forward. The only interface Day 6 leaves for it is
the already-existing `attempt_score.control_arm` column and `auth_outcome.reached_gateway` —
both shipped Day 1.

### 3.10 Integration into `score_attempt()` — the one seam

**Why:** the brief's integration requirement, and `scoring.py:123-125` already carries the
comment naming this line as the Day-6 seam.

`ScorerState` gains four guarded, `Optional` fields alongside `model`/`calibrator`:
`policy: Optional[PolicySnapshot]`, `baseline: Optional[StoreBaseline]`,
`layer2: Optional[Layer2Engine]` (owning the CUSUM + drift state), `incidents:
Optional[IncidentRegistry]`. `build_default()` loads them guarded — same shape as
`_load_model` and the Redis fallback, logged either way, never silent.

Inserted between the existing model block (line 121) and `apply_auto_ceiling` (line 125),
inside the `latency_ms` window:

```
existing: features → rules → model → Platt + prior correction
NEW:      layer2.observe(cusum_bucket_index, p_calibrated, distinct_cards_per_ip_30m_raw)
              → CusumStep + DriftStep
          incidents.step(entity, detectors, ingest_ms)   → Incident | None  (state machine)
          policy.resolve(p_calibrated, rules_eval, incident, snapshot_pinned)
              → PolicyOutcome{proposed_tier, in_force_tier, entity, control_arm,
                              tier_ladder, regime, prior_used, advisory_mode}
existing: decision = apply_auto_ceiling(...)  ← now fed by PolicyOutcome, not the rule floor alone
```

**When `state.policy is None`, the entire block is skipped and the path is byte-identical to
Day 5.** `tests/conftest.py`'s `scorer_state` and `eval/corpus.py::_replay_one` both build bare
states, so the Day-5 corpus, model, audit and `eval_run` rows are provably unaffected — the
same argument Decision 26 used for the Day-2 extraction, and the same guard Day 5 used for the
model.

`ScoreRecord` fields that stop being hardcoded: `regime`, `tier_ladder`, `control_arm`,
`incident_id`, `prior_used`, `policy_version`.

### 3.11 SSE and dashboard

**Why:** `App.jsx:134` renders `ENFORCEMENT` as a hardcoded `"— / 10"` with the caption
`"blast-radius cap · Day 6"`, and App Flow §5's D1 spec says this counter lights up today.

SSE event gains three keys (`scoring.py:199`): `incident` (`{incident_id, state, detector,
entity_type, pseudonym, proposed_tier, in_force_tier}` or `null`), `enforcement`
(`{active, k_max, advisory_mode}`), `control_arm` (bool).

**`entity_key` is never published — only `incident_entity.pseudonym`** (`ip_1`, `bin_A`). The
stream is still unauthenticated (auth is Day 7), and Decision 34's posture — publish what the
tile needs, never a raw identifier — carries forward unchanged.

`App.jsx`: the `ENFORCEMENT` tile renders `active / k_max` live, and the advisory banner
appears at the cap with UIUX §5's exact copy. `DECLINE RATE` stays `—` (Day 7). No incident
drawer, no timeline, no confirm dialog — D3 is Day 8.

---

## 4. Acceptance tests

Existing taxonomy preserved: `tests/acceptance/` = human-reviewed gates (spec-derived, written
before the code, every expectation carrying a `# Source: <doc> §<section>` comment, locked
after approval per Decision 12/13); `tests/unit/` = advisory; `tests/characterization/` =
non-gating change detectors. A `metamorphic` marker is added to `pyproject.toml`'s four
existing markers so `pytest -m metamorphic` works as Impl Plan §5 assumes.

### `tests/acceptance/` — the fourteen declared Day-6 gates

| File | Gate | Source |
|---|---|---|
| `test_cusum_analytic.py` | steps-to-alarm on a synthetic step matches `h/(λ₁ln(λ₁/λ₀)−(λ₁−λ₀))`; empty buckets decay `S_t` by **exactly** `(λ₁−λ₀)`; ARL₀ on pure noise at configured `h` clears 8,640 buckets | TRD §6.5 props 1 & 4; Impl Plan §1.1 analytic table |
| `test_cusum_tuning_isolation.py` | the `h` tuner's provenance names only negative-control merchants; no `kind='attack'` row read; AST check on the script | Impl Plan Day 6 — "asserted by fixture access" |
| `test_metamorphic.py` | **M1–M8**, driven through `ReplayDriver.run(stream=…)` over `golden.jsonl` | Impl Plan §1.4 |
| `test_episode_state_machine.py` | `CLOSED → ESCALATED` raises; re-fire in cooldown **merges** (one `incident_id`, not two); two entities hold overlapping incidents independently; an episode fed in two halves yields one incident | Impl Plan Day 6 |
| `test_policy_pinning.py` | a `policy_config` version landing mid-incident does not change the open incident's tier resolution — it resolves against `pinned_policy_version` | Backend Schema §3.1 |
| `test_hysteresis.py` | a score oscillating inside `[θ_T − 0.08, θ_T]` produces **one** tier change | TRD §6.7 |
| `test_entity_required.py` | **property test**: fuzz `ScoreRequest` (including C-class `event_id`/UA/`client_evidence`) — every emitted enforcement carries a non-empty entity key; store-wide is unreachable; no entity key ever equals a C-class value; the schema CHECK rejects a hand-crafted store-wide row | Impl Plan Day 6; TB-1; TRD §6.7 |
| `test_enforcement_confirmation.py` | `step_up`/`block` rows exist with `confirmed_by IS NULL` **and** `applied_at IS NULL`, and the returned decision is ≤ `challenge` | Threat Model §4/P1; Backend Schema §3.3 |
| `test_blast_radius.py` | at `k_max_entities` the engine enters advisory mode: no new enforcement, scoring continues, existing enforcement retained, alert raised | Threat Model §4/P2 |
| `test_control_arm.py` | exactly `control_fraction` of eligible attempts pass unenforced; two runs with the same seed select the identical attempt set | Eval Protocol §6.1; Impl Plan Day 6 |
| `test_handmade_40_incident.py` | **the exit gate** — one incident opens at the hand-counted alert seq. `xfail(strict=False)` with a named reason until the human fixture lands, mirroring `test_handmade_40.py` exactly | Impl Plan Day 6 exit; Decision 14 |

Also updated (not new): `test_cost_thresholds.py` gains an assertion that
`policy_config.thresholds` as seeded equals the analytic ladder `{0.065, 0.257, 0.509, 0.874}`
— closing the loop between the derived table and what the serving path actually reads.

**`handmade_40` fixture format — the additional human deliverable.** `test_handmade_40.py`'s
docstring already specifies the three files. Day 6 needs **one more hand-computed value**: the
alert point. The plan extends the documented format with an optional final line in
`handmade_40.expected.jsonl`:

```json
{"seq": null, "incident": {"alert_seq": 27, "detector": "cusum", "entity_type": "ip", "entity_key": "203.0.113.7"}}
```

`test_handmade_40_incident.py` reads only that line, and the existing per-seq feature test is
untouched. **Neither the events, the feature values, nor `alert_seq` may be produced by the
implementation agent** (Decision 14).

### `tests/unit/` (advisory, builder-written, never cited as a gate)

`test_cusum_recursion.py` (`S_t` arithmetic edge cases, λ_min flooring, `hour_of_day` wrap),
`test_drift_sprt.py` (Λ accumulation, one-sided clamp, threshold `A`),
`test_ladder_selection.py` (domestic drops `step_up`, foreign keeps it),
`test_entity_narrowest.py` (`card → ipua → ip`, never `asn`).

### `tests/characterization/` (non-gating)

`test_incident_shape.py` — a snapshot of the incident/entity/transition/enforcement rows the
golden fixture produces. A failure is a prompt to look, never a build gate (Impl Plan §1.2).

---

## 5. Integration sequence

Ordered so the analytic gates exist before the code they judge, and so the riskiest
integration (the `score_attempt` seam) lands with everything it needs already tested in
isolation.

| # | Step | Depends on |
|---|---|---|
| 0 | Copy this plan to `08-DAY-6-IMPLEMENTATION-PLAN.md` | — |
| 1 | Write the eleven acceptance-test files against the spec, **before any implementation**; submit for review per Decision 12 | — |
| 2 | `config/policy.yaml` + register it in `eval/provenance.py::DEFAULT_CONFIG_PATHS` | — |
| 3 | `schema.sql`: the two `CHECK` constraints; rebuild `tollgate.db` and `data/corpus/tollgate.db` | — |
| 4 | `repository.py` writers/readers + `PolicySnapshot` / `StoreBaseline` loaders; `drainer.py` new payload branches | 3 |
| 5 | `packages/detect/cusum.py` — pure module, no I/O. Green: `test_cusum_analytic.py` (steps-to-alarm, empty-bucket decay) | 2 |
| 6 | `scripts/learn_store_baseline.py` → `store_baseline` rows from the negative-control corpus | 4, 5 |
| 7 | `scripts/tune_cusum.py` → tuned `cusum_h` + derived `thresholds` as a new `policy_config` version. Green: ARL₀ gate, tuning-isolation gate | 5, 6 |
| 8 | `compute_features`: 11th window (30 m distinct-cards) + plumb `cusum_bucket_index/_count` onto `FeatureVector`. **Re-run the full suite** — `test_one_round_trip`, `test_window_differential`, `test_time_travel`, `test_model_feature_list` must all stay green | — |
| 9 | `packages/detect/drift.py`. Green: `test_drift_sprt.py` | 6, 8 |
| 10 | `packages/detect/episode.py` + `IncidentRegistry`. Green: `test_episode_state_machine.py` | 4 |
| 11 | `packages/detect/policy.py`: entity resolution, ladder, P3, hysteresis, ceiling, `K_max`, control arm. Green: pinning, hysteresis, entity-required, confirmation, blast-radius, control-arm gates | 7, 10 |
| 12 | **The seam** — `ScorerState` fields, `build_default` guarded load, the `score_attempt` block, `ScoreRecord` real values, spool payload. **Re-run the full suite**; confirm `eval/corpus.py` replay is byte-identical (rebuild the corpus and diff `attempt_score`) | 5, 9, 10, 11 |
| 13 | SSE keys + `App.jsx` `ENFORCEMENT` tile and advisory banner. Green: `test_day2_e2e.py` unmodified | 12 |
| 14 | `test_metamorphic.py` M1–M8 through the replay driver | 12 |
| 15 | Live browser check: Launch an `easy` replay, watch the band move, the ENFORCEMENT tile climb, and the cap engage; verify incident rows in SQLite | 13 |
| 16 | Update `Decisions.md` (Gate G, decisions 70+), `Flow.md` §14, `README.md`. Commit `day-6:`, tag `day-6-done` **only after** the `handmade_40` incident gate is green | 15 |

**20:00 checkpoint.** If step 12 is not green, execute the cut (§9).

---

## 6. Day 6 exit criteria

1. **One incident opens on `handmade_40.jsonl` at the hand-counted alert point** —
   `test_handmade_40_incident.py` green (gated on the human fixture; see §8).
2. All fourteen declared acceptance gates green, including M1–M8.
3. Full suite green with no edits to any locked Day-1..5 acceptance test.
4. `eval/corpus.py` rebuild produces an `attempt_score` table byte-identical to the Day-5
   corpus — the Day-5 model, audit and `eval_run` rows are provably unaffected.
5. `policy_config` carries a new version with a tuned `cusum_h` and
   `thresholds == {0.065, 0.257, 0.509, 0.874}` derived from `cost_model.yaml`.
6. The D1 `ENFORCEMENT` tile is live against `K_max`, and advisory mode renders at the cap.
7. `Decisions.md` / `Flow.md` / `README.md` updated with every decision recorded below.

---

## 7. Decisions this plan makes (to be recorded in `Decisions.md`)

| # | Decision | Why it was required |
|---|---|---|
| D1 | **τ_flag = θ_throttle** from `CostModel.tier_ladder()` (≈0.0645), never a literal | No document assigns τ_flag a value; Decision 45 deferred it to today |
| D2 | **`n_t` gating and `S_t` are maintained in-process** on `ScorerState`; the Lua counter is unchanged | `p_calibrated` does not exist when `windows.lua` step 6 runs; a second Redis write breaks the one-round-trip invariant. **Limitation: CUSUM state is per-process** |
| D3 | **ARL₀ target = 8,640 buckets** (≤1 false alarm / 24 virtual hours) | No document states a number, but the gate requires one |
| D4 | **L2b = one-sided Wald SPRT on 95th-percentile exceedance** of `distinct_cards_per_ip_30m` | TRD §6.6 gives the shape but not the statistic, quantile or threshold |
| D5 | **`cards_per_ip_quantiles` carries `{"5m":…, "30m":…}`** | §6.6 needs a 30 m baseline; the schema comment names only "deciles". Table has 0 rows, so no compatibility cost |
| D6 | **The 30 m distinct-card window is an 11th `WindowRequest` in the same `score_path()` call**, surfaced on `FeatureVector`, not `FEATURE_NAMES` | No second feature path (TRD §6.4); one round trip preserved; model contract untouched |
| D7 | **`hysteresis_gap` maps to `T_exit = T_enter − 0.08`** | TRD §6.7 gives both halves and never connects them |
| D8 | **`K_max` = the scalar `k_max_entities` (10)**; P2's `max(10, 1% of active entities in 30m)` is future work | The 1 % form needs an active-entity statistic nothing computes |
| D9 | **Control arm = deterministic one-per-block-of-20 selection**, seeded on `merchant_id`+`policy_version` | "exactly `control_fraction`" and "seeded random" are jointly satisfiable only by block selection |
| D10 | **Control-arm and advisory-mode attempts pass unenforced past the R1–R3 floors** | Decision 17 says floors are unconditional; an enforced "control" is not a control (Eval Protocol §6.1). Narrow, seeded, logged carve-out |
| D11 | **`store_baseline` feeds `packages/detect/` only, never `compute_features`** | Populating `_q`/`*_sigma` would invalidate `models/`, `audit.json` and every `eval_run` row |
| D12 | **`ThreatRollup` is retained as the no-policy fallback**; incident state drives `threat_state` when Layer 2 is live | Keeps `test_day2_e2e.py`, `App.jsx` and the Day-5 corpus replay unchanged |
| D13 | **Two `CHECK` constraints added to `schema.sql`** on `entity_type`/`entity_key` | TRD §6.7: "enforced in the schema, not just in code" — code-only was not enough |

---

## 8. Risks / unresolved

1. **`handmade_40` is a hard human dependency.** The exit criterion cannot be met by any
   amount of implementation work. Per your ruling, Day 6 ships and is tagged only after you
   supply the three files plus the `alert_seq` line (§4). Roughly one hour of paper work; it
   is the only oracle in the system that does not descend from code an agent wrote.
2. **The `hard` tier may still be undetected even with L2b.** The Day-5 model runs on four
   live features after the audit exclusions and is weaker than B0 except on `hard`. If neither
   detector fires on `hard`, that is reported honestly rather than tuned around.
3. **AFA-aware ladder selection cannot be exercised on live data.** `bin_metadata` has 0 rows
   and `bin_is_foreign_issued` is `0.0` for every event, so `tier_ladder` stays `"domestic"` in
   practice. `select_ladder` is tested as a pure function against a synthetic foreign BIN.
   Loading `bin_metadata` is deliberately **not** attempted: it would trip
   `test_nri_control_tripwire.py`, which fails the moment `bin_is_foreign_issued` becomes
   non-zero while attack-side foreign share stays zero. Left as Day-7 work.
4. **P3's "≥2 CUSUM buckets" is unauditable from the DB.** Nothing on `incident`,
   `tier_transition` or `enforcement_action` records which feature families corroborated
   across how many buckets. The engine enforces it in memory; the plan does **not** add a
   column for it. Flagged as a schema gap, not silently ignored.
5. **In-process CUSUM/incident state does not survive restart** and would diverge across
   multiple Uvicorn workers. Acceptable for a single-worker demo (the same posture as
   `ThreatRollup` and `InProcessEventBus`); Redis-backed `tg:{m}:cusum` / `tg:{m}:enforce:*`
   is deferred.
6. **Adding `config/policy.yaml` changes every `config_hash` value.** `test_config_hash.py` is
   fully relative and asserts nothing absolute, but every stored `eval_run.config_hash`
   becomes historical. Expected and stated, not a regression.
7. **Rebuilding `data/corpus/tollgate.db` for the schema CHECK** re-runs a ~10k-attempt replay
   (minutes, not hours) and must reproduce byte-identical `attempt_score` rows. If it does not,
   step 12 has introduced a behaviour change and must be diagnosed before proceeding.

---

## 9. Explicitly out of scope for Day 6

- **`/v1/outcome`, HMAC, nonce, idempotency hardening, stream auth, shed mode, Tier E** — Day 7.
- **`POST /v1/incidents/{id}/action`, the D3 incident detail screen, the operator confirm
  dialog, design tokens, the Gemini narrator** — Day 8. Day 6 produces the proposed-but-
  unconfirmed `enforcement_action` rows those screens will act on; App Flow §4's v2.1 note
  states the confirmation UI is a later day.
- **`bin_metadata` load / real AFA ladder selection** — risk 3.
- **Populating `_q`, `amount_percentile_vs_store`, `*_sigma` model features** — D11.
- **Report Block 1 Layer-2 harm metrics and Block 4's currency headline.** Day 6 **populates**
  `incident.cards_exposed_before_alert` / `attempts_before_alert` / `time_to_detect_s` /
  `cusum_stat_at_alert` — the columns it owns — but rendering them into `eval/report.py` is
  left to Day 8/9 so the 9-hour budget holds. Blocks 1 and 4 keep their honest "deferred"
  text until then.
- **Redis-backed CUSUM/enforcement state, `narrator_call` wiring, cross-merchant anything.**

---

## 10. Cut / fallback if the day overruns

**Trigger: step 12 not green by 20:00 → cut L2b.** *Source: Impl Plan §4 cut ladder,
"Day 6, 20:00 | One incident on `handmade_40` at the hand-counted point | L2b drift → hard
tier reported as undetected".*

The cut is deliberately a **config-level switch, not a code excision**: set
`config/policy.yaml: drift.enabled = false`, skip `test_drift_sprt.py` and the drift half of
`test_metamorphic.py`, and leave `drift.py` and the 11th window in place (both are inert when
disabled, and the window costs nothing since it rides in the existing round trip).

What survives the cut: L2a, the episode state machine, entity resolution, the policy engine,
`K_max`, hysteresis, the control arm, and the `handmade_40` incident gate — i.e. everything the
brief names as "the core incident/policy path".

**The honest statement that ships with it**, in `README.md` and `Decisions.md`:

> Layer 2b (distinct-card sequential drift) was cut on Day 6. Layer 2a's 10-second Poisson
> CUSUM is the wrong instrument for the `hard` tier's ~20 attempts/hour — the bucket is empty
> the overwhelming majority of the time — so **the `hard` tier is reported as undetected by
> Layer 2**, not as detected by a weaker mechanism. `easy` and `medium` are detected by L2a.
> The R1–R3 rule floors remain active on every tier.

Never cut, under any circumstance (Impl Plan §4): the `challenge` auto-ceiling, the
negative-control suite, and the entity-key requirement.
