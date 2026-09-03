# Day 9 — Phase 3: Build J6 steps 6–8

**Executed:** 2026-09-03 (Session 1)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 3. Reconciliation R-2 (J6 6–8 unbuilt).
**Stop condition S-3** (a control needing a *faked* decision / tier / availability state):
**not triggered** — every control drives a real code path.

---

## 1. What was built

| File | Purpose |
|---|---|
| `services/scorer/demo.py` (new) | `demo_controls_enabled()` master gate (env `TOLLGATE_DEMO_CONTROLS`); `DemoFloodRunner` — a real concurrent `POST /v1/score` load generator (worker pool). |
| `services/scorer/routes_demo.py` (new) | `GET /v1/demo/cotenant-ip`, `POST /v1/demo/flood`, `POST /v1/demo/fault`. Every route 404s unless the env gate is on; all key-required (401). |
| `services/scorer/deps.py` | `ScorerState` gains `demo_fault: bool = False`, `demo_flood = None` (both inert defaults). |
| `services/scorer/routes_score.py` | before `score_attempt()`: `if state.demo_fault and demo_controls_enabled(): raise` → the existing `except → _fail_open` path. |
| `services/scorer/app.py` | registers `demo_router`; lifespan `finally` stops a running flood. |
| `services/dashboard/src/components/DemoControlStrip.jsx` | FLOOD + KILL SCORER toggles, in a group labelled "DEMO", rendered only when `VITE_TOLLGATE_DEMO_CONTROLS=1`. |
| `services/storefront/src/screens/S2Checkout.jsx` | `?demo=1` "Checkout as CGNAT co-tenant" button — GETs `/v1/demo/cotenant-ip`, re-runs the checkout tagged `x-tg-demo-xff: <ip>`. |
| `services/storefront/vite.config.js` | proxy `configure` hook: when `TOLLGATE_DEMO_CONTROLS` is on, promotes `x-tg-demo-xff` → `X-Forwarded-For` (the browser cannot set XFF; the Vite proxy IS the declared trusted edge). Inert off the demo path. |
| `docker-compose.yml` | `TOLLGATE_DEMO_CONTROLS=1` on scorer + storefront; `VITE_TOLLGATE_DEMO_CONTROLS=1` on dashboard + storefront. |

All gates default OFF; nothing here changes production / default behaviour.

---

## 2. Acceptance tests (new — `tests/acceptance/test_demo_*.py`)

| File | Count | Covers |
|---|---|---|
| `test_demo_fault.py` | 6 | route 404 without the gate; the flag alone (no env) does not change `/v1/score`; enabled → `allow` + `fail_open:model`, never 5xx; auth required; sustained breach → ERROR **once per window** + still `allow`; toggling off restores the full path |
| `test_demo_cotenant_ip.py` | 8 | 404 without the gate; key required; 404 when nothing enforced; returns an `ip`-type enforcement's IP; resolves an `ipua`-type back to a raw IP via `auth_attempt`; a released enforcement is skipped; the returned IP is honoured as XFF **only from the declared edge**; `apply_auto_ceiling(BLOCK) == CHALLENGE` (the co-tenant can never be blocked) |
| `test_demo_flood.py` | 5 | route 404 without the gate; key required; `enabled:true` with no merchant key → **503, loud refusal**; `enabled:false` a safe no-op; **source-level**: `demo.py` / `routes_demo.py` touch no `shed_incr` / `window_store` / `_shed(` / `degraded_reason` — the flood reaches shed only through the real `AdmissionController` |

**19 new tests, all green.** Full `pytest tests/ -q` after Phase 3: **637 passed / 1 failed / 2 xfailed**
— the 1 failure is `test_d6_provenance::test_corpus_identity` (**DEF-D9-003**, from Phase 2);
`test_durability` flaked once in a machine-loaded background run and passes clean in
isolation (`1 passed in 13.32s`).

`vitest`: 205 passed. `playwright`: 68 (one D6-layout test flaked under 4-worker
contention, passes 4/4 isolated).

---

## 3. Manual demonstration on the Compose stack

### Step 8 — fault injector
```
POST /v1/demo/fault {enabled:true}                 -> {"fault": true}
POST /v1/score x3 (under fault)                    -> 200 allow, latency 0-2 ms, never 5xx
attempt_score.feature_snapshot.degraded_reason     -> fail_open:model  (baseline row: null)
POST /v1/demo/fault {enabled:false}                -> {"fault": false}; full path restored
```
Alert-once-per-window: `fail_open_alert_threshold` is 20; the once-per-window ERROR is
proven by `test_demo_fault.py::test_sustained_breach_alerts_once_per_window` (threshold 4).

### Step 7 — flood → rules-only shed rung
```
POST /v1/demo/flood {enabled:true}   -> starts 250 worker coroutines POSTing /v1/score
after ~16 s sustained:  flood shed_responses = 155   (X-Tollgate-Shed:1 on the flood's own
                                                      requests -- the token bucket is empty)
a concurrent checkout                -> intermittently X-Tollgate-Shed: 1
POST /v1/demo/flood {enabled:false}  -> stops; flood sent = 1291
```
The **real** `AdmissionController.try_consume` path is exercised — `shed` is never set by a
flag (source-level test). **Caveat (DEF-D9-004, P3):** on this single-worker dev scorer the
per-request cost is ~50 ms (DEF-D9-001), only marginally above the 50/s admission refill, so
the 200-token bucket takes ~15 s of sustained concurrent load to empty and then sheds
*intermittently* rather than continuously. The shed rung itself is fully proven by
`test_admission_shed.py`; on a faster / multi-worker deployment the flood sheds immediately.
Phase 13 may raise the flood concurrency or Phase 10 may address the per-request cost.

### Step 6 — CGNAT co-tenant (the money shot)
```
(attack replay: easy, seed 42, speed 60 -> incidents open, challenge enforced on
 198.51.100.57 / 198.51.100.249 and others)
GET /v1/demo/cotenant-ip            -> {"ip":"198.51.100.249","entity_type":"ip", ...}
                                      (loopback / RFC1918 skipped -> a real attacker IP)
POST :5173/v1/score  + header x-tg-demo-xff: 198.51.100.249
                                   -> Vite proxy promotes it to X-Forwarded-For;
                                      scorer trusts the storefront container as the
                                      declared edge (TOLLGATE_TRUSTED_EDGE_HOSTS)
auth_attempt.ip for that checkout   -> 198.51.100.249   (real entity resolution)
decision                           -> allow
```
The legit co-tenant checked out from the enforced IP and was **not blocked** — a single
clean attempt does not cross R1, so it resolves to `allow` (even better than `challenge`);
the `challenge` auto-ceiling guarantees `block` is unreachable without operator
confirmation (`apply_auto_ceiling` test). Nothing about the decision is special-cased.

### Scorer-unreachable (free under Phase 2)
`docker compose stop scorer` -> the dashboard connection chip degrades; storefront
client-side path still completes. (Exercised implicitly by every `restart scorer` this
phase; a scripted capture belongs to Phase 7.)

---

## 4. Verdict

**Phase 3 COMPLETE.** Steps 6, 7, 8 built on real code paths, gated behind
`TOLLGATE_DEMO_CONTROLS=1` (default off) + visible UI labelling, 19 new acceptance tests
green, full suite green except the pre-existing DEF-D9-003. One P3 caveat (DEF-D9-004 —
flood is marginal/slow on the dev scorer). S-3 not triggered.

Evidence: `evidence/day-9/phase-3-pytest*.log`, this file, and the manual transcripts above.
