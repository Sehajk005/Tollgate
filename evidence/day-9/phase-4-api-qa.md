# Day 9 — Phase 4: Backend / API QA

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 4.
**Path under test:** the Docker Compose stack (the judge's deployment path) —
`scorer` container on `:8080`, `TOLLGATE_DEMO_CONTROLS=1`, `RedisWindowStore`,
Layer 1 + Layer 2 loaded (`policy v2, cusum_h=318.133`).
**Harness:** `evidence/day-9/phase-4-api-qa-harness.py` (66 checks) →
`evidence/day-9/phase-4-api-qa-results.json`. **66 / 66 PASS.**

Every route in `services/scorer/` was exercised with the plan's matrix: happy
path · auth present / absent / invalid / empty · malformed body · oversized body ·
missing required fields · wrong types · duplicate `event_id` · same `event_id`
with a different payload · concurrent identical requests · wrong method · unknown
route. State transitions were verified, not just status codes.

There is **no `/metrics` route** on the scorer (the plan lists one). D6 metrics is
a frontend-only route (`#/metrics`) rendered from the committed artifact with zero
backend calls (Decision 100). Not a defect — recorded so the audit does not chase it.

---

## 1. Per-route results

### `GET /healthz` — 2/2
| Case | Result |
|---|---|
| happy (no auth) | 200 `{"status":"ok","drainer_alive":true,"drainer_connects":1,"drainer_rows":5883,"drainer_failures":0}` — counters-only liveness probe (AUDIT-006 signal) |
| wrong method `POST` | 405 |

### `POST /v1/score` — 16/16
| Case | Result | State effect verified |
|---|---|---|
| happy path | 200, body **exactly** `{attempt_uid, decision, latency_ms}` (`extra="forbid"` on `ScoreResponse` — no rule names, no raw score: Threat Model A2) | `attempt_score` row written via spool → drainer |
| auth absent / invalid / empty string | 401 `{"detail":"invalid or missing API key"}` each | no row |
| malformed JSON | 422 (pydantic), operator-readable field-error list | no row |
| wrong content-type (form-encoded) | 422 | no row |
| missing required fields | 422, `loc` names every missing field | no row |
| empty `event_id` (`min_length=1`) | 422 | no row |
| wrong type `amount_minor="…"` | 422 | no row |
| negative `amount_minor` (`ge=0`) | 422 | no row |
| hostile extra fields (`ip`, `merchant_id`, `rules_fired` in body) | 200 — silently **dropped** (`ScoreRequest` `extra="ignore"`; `ip` has no field at all). Merchant identity from the key only; IP from `resolve_client_ip` only. Threat-boundary probe → Phase 6 confirms at the feature layer. |
| oversized body (~4 MB `card_hash`) | 200 — **accepted, no 500, no hang** (~0.4 s). No body-size cap. Recorded for Phase 6 as an availability consideration, not a Phase-4 correctness defect. |
| duplicate `event_id` + identical payload | 200, **same `attempt_uid`** both times — idempotent replay. DB: 1 `auth_attempt` row for the identical pair. |
| same `event_id` + **different** payload (`amount_minor` changed) | 200, **new `attempt_uid`** — by design. Idempotency key = `sha256(merchant_id \| event_id \| payload_digest)` (Threat Model v2 §3 pt 2, `compute.py:264-274`), deliberately the full tuple: a mutated body is a genuinely new attempt, never a silently-dropped one. |
| 10× concurrent identical `event_id` | all 200, **1 distinct `attempt_uid`**, all `allow`. DB: 1 `auth_attempt` row. Idempotency holds under concurrency (AUDIT-005 / Decision 103). |

Latency (Phase-4 sanity only — Phase 10 owns the real gate): warm `/v1/score`
round-trip over Windows→container loopback n=30 → p50 59 ms, p95 68 ms, one 313 ms
outlier; first (cold) request 551 ms compute. Flagged for Phase 10.

### `GET /v1/stream` + `GET /v1/stream/recent` — 4/4
| Case | Result |
|---|---|
| `/v1/stream` opens | 200, `content-type: text/event-stream`, `X-Accel-Buffering: no`, first bytes `": ping\n\n"` — headers flush immediately on subscribe (AUDIT-020 fix) |
| `/v1/stream/recent` happy (unauth — Decision 94) | 200 `{"events":[…]}` (6 buffered) |
| `after=<unknown cursor>` | 200, returns the full buffer, **no error** |
| bad key still 200 | 200 — deliberately open read surface (Decision 94); disclosure risk recorded, R-5 / Phase 6 |

### `POST /v1/replay/{start,stop,reset}` + `GET /v1/replay/status` — 15/15
| Case | Result |
|---|---|
| `GET /status` no auth | 200, `state=idle` — deliberately open (Decision 107): the refresh-recovery path must work with a misconfigured dashboard key |
| `start` / `stop` / `reset` auth absent | 401 each |
| `start` / `reset` auth invalid | 401 each |
| `start` missing `tier` | 422 |
| `start` wrong type `speed="fast"` | 422 |
| `start` **unknown tier** `"no-such-tier"` | **202 accepted**, then the async task raises `KeyError: 'no-such-tier'` in `build_stream` → state `failed`, `error="KeyError: 'no-such-tier'"`, `terminal=true`. Graceful (AUDIT-007 capture works), recoverable by `reset`, **not reachable from the demo DC strip**. Logged **DEF-D9-005 (P3)**. |
| rejected (`start` bad key) leaves state untouched | `idle → idle` |
| `start` happy (`easy` seed 42 speed 60) | 202, `state=starting`, fresh `run_id` |
| `start` again while busy | **409** `{"detail":"replay already running"}` |
| `stop` happy | 200, `state=stopped`, `sent=6/821` — the **true terminal snapshot**, never a stale `running` (AUDIT-003) |
| `reset` happy | 200, `state=idle`, `cleared={window_store:86, threat:true, layer2:true, incidents:true, policy_engine:true, decision_cache:true, persisted_incidents:0}`, `degraded=false` (AUDIT-001 / Decision 105) |
| `status` post-reset | `state=idle`, `run_id=null` |

### `GET /v1/incidents` + `/{id}` + `/{id}/confirm` + `/{id}/resolve` — 12/12
| Case | Result |
|---|---|
| `GET /v1/incidents` happy | 200 `{"incidents":[]}` (none open post-reset) |
| auth absent / invalid | 401 each |
| **`?state=<anything>`** (`live`, `bogus`, …) | 200, **identical result every time** — the `state` query param is declared + documented but **never passed to `read_open_incidents`**, which hard-codes `state != 'CLOSED'` (`repository.py:335-347`). Logged **DEF-D9-006 (P3)**. |
| `GET /{id}` unknown | 404 `{"detail":"unknown incident"}` |
| `GET /{id}` auth absent | 401 |
| `POST /{id}/confirm` unknown incident | 404 |
| `POST /{id}/confirm` auth absent | 401 |
| `POST /{id}/confirm` missing `action_id` | 422 |
| `POST /{id}/resolve` unknown incident | 404 |
| `POST /{id}/resolve` bad `resolution` value | 422 `{"detail":"resolution must be false_positive or true_positive"}` |
| `POST /{id}/resolve` auth absent | 401 |

A full confirm→resolve state-transition test against a **real open incident**
(entity ceiling raised in the live `PolicyEngine`, enforcement rows released) is
run in Phase 8 / Phase 9 where a live incident exists.

### `POST /v1/outcome` — 5/5
| Case | Result |
|---|---|
| unsigned (no HMAC headers) | 401 `{"detail":"unsigned"}` |
| stale timestamp (`ts=1`) | 401 `{"detail":"stale"}` |
| fresh ts, bad signature | 401 `{"detail":"bad signature"}` |
| extra field (`extra="forbid"`) | 422 |
| missing `event_id` | 422 |

Happy path + `404 unknown event_id` + `409 replayed nonce` + `503 secret unset`
are exercised in Phase 6 with a correctly-signed request against a real scored
`event_id`; `test_outcome_hmac.py` (green suite) already covers all six wire outcomes.

### `GET /v1/demo/cotenant-ip` + `POST /v1/demo/flood` + `POST /v1/demo/fault` — 10/10
`TOLLGATE_DEMO_CONTROLS=1` on this stack, so the routes are live.
| Case | Result |
|---|---|
| `cotenant-ip` key ok | 200 `{"ip":"198.51.100.249","entity_type":"ip","expires_at":4581470}` — served from a persisted `enforcement_action` row (Session-1 replay; stale-enforcement note below) |
| `cotenant-ip` auth absent | 401 |
| `flood {enabled:false}` | 200 `{"flood":false,"sent":0,"shed_responses":0}` — safe no-op |
| `flood` auth absent | 401 |
| `flood` missing `enabled` | 422 |
| `fault` auth absent | 401 |
| `fault` missing `enabled` | 422 |
| `fault {enabled:true}` → `POST /v1/score` | 200 `allow` — **fail-open, never a 5xx** |
| `fault {enabled:false}` | 200 `{"fault":false}` — restored |
| after OFF → `POST /v1/score` | 200 `allow`, full path restored |

The `/v1/demo/*` surface with the env gate **unset** is covered by
`test_demo_{fault,cotenant_ip,flood}.py` in the green suite and re-confirmed live
in Phase 6.

### Unknown routes — 2/2
`GET /v1/does-not-exist` → 404; `GET /` → 404 (no index). Standard FastAPI
`{"detail":"Not Found"}` — operator-readable, not a stack trace.

---

## 2. New defects

### DEF-D9-005 — `POST /v1/replay/start` accepts an unknown `tier` (P3)
- **Observed:** `{"tier":"no-such-tier"}` → `202 Accepted`, `state=starting`; ~90 ms
  later the replay task raises `KeyError: 'no-such-tier'` (`packages/simulator/
  generate.py:83`, `attack_tiers[tier]`) → driver transitions to `failed`,
  `error="KeyError: 'no-such-tier'"`, `terminal=true`.
- **Severity:** P3. Failure captured honestly (AUDIT-007 behaviour), state terminal
  and recoverable via `reset`, unreachable from the DC strip (`TIER_OPTIONS` only).
- **Root cause:** `ReplayStartBody.tier` is an unconstrained `str`; no allow-list
  check at the boundary, so an invalid value is only caught deep in the async task.
- **Fix:** none this phase. Phase 13 candidate — validate `tier` ∈
  `{easy,medium,hard,evasive}`, return `422 {"detail":"unknown tier '…'"}`.
- **Evidence:** §1; scorer log `replay: run failed at 0/0` + traceback.

### DEF-D9-006 — `GET /v1/incidents?state=` is a dead parameter (P3)
- **Observed:** `?state=live`, `?state=closed`, `?state=bogus` all return the
  identical list (non-CLOSED incidents).
- **Severity:** P3. No functional impact — the dashboard only sends the default and
  `read_open_incidents` correctly returns live incidents. But route + docstring
  advertise a filter that does nothing.
- **Root cause:** `list_incidents(state: str = "live", …)` never forwards `state`;
  `read_open_incidents(conn, merchant_id)` hard-codes `WHERE state != 'CLOSED'`
  (`packages/storage/repository.py:335`).
- **Fix:** none this phase. Phase 13 candidate — honour or drop the param.
- **Evidence:** §1; source read of `repository.py:335-347`.

---

## 3. Observations carried forward (not Phase-4 defects)

- **Oversized request bodies accepted uncapped.** ~4 MB `card_hash` → 200 in
  ~0.4 s, no `413`. Phase 6 evaluates as a DoS surface; token-bucket admission
  (`rate_per_s 50 / burst 200`) is the volume mitigation, not per-body size.
- **Stale persisted enforcement.** `GET /v1/demo/cotenant-ip` returned
  `198.51.100.249` while replay state was `idle` and freshly reset — `reset`
  cleared live detector state + `persisted_incidents:0`, but `enforcement_action`
  rows from Session-1 replays (`released_at IS NULL`) survive on the volume DB.
  Phase 8 checks whether `reset` should release persisted enforcement or whether
  the TTL is the intended expiry (Decision 99).
- **`/v1/score` cold first request = 551 ms compute** (model/feature warmup),
  warm p50 ≈ 59 ms round-trip. Phase 10 owns the p50/p95/p99 gate.

---

## 4. Verdict

**Phase 4 COMPLETE.** 66/66 API-QA checks pass. Every route enforces its auth
boundary, validates its body with operator-readable 422s, and never returns a raw
stack trace or an unmapped 500. Two **P3** defects logged (DEF-D9-005, DEF-D9-006)
— neither on the demo path, both Phase-13 candidates. No P0/P1/P2. Idempotency
(`event_id` + payload tuple) verified correct at the API and DB level, including
under 10× concurrency.
