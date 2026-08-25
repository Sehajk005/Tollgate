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
  ├─ 4. resolve_client_ip(request)                          services/scorer/net.py
  │     -- request.client.host, or X-Forwarded-For if the peer is a
  │        configured trusted edge (TRUSTED_EDGE_HOSTS)
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
  │       -> FeatureVector (24 canonical features + trusted/degraded_reason)
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

## 10. What does NOT exist yet (explicitly deferred)

- No `/v1/outcome` route (Day 7); `decline_rate_per_ip_5m`, `invalid_cvv_share_ip_5m`,
  `outcome_coverage_ratio` stay at their Day-3 neutral `0.0`.
- No `store_baseline` row (Day 4); `distinct_cards_per_ip_5m_q`,
  `distinct_cards_per_ipua_5m_q`, `amount_percentile_vs_store`, `store_volume_deviation_
  sigma`, `store_decline_rate_deviation_sigma`, `foreign_bin_share_sigma` stay at `0.0`.
- No CUSUM statistic (`S_t`) -- Day 3 builds only the raw per-bucket attempt counter
  `windows.lua` step 6 names; `τ_flag`-gated counting is explicitly deferred to Day 6
  (Decisions.md decision 45). No drift detection / real incidents / entity resolution --
  `packages/detect/threat_state.py`'s rollup is an explicit Day-2 stand-in Day 6's incident
  detector replaces.
- No D3/D6 dashboard screens, no design tokens, no Stream Rail, no Gemini narrator backend
  (Day 8); the template narrator (§11 above) is not yet called from `score_attempt()`.
- No BIN metadata join -- `tier_ladder` is hardcoded `"domestic"`, `bin_is_foreign_issued`
  and `foreign_bin_share_5m` stay at `0.0`.
- No `medium`/`evasive` attack tiers (`config/attack_tiers.yaml` declares
  them `pending: "Day 4"`/`"Day 7"`); no negative-control selector, no
  flood/kill-scorer DC toggles (Day 4 / Day 7).
- No stream authentication -- `/v1/stream` publishes `rules_fired` and
  `feature_snapshot` unauthenticated; accepted for the loopback-bound demo
  (Threat Model v2 addendum, decisions.md decision 34), hardened Day 7.
- `tests/fixtures/handmade_40.jsonl` (the independent human-authored oracle) has not been
  supplied yet; `tests/acceptance/test_handmade_40.py` xfails with a named reason until it is
  (Decisions.md decision 14 -- must not be generated by the implementation agent).
