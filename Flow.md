# Tollgate — Day 1 Walking Skeleton: Actual Execution Flow

This documents what the code actually does, using real names, as of the Day 1
implementation. Not a generic architecture description — see `07-IMPLEMENTATION-PLAN-v2.md`
for that. Update this file whenever the execution path changes.

---

## 1. POST /v1/score — the scoring path

Source: Day-2 Plan §L Step 6 / Decisions.md decision 26. Steps 5-11 (below) moved into
`services/scorer/scoring.py::score_attempt()` on Day 2 -- a pure extraction, no behaviour
change (the 55 Day-1 tests are unedited proof). The route now does only auth + IP + Stopwatch
and delegates. `services/scorer/replay.py::ReplayDriver` (§7 below) calls the same
`score_attempt()` with its own `VirtualClock` and a seed-derived `UlidGenerator` instead of
`state.clock`/`state.ulid` -- this is the seam that makes replay and the storefront run
byte-identical logic.

```
Browser / curl                              services/scorer/replay.py::ReplayDriver (§7)
  │                                                     │
  ▼                                                     │ clock=VirtualClock, ulid=seeded
POST /v1/score  (services/scorer/routes_score.py:score) │
  │                                                     │
  ├─ 1. Stopwatch() started                                packages/clock/stopwatch.py
  │
  ├─ 2. FastAPI validates the body against
  │     ScoreRequest                                       packages/contracts/wire.py
  │     -- extra="ignore": a body-supplied `ip` field is silently dropped here,
  │        never reaching application code (Threat Model v2 §2 / finding K8)
  │
  ├─ 3. resolve_merchant_id(conn, x_tollgate_key)           services/scorer/auth.py
  │     -- SHA-256(raw_key) looked up against merchant.api_key_hash
  │     -- None -> HTTPException(401)
  │
  ├─ 3b. [Day 7] resolve_merchant_id_cached(state, x_tollgate_key)  services/scorer/auth.py
  │     -- warm {api_key_hash -> merchant_id} cache on ScorerState; a locked
  │        auth DB with a WARM cache still authenticates. AuthBackendUnavailable
  │        (cold cache + unavailable DB) -> HTTPException(503) -- auth NEVER
  │        fails open (Decision 89).
  │
  ├─ 4. resolve_client_ip(request)                          services/scorer/net.py
  │     -- request.client.host, or X-Forwarded-For if the peer is a
  │        configured trusted edge (TRUSTED_EDGE_HOSTS)
  │
  ├─ 4a. [Day 7] admission -- state.admission.try_consume(merchant_id, now_ms)  services/scorer/admission.py
  │     -- one lazy-refill TokenBucket per merchant (injected clock). If empty:
  │        state.window_store.shed_incr(merchant_id, ip, now_ms, shed_ttl_ms)
  │        -> tg:{m}:shed:{ip} (MERCHANT_SCOPED_KEY_RE, 60 s TTL)
  │        -> tier = THROTTLE if n >= R1 threshold else ALLOW   (R1 ONLY, Decision 15)
  │        -> X-Tollgate-Shed: 1 header; spool a shed=True ScoreRecord with a
  │           zero-filled feature_snapshot (degraded_reason "shed"); RETURN.
  │           compute_features / model / Layer 2 are NEVER reached.
  │
  ├─ 4b. [Day 7] score_attempt(...) is wrapped in try/except Exception (fail-open).
  │     On ANY fault: state.availability.record_fail_open(merchant_id, now_ms, reason);
  │     spool an `allow` ScoreRecord (degraded_reason "fail_open:{window_store|model}");
  │     publish an SSE event with availability.alert; RETURN Decision.ALLOW.
  │     The response is ALWAYS `allow` (Decision 89); the budget governs alerting,
  │     not the tier. Redis has socket_timeout/socket_connect_timeout=150 ms so a
  │     dead socket raises promptly (asyncio.wait_for cannot bound a sync call).
  │                                                          ▼
  │                    services/scorer/scoring.py::score_attempt(state, merchant_id, ip, body,
  │                                                              clock=None, ulid=None, ...)
  ├─ 5. (clock or state.clock).now_ms()                     packages/clock/clock.py
  │     (ulid or state.ulid).new()                          packages/clock/ids.py (UlidGenerator)
  │     -- attempt_uid minted from the clock, not wall time
  │
  ├─ 6. [Day 3] classify_ua(user_agent) -> ua_class; ipua_key(ip, ua_class)  packages/features/compute.py
  │     compute_features(state.window_store, FeatureContext(...))
  │       -> ONE store.score_path(ScorePathRequest) call                    TRD §6.3, one round trip
  │          -- InMemoryWindowStore.score_path() or RedisWindowStore.score_path()
  │             (EVALSHA windows.lua): SET NX idem -> ZADD every window ->
  │             ZREMRANGEBYSCORE trim -> ZCARD/ZRANGE read -> eidr SADD ->
  │             card24 INCR -> CUSUM bucket HINCRBY, all in one call
  │       -> FeatureVector (24 canonical features + trusted/degraded_reason + idem_digest)
  │     [Day 7] if features.idempotent_replay AND state.decision_cache has idem_digest:
  │       -> return ScoreResponse(stored attempt_uid, stored decision) WITHOUT a spool
  │          append or an SSE publish -- 39 of 40 concurrent identical submissions get
  │          the SET-NX winner's decision replayed, one row, one increment (Decision 86).
  │     DayOneRules.evaluate_from_features(features)          packages/detect/rules.py
  │       -- reads R1/R2/R3's three statistics from the vector already fetched above
  │          (the locked evaluate()/record_and_read() path is untouched and still used
  │          directly by tests/acceptance/test_rules.py and test_rules_geometry.py)
  │     -> RulesEvaluation(results=(R1, R2, R3))
  │        .minimum_tier  (Decision.ALLOW if none fired, else the max fired tier)
  │        .fired_names, .feature_snapshot, .rule_score()
  │     feature_snapshot = features.snapshot() merged with evaluation.feature_snapshot
  │        -- 24 canonical keys + trusted/baseline_coverage, plus the Day-1/2 raw
  │           rule-level keys (distinct_cards_per_ip_5m etc.) the dashboard already reads
  │
  ├─ 7. apply_auto_ceiling(evaluation.minimum_tier)          packages/detect/policy.py
  │     -- clamps to Decision.CHALLENGE if a rule ever floors above it
  │        (never triggers today: R1-R3 floor at throttle/challenge only)
  │
  ├─ 8. stopwatch.elapsed_ms() -> latency_ms
  │
  ├─ 9. Build AttemptRecord + ScoreRecord                    packages/contracts/records.py
  │     -- compute_payload_digest(body): sha256 over the M-class fields
  │     -- model_version="rules-only-v0", calibrator_version="identity",
  │        tier_ladder="domestic" (no BIN metadata join on Day 1),
  │        prior_used=state.prior_steady_state, regime="in_control"
  │
  ├─ 10. state.spool.append(attempt_uid, {...})              packages/storage/spool.py (Spool)
  │      -- json line written + flush()'d to spool/attempts-active.jsonl
  │         BEFORE the response is constructed -- this is what makes the
  │         200 response's durability guarantee true
  │
  ├─ 11. state.threat.observe(rules_fired, decision, ingest_ms) packages/detect/threat_state.py
  │      -> threat_state ("calm"|"elevated"|"under_attack"|"resolved")     [Day 2, §7/§9]
  │      await state.event_bus.publish({...})                packages/storage/bus.py
  │      -- extended payload, see §3 below -- delivered to every subscriber's asyncio.Queue
  │
  └─ 12. return ScoreResponse(attempt_uid, decision, latency_ms)
         -- wire body carries `decision` only (decisions.md, decision 18)
```

## 2. Background drainer — spool to SQLite

```
Drainer.start()  (packages/storage/drainer.py)
  -- daemon thread, _run() loop, poll_interval_s=0.05
  │
  └─ Drainer.drain_once()
       │
       ├─ opens spool/attempts-active.jsonl, seeks to self._offset
       ├─ reads complete lines only (stops at a torn/partial final line)
       ├─ for each line:
       │    AttemptRecord(**payload["attempt"])
       │    ScoreRecord(**payload["score"])
       │    insert_attempt(conn, attempt)   packages/storage/repository.py
       │    insert_score(conn, score)      packages/storage/repository.py
       │    -- both use INSERT OR IGNORE keyed on attempt_uid (idempotent)
       └─ conn.commit()  -- one transaction per batch
```

On service startup (`services/scorer/app.py`'s `lifespan`):
`drainer.drain_from_start()` resets `self._offset = 0` and drains the whole
spool file before `yield` (i.e. before the app accepts traffic), so a crash
that lost the in-memory offset still recovers everything acknowledged.

## 3. GET /v1/stream — SSE

```
Browser: new EventSource("/v1/stream")   services/dashboard/src/App.jsx
  │
  ▼
GET /v1/stream  (services/scorer/routes_stream.py:stream)
  │
  └─ state.event_bus.subscribe()          packages/storage/bus.py
       -- registers an asyncio.Queue, yields "data: {json}\n\n" per event
          forever, until the client disconnects
```

**Day-2 payload (decisions.md decision 34).** Day 1 shipped five keys:
`attempt_uid, decision, ip, bin, ingest_time`. Day 2 adds five more, all built in
`services/scorer/scoring.py`: `rules_fired` (list of fired rule names),
`feature_snapshot` (raw per-rule counts -- disclosed on this unauthenticated
stream; accepted for the loopback-bound demo, stream auth is Day 7),
`threat_state` (`packages/detect/threat_state.py`'s rollup output: `"calm"` |
`"elevated"` | `"under_attack"` | `"resolved"`), `regime` (constant
`"in_control"`), and `replay` (a mirror of `ReplayStatus.to_dict()`, or an
idle placeholder when no replay driver is attached). `card_hash` is never
published (Threat Model v2 addendum, decision 34). The dashboard renders
`threat_state` verbatim -- it is never re-derived client-side.

## 4. Startup / shutdown

```
create_app(state=None)                   services/scorer/app.py
  │
  ├─ lifespan(app) [asynccontextmanager]
  │    on enter:
  │      active_state = state or ScorerState.build_default()   services/scorer/deps.py
  │      app.state.scorer = active_state
  │      active_state.drainer.drain_from_start()
  │      active_state.drainer.start()
  │    on exit:
  │      active_state.drainer.stop()
  │      active_state.spool.close()
  │
  ├─ CORSMiddleware(allow_origins=[":5173", ":5174"])
  ├─ include_router(routes_score.router)
  ├─ include_router(routes_stream.router)
  └─ GET /healthz -> {"status": "ok"}
```

## 5. Browser checkout -> dashboard ticker (the Day 1 exit criterion)

```
services/storefront (Vite, :5173)          services/dashboard (Vite, :5174)
  │                                             │
  │  App.jsx: <button onClick={submitCheckout}>  App.jsx: useEffect ->
  │  fetch("/v1/score", {...})                   new EventSource("/v1/stream")
  │       │                                            │
  │       ▼ (Vite proxy: /v1 -> :8080)                 ▼ (Vite proxy: /v1 -> :8080)
  │  services/scorer/app.py (see section 1)      services/scorer/routes_stream.py
  │       │                                            ▲
  │       └────────── event_bus.publish() ─────────────┘
  │
  └─ setResult(body)  -- JSON pretty-printed        setEvents(prev => [data, ...prev])
     under the Pay button                            -- new <li> row appears at the top
```

Verified manually (2026-08-23): `curl` against `/v1/score` produced a decision;
the row appeared in both `auth_attempt` and `attempt_score` (confirmed via
direct SQLite query); a checkout posted through the storefront's Vite proxy
(`:5173`) and an SSE listener through the dashboard's Vite proxy (`:5174`)
were driven programmatically end-to-end and the SSE event's `attempt_uid`
matched the posted attempt exactly. Both dev servers were confirmed serving
real pages (`curl` against `:5173/` and `:5174/` returned the Vite-injected
HTML shell). Literal visual confirmation in an actual browser window was not
performed in this session (no browser automation tool is available here) —
the user should open `http://localhost:5173` and `http://localhost:5174` to
see the rendered pages directly; the underlying request path is identical to
what was already verified.

## 7. POST /v1/replay/start — the virtual-clock replay driver

Source: Day-2 Plan §G / decisions.md decisions 25-27.

```
DC strip: Launch button   services/dashboard/src/App.jsx
  │  fetch("/v1/replay/start", {tier, seed, speed, epoch_ms})
  ▼ (Vite proxy: /v1 -> :8080)
POST /v1/replay/start  (services/scorer/routes_replay.py:replay_start)
  │
  ├─ resolve_merchant_id(conn, x_tollgate_key)   -- same auth as /v1/score;
  │     the loop below never re-authenticates per event
  ├─ 409 if state.replay_driver.status.state == "running"
  ├─ driver.mark_starting(request)     -- synchronous, closes the
  │     asyncio.create_task() scheduling race against a second rapid /start
  └─ state.replay_task = asyncio.create_task(driver.run(request))
       -- returns 202 immediately; the loop below runs concurrently

ReplayDriver.run(request, stream=None)   services/scorer/replay.py
  │
  ├─ epoch_ms = request.epoch_ms or state.clock.now_ms()
  ├─ self._clock = VirtualClock(epoch_ms)                packages/clock/clock.py
  ├─ ulid = UlidGenerator(clock=self._clock,
  │           rng=random.Random(f"ulid:{request.seed}"))  -- deterministic attempt_uid
  ├─ stream = stream or packages.simulator.generate.build_stream(seed, tier, hours)  [§8]
  │
  └─ for ev in stream:
       ├─ if stop requested: status="stopped", return
       ├─ self._clock.set_ms(epoch_ms + ev.t_ms)   -- virtual time IS event time;
       │     never advance_ms(wall_delta) -- this is what A14 asserts
       ├─ await score_attempt(state, merchant_id, ip=ev.ip,
       │       body=ScoreRequest(**ev.to_score_request()),
       │       clock=self._clock, ulid=ulid)              [§1]
       ├─ if request.speed: await asyncio.sleep((ev.t_ms - prev) / 1000 / speed)
       │     -- the ONLY wall-clock call in the loop; affects nothing the
       │        scorer reads (speed=0 vs speed=60 produce identical
       │        decision sequences -- A13)
       └─ self._status updated (sent/total/virtual_time_ms) every iteration
```

`POST /v1/replay/stop` sets a cooperative flag the loop checks each iteration.
`POST /v1/replay/reset` clears `state.window_store` (`InMemoryWindowStore.clear()`,
new on Day 2) and `state.threat` (`ThreatRollup.clear()`) -- required, not
convenient: without it a second `Launch` in the same process inherits stale
window/threat state (decisions.md decision 36). `GET /v1/replay/status`
returns the same `ReplayStatus.to_dict()` mirrored onto every SSE event's
`replay` key. The scorer's `lifespan` (`services/scorer/app.py`) cancels any
running replay task on shutdown.

## 8. `python -m packages.simulator.generate` — the generation path

Source: Day-2 Plan §F / decisions.md decisions 28-32.

```
generate.py:build_stream(seed, tier, hours, epoch_ms)   packages/simulator/generate.py
  │
  ├─ load_store_profile() / load_attack_tiers()          packages/simulator/profile.py
  │     -- config/store_profile.yaml, config/attack_tiers.yaml (yaml.safe_load)
  ├─ load_baseline_profile()                              packages/simulator/profile.py
  │     -- data/baseline/online_retail_ii.profile.json, SHA-256-verified
  │        against the committed .sha256 sidecar before use
  │
  ├─ generate_attack_episode(seed, tier, tier_config,      packages/simulator/attack.py
  │     episode_start_ms=hours*3.6M/3, baseline_profile, aov_minor, currency)
  │     -- SubStream(seed, f"attack:{tier}:*")  (rng.py, getrandbits-only)
  │     -- amounts: same empirical quantile table as baseline, restricted to
  │        amount_quantile_band's low-index range (Eval Protocol v2 §4/V2)
  │     -> attack_items: list[RawItem], episode_id, ended_at_ms
  │
  ├─ generate_baseline_events(seed, hours, store_profile,  packages/simulator/baseline.py
  │     baseline_profile, episode_windows=[(episode_start_ms,
  │     episode_start_ms + 60_000)])   -- fixed 60s guarantee window,
  │     independent of the attack tier's own duration (decision 31: this
  │     is what keeps A4 and A7 both satisfiable at once)
  │     -- SubStream(seed, "baseline:*")  -- never parameterized by tier
  │     -> baseline_items: list[RawItem]
  │
  └─ merge_and_number(baseline_items, attack_items)        packages/simulator/stream.py
       -- stable sort by t_ms; event_id/seq assigned from MERGED position only
          (never a per-source counter -- anti-leakage checklist)
       -> events: list[Event], labels: list[Label]
       -> episodes: list[Episode]  (attempt_count/distinct_cards recounted
          from the labels that reference this episode_id)

CLI (__main__): writes events/labels/episodes to --out/--labels/--episodes
as canonical JSONL (sort_keys, no spaces, ASCII, LF-only) via
packages/simulator/stream.py::canonical_line()/write_jsonl().
```

Safety (decisions.md decision 28, `tests/acceptance/test_simulator_safety.py`,
`-m safety`): `packages/simulator`'s transitive import closure never reaches
`socket/ssl/http/urllib/requests/httpx/asyncio/subprocess/ftplib/smtplib/ctypes`;
no PAN-shaped identifiers; a full generation run succeeds with `socket.socket`
monkeypatched to raise. `scripts/distill_baseline.py` (pandas/openpyxl) lives
outside `packages/simulator` specifically so this closure never has a reason
to include it.

## 9. Demo launch: Launch button → threat band

Source: Day-2 Plan §M exit gate -- the Day-2 equivalent of §5's Day-1 walkthrough.
Verified in a live browser session (not just the automated A16 test) on
2026-08-24: pressed Launch (tier=easy, speed=60) against the real dev stack
(`:8080`/`:5173`/`:5174`); the D1 threat band moved `CALM -> UNDER ATTACK` on
screen, `ATTEMPTS · 5 MIN` and `CARDS PER IP · TOP` climbed live, and the
ticker showed real `challenge` decisions with `rules_fired: attempts_per_ip_60s,
distinct_cards_per_ip_5m, distinct_cards_per_bin_5m` -- all driven purely by
the SSE stream, confirming the band is never derived client-side.

```
services/dashboard (DC strip)                services/scorer
  │  POST /v1/replay/start {tier:"easy",           │
  │    seed:42, speed:60, epoch_ms:0}               │
  ▼ (Vite proxy)                                    ▼
  202 + ReplayStatus{state:"running",...}    ReplayDriver.run() [§7] starts
  │                                                  │  in a background asyncio.Task
  │                                          for each ev: score_attempt() [§1]
  │                                                  │  -> spool -> Drainer -> SQLite
  │                                                  │  -> event_bus.publish() [§3]
  │  EventSource("/v1/stream")                       ▼
  ◄──────────────────────────────────── {..., threat_state, rules_fired, replay}
  │
  ├─ ThreatIcon + label render event.threat_state verbatim -- CALM (hollow
  │    ring, grey) while the episode has not yet tripped a rule, then
  │    ELEVATED (R1/throttle) or UNDER_ATTACK (R2/R3/challenge) as the
  │    replay's attack episode fires real rule evaluations
  ├─ ATTEMPTS · 5 MIN: count of buffered SSE events within 5 minutes of the
  │    latest event's own ingest_time (event time, not wall time -- reads
  │    correctly under 60x compression)
  ├─ CARDS PER IP · TOP: max(feature_snapshot.distinct_cards_per_ip_5m) over
  │    the buffered events
  └─ DECLINE RATE / ENFORCEMENT: fixed "—" placeholders (Day 7 / Day 6)
```

`sqlite3 tollgate.db "select decision, count(*) from attempt_score group by
1"` shows the same non-`allow` decisions after the drainer catches up
(verified via `test_day2_e2e.py`'s post-drain SQLite assertion).

## 11. [Day 3] The real feature path -- `compute_features()` and the Lua script

Source: Day-3 Plan / TRD §6.3-§6.4, §6.11. `packages/features/compute.py::compute_features()`
is now **the** feature definition (TRD §6.4), called from step 6 above. It issues exactly one
`WindowStore.score_path(ScorePathRequest)` call, positionally building a `WindowRequest` per
window it needs (10 on Day 3: `ip`/`ipua`/`bin`/`session` spaces across 60s/5m/30m widths),
then assembles all 24 `FEATURE_NAMES` from the single returned `ScorePathSnapshot`. Un-fed
slots (no `store_baseline` until Day 4, no `/v1/outcome` until Day 7, no client `ts`) emit
`0.0` plus an explicit coverage field rather than NaN or None (Decisions.md decision 43).

```
RedisWindowStore.score_path()                    packages/features/redis_store.py
  -- EVALSHA windows.lua (SCRIPT LOAD once, at construction -- Decisions.md decision
     covers the one-round-trip invariant; tests/acceptance/test_one_round_trip.py)
  -- KEYS: idem, eidr, card24, cusum, one sorted-set key per window
     (window_key() now includes window_ms -- Decisions.md decision 40)
  -- idem key = sha256(merchant_id || event_id || payload_digest), NOT payload_digest
     alone (Decisions.md decision 41 -- a real bug found and fixed via the locked
     Day-1 R1 acceptance test)
  -- a background thread on its OWN connection polls INFO stats:evicted_keys and
     latches trusted=False, degraded_reason="redis_eviction" on any rise, distinct
     from ordinary TTL expiry (Decisions.md decision 44)

InMemoryWindowStore.score_path()                 packages/features/memory_store.py
  -- identical semantics, single-process, always trusted=True; the pre-committed
     20:00 fallback, verified by the same differential test as Redis
```

`ScorerState.build_default()` (`services/scorer/deps.py`) selects `RedisWindowStore` when
`TOLLGATE_REDIS_URL` is set and reachable, else `InMemoryWindowStore` -- logged either way,
never silent.

`packages/narrator/template.py::render(EvidenceBundle)` renders `{"narrative",
"confidence_note"}` from closed-vocabulary, pseudonymised evidence only (Threat Model §5);
not yet wired into `score_attempt()` -- Day 3 scope is "a narrative renders" (verified by its
own test), full incident-pipeline wiring is Day 6.

---

## 12. [Day 4] The evaluation harness -- generation -> dataset -> split -> score -> metric -> report

Source: Day-4 Plan (rev. 2). `eval/` is a new top-level package (repo root, not inside
`packages/simulator` -- Decisions.md decision 52), invoked as `python -m eval.harness --split
all --seed 42 [--seeds N] [--out eval/outputs/]`. It never touches the live scoring path
(`services/scorer/*`, `packages/detect/rules.py`, `packages/features/compute.py` are all
unmodified) -- it drives the SAME `WindowStore` protocol the online path uses, offline, over
simulator-generated streams.

```
eval.harness.main()
  -- for each seed in [seed, seed+1, ..., seed+seeds-1]:
       run_all(seed)
         build_full_dataset(seed)                         eval/harness.py
           -- 4 sequentially-epoched blocks x {easy, medium, hard}   packages/simulator/generate.py
              (build_stream, seed+block_i, distinct epoch_ms per block --
              ONE build_stream() call has exactly one attack episode, so multiple
              blocks are unioned to spread episodes across a longer timeline;
              Decisions.md decision 54)
           -- + one run per negative-control scenario                packages/simulator/negative.py
              (build_negative_stream, all 7: flash_sale, corporate_nat, cgnat,
              retry_storm, subscription_batch, nri_traffic, shared_ip_legit)
           -> build_dataset(runs) -> list[Sample]                     eval/dataset.py
              (stamps stream_tier from the run label, episode_tier/kind/scenario
              from the joined Episode, outcome_visible_ms = t_ms + 340ms)
           -> compute_entity_overlap(samples)                         eval/dataset.py
              (ip/card_hash only, NOT bin -- test 16 measures why; window =
              [min(attack t_ms), max(attack t_ms) + 30min], derived from the
              samples' own is_attack=True timestamps, no second parameter)

         temporal_split(samples, 0.7) -> purge + embargo (30min)      eval/dataset.py
         attack_shape_holdout(samples) -> train={easy,medium}, test=hard
         exclude_negative_controls(train side only)                  -- F13 fix
         negative_control_splits(samples) -> 7 per-scenario Splits    -- deliberately single-class

         for each eval split x each of the 4 B3 sanity scorers:       eval/scorers.py
             (PerfectScorer, RandomScorer(seed), InvertedScorer, AlwaysPositiveScorer)
           evaluate(split, scorer, cost_model, provenance) -> Report  eval/harness.py
             -- recall_at_fpr (Wilson CI + resolvability)             eval/metrics.py
             -- average_precision / ap_at_prevalence (per-item rank formula,
                NOT tie-collapsed -- Decisions.md decision 56)
             -- roc_auc (Mann-Whitney, average-rank ties)
             -- cost_over_operating_points + roc_convex_hull -> min_cost   eval/cost.py
             -- per-tier + clean-subset (clean_view) breakdowns
           Report.__post_init__() -> RunProvenance.validate()          eval/provenance.py
             (config_hash recomputed and compared; model_version vocabulary;
             policy_version against a Day-4 placeholder (1,) -- no live
             merchant DB dependency yet, Decisions.md decision 62)

         B1 (decline-velocity) / B2 (BIN-concentration)                eval/baselines.py
           -- BOTH drive WindowStore.record_and_read() directly -- zero bespoke
              windowing code (F3). B2's request is byte-identical to
              compute.py:203's distinct_cards_per_bin_5m window.
           -- B1 processes one MERGED chronological timeline (score events at
              t_ms, decline-visibility events at t_ms+340ms) so a decline is
              never visible before its own outcome_visible_ms (Decisions.md
              decision 59)

  eval.report.render(runs) -> eval/outputs/report.md                  eval/report.py
    Block 1: per-tier recall@FPR + PR-AUC, per sanity scorer (Layer-2 harm
             metrics named as a Day-6 gap)
    Block 2: negative controls -- episode/attempt FP counts at theta_challenge
             =0.257, per scenario, per scorer (nri_traffic marked inert)
    Block 3: discriminability audit -- deferred to Day 5 (needs feature_snapshot)
    Block 4: cost over achievable (FPR,TPR) + hull minimum at pi0/pi1 -- no
             theta-indexed curve, no Rs gap (needs a calibrator, Day 6)
    Block 5: calibration -- "not yet measured (Day 5)", explicit empty block
    Block 6: B1/B2 native operating points; B0 marked Day 5 (never recomputed
             offline -- would credit the live detector with information it
             never had, Eval Protocol §8)
```

`eval/load.py::load_truth(conn, merchant_id, runs)` writes `episode_truth` (unconditional,
idempotent via `INSERT ... ON CONFLICT(episode_id) DO UPDATE`) and `attempt_label` (only for
events with an existing `auth_attempt` row, i.e. already replayed -- Decision 32; skips
counted) -- implemented and independently tested
(`tests/acceptance/test_load_truth.py`), but **not called by `eval.harness.main()`**: Day 4 has
no live replay/merchant flow to load against yet (Decisions.md decision 62). Wiring it into a
real replay is Day 5's job.

**Deferred past Day 4** (see §10 below for the full list): the discriminability audit RUN
(statistic ships, Day 5), calibration (Day 5), B0 recomputed offline (never -- by design),
Layer-2 harm metrics / incident-based reporting (Day 6), a theta-indexed cost curve (Day 6),
`nri_traffic`'s actual discriminating power (Day 5, tracked by a tripwire test), `evasive` tier
(Day 7).

---

## 13. [Day 5] Layer 1 -- corpus -> audit -> model -> calibrator -> eval_run

Source: Day-5 Plan. Day 5 turns the Day-4 evaluation scaffold into a real detector without
changing the decision rule: **score yes, decide no.**

```
python -m scripts.train_l1 --seed 42 --db data/corpus/tollgate.db --out models/ [--rebuild-corpus]
  eval.corpus.build_runs(42)                                 eval/corpus.py  (seam S1)
    -- THE single construction: the 12 sequentially-epoched tier blocks + 7
       negative-control scenarios that eval/harness.build_full_dataset now
       DELEGATES to. Each run carries identity: run_index, merchant_id
       "m-eval-NN", stream_tier|scenario, epoch_ms.
  eval.corpus.replay_corpus(runs, db_path, spool_dir)        eval/corpus.py  (seam S2)
    -- per run, in run order:
         seed merchant + policy_config v1 for m-eval-NN
         fresh ScorerState (fresh InMemoryWindowStore; Redis MUST be off)
         ReplayDriver(state, merchant_id).run(ReplayRequest(speed=0, epoch_ms=0),
             stream=run.output.events)  -- the EXISTING injected-stream seam;
             negative controls replay through the identical score_attempt path
         spool.close(); Drainer.drain_from_start()  -> auth_attempt + attempt_score
         eval.load.load_truth(conn, m-eval-NN, [(tier, output)])  -> episode_truth + attempt_label
    -- one merchant per run fixes colliding event_ids (stream.py restarts at
       e-0000000/run), overlapping negative-control timelines (no epoch_ms),
       and per-run window isolation. ~10,122 attempts, 10,122 labels.
  eval.corpus.load_feature_corpus(conn)                      eval/corpus.py  (seam S4)
    -- auth_attempt JOIN attempt_score; json.loads(feature_snapshot) projected
       by FEATURE_NAMES (the stored dict has 27 keys) with float() coercion,
       raises on a missing key. Keyed (run_index, event_id) -> FeatureRow(x[24],
       rule_score_raw = score_raw at decision time = B0).

  samples = compute_entity_overlap(build_dataset(runs))       Sample.run_index (seam S3)
  temporal_split(samples, 0.7) -> exclude_negative_controls -> stream_tier in {easy,medium}
  three_way_temporal_slice(train): fit 70% / earlystop 15% / calib 15%, 30-min embargo

  discriminability audit (Eval Protocol §4/V2)               scripts/train_l1.py::run_audit
    -- univariate_auc(column_j, labels) over ALL 24 on the training set;
       writes models/audit.json; EXITS NON-ZERO if a feature over
       max_univariate_auc=0.95 is not already in config/features.yaml:audit.excluded.
       Six features are excluded (Decision 64); 14 read constant 0.5 (Decision 43).

  train_lgbm(fit, earlystop)                                 scripts/train_l1.py
    -- objective=binary, num_boost_round=200, max_depth=6, num_threads=1,
       deterministic=True, seed=42, scale_pos_weight = n_neg/n_pos of `fit`.
       Pass 1: early stopping on a custom feval calling
       eval.metrics.recall_at_fpr(scores, labels, cost_model.target_fpr).
       That metric is 0.0 every round (earlystop n_neg << 1/target_fpr), so
       pass 2 retrains without the callback and keeps all 200 trees (Decision 65).
  fit_platt(calib_margins, calib_labels)                     packages/detect/calibrate.py
    -- canonical Platt / Lin et al. Bayes-smoothed-target MLE (Decision 66);
       a>0 or abort. pi_t = prevalence(calib).
  models/l1-lgbm-v1.txt (booster, gitignored) + l1-lgbm-v1.json (ModelArtifact)
         + platt-v1.json (Calibrator) + audit.json
```

```
python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db --model-dir models/ --write-eval-run
  main() loads Layer1Model + Calibrator + audit.json; discovers real
    policy_config versions from --corpus-db (completes Decision 62's hand-off).
  run_all(42, feature_corpus, model, calibrator, audit_block, policy_versions)
    -- adds two Scorers to the existing (Sample) -> float protocol:       eval/scorers.py
         Layer1Scorer(model, calibrator, features, pi_s = serving_prior("in_control"))
           -> calibrator.apply(model.margin(x), pi_s)   [Platt then §3.2 prior correction]
         B0RulesScorer(features) -> FeatureRow.rule_score_raw   [read, never recomputed]
       on temporal_test + holdout_test only. evaluate() / Report / TierMetrics unchanged.
    -- _calibration_block(temporal_test): Brier + ECE for {raw, Platt,
       Platt+prior-correction} at pi0 and pi1 via prevalence_weights;
       reliability at both regimes.                                        eval/harness.py
  eval.report.render(runs) -> eval/outputs/report.md                       eval/report.py
    Block 1: + l1-lgbm-v1 and B0 rows per tier + holdout row (sanity scorers unchanged)
    Block 3: the real 24-row audit table (AUC + EXCLUDED/constant/ok marker)
    Block 5: the real calibration tables at pi0 and pi1 + the ECE gap at pi1
    Block 6: the real B0 row (ROC-AUC / AP / recall@target_fpr on temporal_test)
    Blocks 2 & 4: unchanged (nri_traffic keeps its marker; no theta curve -- Decision 57)
  eval.load.write_eval_run(conn, report, ...)                              eval/load.py
    -- one eval_run row per (model_version, split): l1-lgbm-v1/temporal_test,
       rules-only-v0/temporal_test, l1-lgbm-v1/holdout.
       run_id = sha256(config_hash ‖ build_hash ‖ model_version ‖ split_name ‖ seed),
       ON CONFLICT(run_id) DO UPDATE  -> idempotent re-runs.
       metrics JSON carries per-tier breakdown + build_hash + calibration + audit summary
       (no schema migration -- Decision 68).
```

**Live serving path** (`services/scorer/scoring.py::score_attempt`, Step 9): when `models/`
holds an artifact, `ScorerState.build_default` guarded-loads `model` + `calibrator`
(`deps.py::_load_model`, same pattern as the Redis fallback). Between rules and
`apply_auto_ceiling`, and inside the `latency_ms` window:
`margin, contribs = state.model.score_one(x)`; `score_raw = sigmoid(margin)`;
`score_calibrated = calibrator.apply(margin, serving_prior("in_control", state))`;
`top_contributors = top-k of contribs`; `model_version = "l1-lgbm-v1"`,
`calibrator_version = "platt-v1"`, `prior_used = pi_s`, `regime = "in_control"`.
**`decision = apply_auto_ceiling(evaluation.minimum_tier)` is unchanged** -- applying theta_T
to the calibrated posterior is Day 6 (Decision 57); the R1-R3 tier floors hold
unconditionally (Decision 17). With **no** artifact present the path is byte-identical to
Day 4 -- the authorized rules-only fallback.

## 14. [Day 6] Layer 2 + policy -- CUSUM / drift -> incident state machine -> cost-derived enforcement

Source: Day-6 Plan (`08-DAY-6-IMPLEMENTATION-PLAN.md`). Day 6 closes the loop
the first five days left open: the system now **decides**, entity-scoped and
cost-derived, never automatically above `challenge`.

### 14.1 Offline preparation (run once, in order)

```
python -m scripts.learn_store_baseline --db data/corpus/tollgate.db --demo-db tollgate.db
  reads ONLY the 7 negative-control runs (m-eval-12..18, episode_truth.kind='negative_control')
  re-scores each attempt's feature_snapshot through models/ (the SERVING regime, Decision 83)
  writes store_baseline rows: hourly_volume_profile (24 floats), flagged_rate_mean (p_bar_0),
    cards_per_ip_quantiles {"5m": [...11...], "30m": [...11...]}
  -- store_baseline is consumed ONLY by packages/detect/ (Decision 80); compute_features untouched

python -m scripts.tune_cusum --db data/corpus/tollgate.db --demo-db tollgate.db
  tau_flag = CostModel.tier_ladder()["throttle"]  (Decision 70, DERIVED)
  replays each negative-control run's (ingest_time, score_calibrated) through PoissonCusum
    at tau_flag, using that merchant's own store_baseline for lambda_0(t)
  bisects h for ZERO false alarms across the 7 runs; validates ARL0 >= 8,640 on Poisson noise
  writes a NEW policy_config version: cusum_h (tuned) + thresholds = CostModel.tier_ladder()
  TuningProvenance names every merchant_id read -- the assertion surface for
    test_cusum_tuning_isolation.py (negative controls only; no kind='attack' row touched)
```

### 14.2 Startup -- guarded load (services/scorer/deps.py::_load_layer2)

```
ScorerState.build_default()
  _load_model(models/)                 -> (Layer1Model, Calibrator) | (None, None)   [Day 5]
  _load_layer2(db_path, merchant_demo) -> (policy, baseline, layer2, incidents, engine, ttl)
    load_policy_config(latest)  -- None or thresholds == {} -> Layer 2 DISABLED (Day-5 path)
    load_store_baseline         -- None                     -> Layer 2 DISABLED (Day-5 path)
    CusumParams(rho, h, bucket_s, lambda_min)  DriftParams(quantile, p1, alpha, beta, enabled)
    Layer2Engine(baseline, cusum_params, drift_params, tau_flag)
    IncidentRegistry()   PolicyEngine()   policy_versions = {version: snapshot}
```

When `state.policy is None` the entire block below is skipped and every
`attempt_score` / SSE field is byte-identical to Day 5 (tests/conftest.py's
`scorer_state`, `eval/corpus.py::_replay_one` -- both build bare states, so the
Day-5 corpus / model / audit / eval_run rows are provably unaffected;
verified: the rebuilt corpus's `attempt_score` digest is unchanged).

### 14.3 The one seam (services/scorer/scoring.py::score_attempt)

```
features   = compute_features(...)     -- now 11 windows in the SAME score_path() call;
                                          cusum_bucket_index / distinct_cards_per_ip_30m_raw
                                          ride on FeatureVector, NOT in FEATURE_NAMES / snapshot()
evaluation = rules.evaluate_from_features(features)

-- Day 6, INSIDE the latency_ms window, only when layer2 is live and the attempt is not an
-- idempotent replay (M7):

regime, rate_ratio = layer2.regime_for(merchant_id, features.cusum_bucket_index)
     -- commits every CUSUM bucket strictly BEFORE this attempt's bucket and returns the
        committed alarm state, so the alarm regime that picks the prior is a pure function
        of already-scored buckets (no circularity with the tau_flag gate)

model block -- unchanged EXCEPT: regime == "alarm" -> pi_s = serving_prior("alarm", state,
               rate_ratio); ScoreRecord.regime / prior_used become real values

_resolve_layer2:
  scope   = "bin" if only R3 fired else "ip"          (Decision 85)
  entity  = resolve_entity(scope, ip, ua_class, card_hash, bin)   -- card -> ipua -> ip, never asn
  signal  = layer2.observe(entity, bucket_index, p_calibrated, distinct_cards_per_ip_30m_raw,
                           rule_families, card_hash)
             -- Layer 2a: n_t += (p_calibrated >= tau_flag); S_live = PoissonCusum.peek(...)
             -- Layer 2b: SequentialDrift.observe(distinct_cards_per_ip_30m, q_hi)  [ip / ipua]
             -- fired = cusum_alarm OR drift_fired ; detector in {cusum, drift, both, none}
  incident = incidents.step(entity, ingest_ms, signal, cooldown_seconds, pinned_policy_version)
             -- OPEN | ESCALATED | COOLING | CLOSED ; re-fire in cooldown MERGES (same id);
                harm fields (attempts_before_alert, cards_exposed_before_alert, time_to_detect_s
                in event time, cusum_stat_at_alert) stamped at first fire
  snapshot = policy_versions[incident.pinned_policy_version]  if a live incident pre-existed,
             else the live snapshot   (Backend Schema §3.1 -- pinned, cached, one DB read max)
  outcome  = engine.resolve(p_calibrated, evaluation, entity, snapshot, incident_open,
                            corroborated, active_enforced_count, bin_is_foreign_issued, regime):
      1. ladder      -- select_ladder(bin_is_foreign_issued); domestic drops step_up
      2. l2_tier     -- tier_from_score(p, thresholds, ladder)  [only if incident_open]
      3. P3          -- uncorroborated (< 2 rule-families across < 2 buckets) -> cap at monitor
      4. hysteresis  -- rise at theta_T, fall below theta_T - 0.08  (score-driven tier only)
      5. rule floor  -- proposed = max(l2_tier, evaluation.minimum_tier)   (rules raise, never lower)
      6. auto-ceiling-- in_force = apply_auto_ceiling(proposed, challenge); step_up/block PROPOSED
      7. K_max       -- active_enforced_count >= k_max_entities & new entity -> advisory, in_force=allow
      8. control arm -- 1 per block of 20 eligible, seeded on merchant+policy_version -> in_force=allow
  incidents.note_tier(incident, proposed_tier, ...)   -- appends a tier_transition, may ESCALATE

decision = outcome.in_force_tier    (was: apply_auto_ceiling(evaluation.minimum_tier))
```

### 14.4 Persistence -- through the existing spool -> drainer -> SQLite

`score_attempt` adds `incident` / `incident_entity` / `tier_transition` /
`enforcement` keys to the same spool payload it already writes.
`Drainer.drain_once` gains guarded branches: `upsert_incident` (ON CONFLICT DO
UPDATE -- state changes over the incident's life) BEFORE `insert_score`
(FK), then `insert_tier_transition` / `insert_enforcement_action` (INSERT OR
IGNORE, deterministic ids) AFTER. Re-drain from byte 0 stays idempotent --
the incident's final state is re-derived by replaying its ordered transitions.
`attempt_score.incident_id` / `regime` / `tier_ladder` / `control_arm` /
`policy_version` stop being hardcoded.

Enforcement rows: `throttle` / `challenge` -> `requires_confirmation=0`,
`confirmed_by='auto'`, `applied_at=ingest_ms` (in force). `step_up` / `block`
-> `requires_confirmation=1`, `confirmed_by=NULL`, `applied_at=NULL`
(proposed, never applied). `monitor` / `allow` / control / advisory -> no row.

### 14.5 SSE + D1

`scoring.py` adds three keys to the SSE event: `incident`
(`{incident_id, state, detector, entity_type, pseudonym, proposed_tier,
in_force_tier}` or null -- **`pseudonym` only, never a raw key**),
`enforcement` (`{active, k_max, advisory_mode}`), `control_arm`.
`services/dashboard/src/App.jsx`: the `ENFORCEMENT` tile renders `active /
k_max` live; the advisory banner (system-state, monochrome, never a threat
colour -- UIUX §6.10) appears at the cap. No incident drawer / timeline /
confirm dialog -- D3 is Day 8.

### 14.6 What Layer 2 catches, in practice

With `models/` loaded, `p_bar_0 ~ 0.60` (weak 4-feature Day-5 model,
Decision 83), so Layer 2a's `lambda_0` is high and the CUSUM is conservative:
it does not fire on the simulator's card-fan-out `easy` / `medium` tiers or
on low-and-slow `hard`. **Layer 2b (distinct-card drift) is the operative
detector for `easy` and `medium`** (verified: TTD ~76 s, `cards_exposed_
before_alert = 32`, incident -> ESCALATED -> `challenge` in force).
**`hard` is undetected by Layer 2** and is reported as such, not tuned around
(Day-6 Plan §8 risk 2). The R1-R3 rule floors remain active on every tier.

---

## 15. [Day 7] Security hardening — FULL → RULES-ONLY/SHED → FAIL-OPEN

All three rungs live in `services/scorer/routes_score.py`, **outside** the Layer-2 atomic
block (Decision 87 / §14.3). `_resolve_layer2` still contains no `await` — the
100-concurrent-vs-sequential CUSUM guarantee (`test_concurrent_cusum.py`) depends on it.

```
POST /v1/score
  ├─ auth (cached; 503 on cold-cache + locked DB, NEVER allow)
  ├─ FULL:            state.admission.try_consume(merchant_id, now_ms) == True
  │                     -> score_attempt() as Day 6 (+ SSE `availability` field)
  ├─ RULES-ONLY/SHED: bucket empty -> shed_incr(tg:{m}:shed:{ip}), R1-only tier,
  │                     X-Tollgate-Shed: 1, shed=True ScoreRecord, no score_path() call
  └─ FAIL-OPEN:       score_attempt() raised -> AvailabilityMonitor.record_fail_open,
                        `allow` ScoreRecord (degraded_reason fail_open:<reason>),
                        one ERROR log + `alert` on SSE per clock window, response = allow
```

**`POST /v1/outcome`** (`services/scorer/routes_outcome.py`, registered in `app.py`):

```
secret = os.environ["TOLLGATE_OUTCOME_SECRET"]  (unset -> 503, logged once)
  ├─ headers present? (X-Tollgate-Key/-Signature/-Timestamp/-Nonce)   else 401
  ├─ |now_ms - ts_ms| <= 300_000                                       else 401 (stale)
  ├─ merchant = merchant WHERE api_key_hash = sha256(key)              else 401
  ├─ hmac.compare_digest(sha256(secret), merchant.outcome_hmac_key_hash) else 401 (not bound)
  ├─ sig == hmac_sha256(secret, f"{merchant_id}\n{ts_ms}\n{nonce}\n{sha256(canonical_body)}")  else 401
  ├─ attempt_uid FROM auth_attempt WHERE (merchant_id, event_id)       else 404
  ├─ INSERT outcome_nonce(nonce)  -- IntegrityError -> 409 (replay), no auth_outcome row
  └─ INSERT OR IGNORE auth_outcome(attempt_uid, ..., sig_verified=1); commit -> {"status":"recorded"}
```
Canonical body = `json.dumps(body.model_dump(), sort_keys=True, separators=(",",":"))`.
No schema change (Decision 88/90). The three outcome-derived model features
(`decline_rate_per_ip_5m`, `invalid_cvv_share_ip_5m`, `outcome_coverage_ratio`) still read
`0.0` — feeding them needs new outcome-keyed windows, out of Day-7 scope.

**Narrator admission boundary** (`packages/narrator/`): at incident-open ONLY,
`scoring.py::_resolve_layer2` calls `build_bundle(entity_type=, pseudonym=, decision=,
evaluation=)` — the single admission point; it accepts **no `user_agent`**, no raw
identifier, no free text. `assemble_prompt(bundle)` renders the typed slots into the string
a backend would dispatch and asserts `CHARSET_RE` **before returning** (input-side gate);
`template.render(bundle)["narrative"]` is stored on `incident.narrative` /
`narrative_source="template"` through the existing spool → drainer path. Deterministic,
I/O-free, not an LLM call. A hostile UA is retained in `auth_attempt.client_evidence` as
evidence but has no path to the prompt (`test_narrator_injection.py`). Gemini remains Day 8.

## 16. [Day 7] Tier E — the adaptive adversary

```
scripts/train_l1  (frozen; existing models/ used)
   │
   ▼
packages/simulator/evade.py::search(seed, budget=200, patience=40, theta_challenge, evaluate_fn)
   -- PURE: imports only packages.simulator.rng; SubStream(seed, "evade:<field>") draws;
      searches the SIX params generate_attack_episode consumes (Decision 92);
      theta_challenge = pinned policy_config thresholds["challenge"] (derived, Decision 70);
      evaluate_fn (scripts/search_evasive.py) replays each candidate through the frozen
      InMemoryWindowStore + DayOneRules + models/ bundle + _load_layer2 detector via
      ReplayDriver.run(stream=...), reading score_calibrated + incident from a recording spool.
   │  objective: maximise cards_validated_per_hour s.t. mean(score_calibrated) < theta_challenge
   │             AND no incident opened; -inf otherwise.
   ▼
config/attack_tiers.yaml `evasive` block rewritten (A10-clean sources) + eval/outputs/evade_search.json
   │
   ▼
scripts/search_evasive --append-corpus  -> eval.corpus.build_tier_e_runs(42) (run_index 19,
   m-eval-19, seed+900) -> replay_corpus(rebuild=False) into data/corpus/tollgate.db
   -> episode_truth.evasion_params = json.dumps({six searched leaves})  (no schema change)
   │
   ▼
eval.harness --write-eval-run
   -- build_full_dataset() UNCHANGED; build_tier_e_dataset(42) filters build_runs+build_tier_e_runs
      to stream_tier=="evasive"; run_all() evaluates the dedicated `tier_e` split with the same
      scorers; evaluate()/write_eval_run/report.py per-tier loops gain `evasive`; the eval_run
      `per_tier.evasive` entry is sourced from the `tier_e` split, NEVER from temporal_test
      (Decision 93). report.md gains the `evasive` row + a Tier-E parameter-vector note.
```

## 10. What does NOT exist yet (explicitly deferred)

- [Day 7 DONE] `POST /v1/outcome` exists (route + HMAC / nonce / 5-minute staleness
  verification, §15). `decline_rate_per_ip_5m`, `invalid_cvv_share_ip_5m`,
  `outcome_coverage_ratio` **still** stay at `0.0` — the route persists to `auth_outcome`
  and stops there; feeding those features needs new outcome-keyed windows, which no Day-7
  deliverable names (Decision 90). `/v1/outcome` returns `503` unless
  `TOLLGATE_OUTCOME_SECRET` is set.
- No `store_baseline` row (Day 4); `distinct_cards_per_ip_5m_q`,
  `distinct_cards_per_ipua_5m_q`, `amount_percentile_vs_store`, `store_volume_deviation_
  sigma`, `store_decline_rate_deviation_sigma`, `foreign_bin_share_sigma` stay at `0.0`.
- [Day 6 DONE] CUSUM `S_t` (`packages/detect/cusum.py`), the distinct-card drift SPRT
  (`packages/detect/drift.py`), the incident episode state machine
  (`packages/detect/episode.py`), entity resolution + the cost-derived policy engine
  (`packages/detect/policy.py`) and the `Layer2Engine` coordinator
  (`packages/detect/layer2.py`) all exist and are wired into `score_attempt()` behind a
  guard (§14). `packages/detect/threat_state.py` is retained ONLY as the no-policy fallback
  (Decision 81). `τ_flag`-gated counting is in-process on `ScorerState` (Decision 71).
  Incidents / enforcement persist through the existing spool -> drainer -> SQLite path.
- [Day 6] Layer 2a is conservative with the weak Day-5 model loaded (`p_bar_0 ~ 0.60`,
  Decision 83) and does not fire on the simulator's card-fan-out `easy` / `medium` tiers
  or on low-and-slow `hard`. **Layer 2b is the operative Layer-2 detector for `easy` /
  `medium`; `hard` is undetected by Layer 2** (reported honestly, Day-6 Plan §8 risk 2).
- [Day 6] No Redis-backed CUSUM / enforcement state -- per-process only (Decision 71); no
  `bin_metadata` load / real AFA ladder (`select_ladder` is a tested pure function, live
  `tier_ladder` stays `"domestic"`); P3's ">= 2 buckets" is enforced in memory, not
  recorded in any column (Decision 84); the incident detail screen / confirmation API /
  Gemini narrator are Day 8 -- Day 6 only produces the proposed-but-unconfirmed
  `enforcement_action` rows those screens will act on.
- No D3 dashboard screen, no design tokens, no Stream Rail, no Gemini narrator backend
  (Day 8). [Day 7 DONE] the template narrator IS now called from `score_attempt()` at
  incident-open, through the `build_bundle()` / `assemble_prompt()` admission boundary
  (§15); `NARRATOR_BACKEND != "template"` still raises (Gemini is Day 8).
- No BIN metadata join -- `tier_ladder` is hardcoded `"domestic"`, `bin_is_foreign_issued`
  and `foreign_bin_share_5m` stay at `0.0`.
- [Day 4 -> Day 7 DONE] `medium` and now `evasive` attack tiers and all seven
  negative-control scenarios exist (`config/attack_tiers.yaml`,
  `packages/simulator/negative.py`); the `evasive` block is populated by the Tier-E search
  (§16) and is **no longer `pending`**. No flood/kill-scorer DC toggles (D3/D6 UI, Day 8).
- [Day 7 RE-DEFERRED] `/v1/stream` authentication. Decision 34 / Flow.md §10 / Threat Model
  §9 annotated it "Day 7", but the approved Day-7 deliverable list (§4 A–F) omits it, so it
  is **explicitly re-deferred past Day 7** under the minimality rule (Decision 94).
  `/v1/stream` still binds loopback only and publishes `rules_fired` / `feature_snapshot`
  unauthenticated; the residual disclosure risk is unchanged from Day 6.
- [Day 7] The token bucket, the fail-open availability monitor, and the stored-decision
  cache are **in-process on `ScorerState`** (Decision 86/87) — single Uvicorn worker only,
  not shared across workers and not surviving a restart. This is the same trade Decision 71
  already made for Layer-2 state.
- `tests/fixtures/handmade_40.jsonl` (the independent human-authored oracle) has not been
  supplied yet; `tests/acceptance/test_handmade_40.py` (Day-3 feature values) AND
  `tests/acceptance/test_handmade_40_incident.py` (Day-6 incident alert point) both xfail
  with a named reason until it is (Decisions.md decision 14 -- must not be generated by the
  implementation agent). **Day 6 ships and is tagged `day-6-done` only after a human
  supplies the fixture + the hand-counted `alert_seq` and that incident gate goes green.**
- [Day 5 DONE] The `l1-lgbm-v1` LightGBM detector (`packages/detect/model.py`), the Platt
  calibrator (`packages/detect/calibrate.py`), the persistent replay corpus
  (`eval/corpus.py`), and B0 (read from `attempt_score.score_raw`) all exist and are wired
  into `eval.harness` and the live `score_attempt` path (score yes, decide no). The
  discriminability audit runs against real `feature_snapshot` rows (`scripts/train_l1.py`);
  `eval.load.load_truth` is called per run by `replay_corpus`; `eval_run` has real per-tier
  rows (`eval.load.write_eval_run`).
- [Day 5] Six model features are EXCLUDED by the audit (Decision 64); the model runs on
  4 live features and is weaker than B0 except on `hard` (where B0 fires 0/3). Reinstating
  them needs the store-relative quantile transforms (Decision 16).
- [Day 5 -> Day 6 DONE] `apply_auto_ceiling` is still Threat Model §4/P1's ceiling
  mechanism, but the calibrated posterior now IS applied to `theta_T` via
  `PolicyEngine.tier_from_score` (Decision 57 was deferred to Day 6). Still no
  theta-indexed cost curve rendered into `eval/report.py` and no currency-amount headline
  -- Report Block 1 / Block 4 keep their honest "deferred" text (Day 8/9, Day-6 Plan §9).
- [Day 4] `nri_traffic`'s control is inert: `bin_is_foreign_issued` is 0.0 for every attack-tier
  event today (no BIN metadata join, per the bullet above) -- `test_nri_control_tripwire.py`
  fails the moment that changes while attack-side foreign share stays zero. (Report Block 2
  keeps the "inert" marker; Day-5 did not populate `bin_metadata`.)
