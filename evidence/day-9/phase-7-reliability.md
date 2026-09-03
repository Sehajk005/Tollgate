# Day 9 — Phase 7: Reliability, State Machine, Failure Injection

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 7.
Faults injected against the **running Compose stack**. Each answers the plan's six
questions: *does it fail · does it fail safely · does the UI tell the truth · can
the operator recover · is state/data preserved · can the demo continue?*

Legend: **FS** = fails safely · **UI** = UI/status tells the truth · **REC** =
operator recovers · **DATA** = state/data preserved · **DEMO** = demo can continue.

---

## Fault matrix

| # | Fault | Result | FS | UI | REC | DATA | DEMO |
|---|---|---|:-:|:-:|:-:|:-:|:-:|
| 1 | **Redis killed mid-scoring** (`docker compose stop redis`) | 5 scores → **200 `allow`** every time, `degraded_reason: fail_open:window_store`, **never a 5xx**. `/healthz` still 200 (event loop not blocked — the socket timeout is the mechanism). SSE published 5 `availability.fail_open:true` frames; `alert:false` (< the 20-breach threshold, correct). | ✅ | ✅ | ✅ | ✅ | ✅ |
| 1b | **Redis restarted** (`docker compose start redis`) | Scorer **auto-recovered with no restart** — next scores `degraded_reason: null`, `attempts_per_ip_60s` counting 1/2/3 again. redis-py pool re-established transparently. | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2 | **Scorer restarted** (`docker compose restart scorer`, SIGTERM) | Healthy in 8 s. Startup log clean (Redis connected, Layer 1 + Layer 2 loaded). Drainer **resumed from the persisted byte offset `30713734`** — no re-drain, `drainer_rows` 6767 preserved, `attempt_score` count 6767 → 6767 (no loss, no double-write). Replay state `idle` / `run_id:null` / `terminal:true` — **no stuck `running`**. Score works immediately after. | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3 | **Scorer SIGKILL mid-replay** (`docker compose kill scorer` at `running 6/821`) | Scorer unreachable (`[000]`). After `start`: replay state `idle` / `run_id:null` / `terminal:true` / `error:null` — the in-process replay state (Decision 71) is lost cleanly on a hard kill, **not** left as a phantom `running`. The 6 scored events survived (spool → drainer). Operator recovery: a fresh `POST /v1/replay/start` → 202 `running 4/821` under a new `run_id`, **no manual intervention**. | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4 | **SSE drop → polling fallback contract** | `GET /v1/stream/recent?after=<uid>` returns events **strictly after** the cursor, in order; the cursor uid is excluded; later uids present. This is exactly what `useEventStream` polls on an SSE drop. `GET /v1/stream` flushes `: ping` immediately on subscribe (AUDIT-020). Browser-side SSE→5 s-poll→SSE recovery → Phase 11. | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5 | **SQLite locked** (held `BEGIN EXCLUSIVE` on the demo DB for 4 s) | `GET /v1/incidents` during the lock → **200** (read-only connection, WAL snapshot). `POST /v1/score` during the lock → **200** (the score path writes the append-only **spool file**, never SQLite directly; the drainer writes async and retries on lock). `drainer_failures: 0` throughout. **Scoring is fully decoupled from DB contention.** | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6 | **Redis unavailable at scorer startup** (`stop redis` then `restart scorer`) | Scorer healthy in 12 s. Startup log: **`ERROR … falling back to InMemoryWindowStore (single-process limitation applies)`** — explicit, not silent (with a redis `ConnectionError` traceback for diagnosis). Scores → 200 `allow`, `degraded_reason: null`, `attempts_per_ip_60s` counting — a **real in-memory window path**, not fail-open. Restore: `start redis` + `restart scorer` → `Connected to Redis … using RedisWindowStore`. | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Faults covered elsewhere (cross-reference)

| Fault | Where verified |
|---|---|
| Duplicate `event_id` · malformed request · invalid API key | **Phase 4** — idempotent (1 uid) / 422 pydantic / 401 |
| `reset` during replay · `stop` during replay | **Phase 8** — replay lifecycle |
| Dashboard refresh (idle / mid-replay / post-completion) · storefront refresh · browser opened before backend ready · in-browser SSE→5 s-poll→SSE recovery | **Phase 11** — UI/UX (backend contract verified in Fault 4) |
| API timeout | **Fault 1** — the fail-open budget / socket timeout is the mechanism (`FAIL_OPEN_BUDGET_MS` on the redis client) |
| Spool present at startup · stale spool segment | **Fault 2** — drainer resumes from a persisted byte offset, no re-drain |
| Partial service startup | `depends_on: condition: service_healthy` chain (redis → bootstrap → scorer → frontends); Session 1 Phase 2 verified the clean bring-up |
| Gemini unavailable / malformed JSON / 429 / charset violation | Stack runs `NARRATOR_BACKEND=template`; `test_narrator_{gemini_fallback,gemini_success,model_fallback,eval_disabled,template,startup_validation}` → **23 passed**. The narrator is **out-of-band** (Decision 98), never on the scoring path (Phase 10); any Gemini fault leaves the template narrative intact and the operator sees no error. |

---

## No swallowed background-task exceptions · no CPU loops · no corrupted state

- **Replay task exceptions surfaced, not swallowed** (AUDIT-007): an unknown tier
  (DEF-D9-005, Phase 4) → `state=failed`, `error="KeyError: 'no-such-tier'"`,
  `terminal=true`. A hard kill (Fault 3) → clean `idle`, not a phantom.
- **Drainer never wedged** — `drainer_failures: 0` across every fault; the
  `/healthz` counters (`drainer_alive`, `drainer_connects ≤ 2`) stayed healthy.
- **No CPU loop / blocked event loop** — `/healthz` answered within its timeout
  during Redis-down (Fault 1), SQLite-locked (Fault 5), and every restart.
- **No corrupted state** — after all six faults + restores, `docker compose ps`
  shows all 5 services healthy; `POST /v1/replay/reset` → `idle` with a full
  `cleared` map (`persisted_incidents: 11` cleared); `attempt_score` row counts
  monotonic, no double-writes.

## Observations (not defects)

- **`InMemoryWindowStore` fallback logs a full redis traceback** via
  `logger.exception`. The key message line is clear; the traceback aids
  diagnosis. Not a defect (intentional).
- **Spool file grows unbounded** (`attempts-active.jsonl` = 30 MB). The drainer
  tracks a byte offset and never truncates; `docker compose down -v` resets it.
  Spool rotation is a post-Day-9 concern — not on the demo path.
- **`reset` clears persisted incidents** (`persisted_incidents: 11` this run) but
  the interaction with already-CLOSED incidents' `enforcement_action` rows
  (`released_at IS NULL`) is examined in **Phase 8** (`GET /v1/demo/cotenant-ip`
  returned an enforced IP after a Phase-4 reset that reported `persisted_incidents: 0`).

---

## Verdict

**Phase 7 COMPLETE.** All 6 injected infrastructure faults fail **safely** — no
5xx where fail-open is required, no swallowed exceptions, no CPU loop, no
corrupted state, recovery works in every case, and the demo can continue after
each. Scoring is decoupled from both Redis (fail-open) and SQLite (spool) so a
storage fault degrades gracefully rather than breaking the demo. **No new
defects.**
