# Tollgate — Day 1 Walking Skeleton: Actual Execution Flow

This documents what the code actually does, using real names, as of the Day 1
implementation. Not a generic architecture description — see `07-IMPLEMENTATION-PLAN-v2.md`
for that. Update this file whenever the execution path changes.

---

## 1. POST /v1/score — the scoring path

```
Browser / curl
  │
  ▼
POST /v1/score  (services/scorer/routes_score.py:score)
  │
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
  │
  ├─ 5. state.clock.now_ms()                                packages/clock/clock.py (SystemClock)
  │     state.ulid.new()                                    packages/clock/ids.py (UlidGenerator)
  │     -- attempt_uid minted from the clock, not wall time
  │
  ├─ 6. DayOneRules.evaluate(RuleInput(...))                packages/detect/rules.py
  │     For each of R1/R2/R3:
  │       InMemoryWindowStore.record_and_read(WindowRequest) packages/features/memory_store.py
  │         -- window_key(merchant_id, space, key, metric)   packages/features/keys.py
  │         -- add member at ingest_ms, trim <= ingest_ms - window_ms, return count
  │     -> RulesEvaluation(results=(R1, R2, R3))
  │        .minimum_tier  (Decision.ALLOW if none fired, else the max fired tier)
  │        .fired_names, .feature_snapshot, .rule_score()
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
  ├─ 11. await state.event_bus.publish({...})                packages/storage/bus.py (InProcessEventBus)
  │      -- delivered to every subscriber's asyncio.Queue
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

## 6. What does NOT exist yet (explicitly deferred)

- No `/v1/outcome` route (Day 7).
- No Redis; `InMemoryWindowStore` is the only `WindowStore` backend (Day 3
  adds `RedisWindowStore` behind the same protocol).
- No idempotency guard (`SET NX` on a payload digest) -- `payload_digest` is
  computed and stored, but nothing rejects a duplicate yet (Day 7).
- No CUSUM / drift detection / incidents / entity resolution (Day 6).
- No narrator, no D3/D6 dashboard screens, no design tokens (Day 8).
- No BIN metadata join -- `tier_ladder` is hardcoded `"domestic"`.
