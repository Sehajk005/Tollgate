# Day 9 — Phase 8: Replay Lifecycle (release gate)

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 8 — "highest-priority area … the
complete demo is repeatable. A demo that works once but not twice is NOT
demo-ready."

Harness: `evidence/day-9/phase-8-replay-harness.py` → `phase-8-replay-results.json`
(console: `phase-8-replay-console.log`). Backend state + persisted data verified,
not just the wire status. **19 launches, 19 distinct `run_id`s.**

---

## A. Speed-0 matrix — `{easy,medium,hard,evasive}` × pace `{on,off}` × 2 repeats (seed 42)

**16 / 16 PASS.**

| Tier | rep1 | rep2 | pace on | pace off | terminal | `attempt_score` parity |
|---|---|---|---|---|---|---|
| **easy** | **821 / 821** | **821 / 821** | 821 | 821 | `finished` | Δ == `sent` every run |
| medium | 701 / 701 | 701 / 701 | 701 | 701 | `finished` | ✅ |
| hard | 508 / 508 | 508 / 508 | 508 | 508 | `finished` | ✅ |
| evasive | 390 / 390 | 390 / 390 | 390 | 390 | `finished` | ✅ |

- **Repeatable** — both reps of every `(tier, pace)` config produced the
  **identical** event count.
- **`easy` = 821** exactly (plan invariant).
- **Count invariant under pace on/off** — same events, only the sleep changes
  (Decision 106).
- **Terminal state `finished`, `sent == total`, `terminal == true`** on every run
  — never `N−1/N` (AUDIT-002).
- **`attempt_score` row Δ == `sent`** on every run — no run swallowed (AUDIT-005).
- **`run_id` unique** on every launch (16 distinct here).
- **`reset` → 200** with a full `cleared` map, `degraded: false`, every time.
- **Redis floor** — on the scorer's actual DB (`redis://redis:6379`, **db 0**):
  `dbsize` = **0**, zero `tg:*` keys after `reset` (the harness's own
  `redis_floor()` read db 9, the `verify_60x` DB — corrected here against db 0).

---

## B. Speed-60 (demo path) — `easy` pace-on / pace-off, `medium` pace-on

**3 / 3 PASS.**

| Run | Result | Wall time | Open incidents |
|---|---|---|---|
| `easy` / 60 / pace | `finished 821/821` | **126 s** | 2 |
| `easy` / 60 / **no pace** | `finished 821/821` | **183 s** (~3 min — matches README) | 2 |
| `medium` / 60 / pace | `finished 701/701` | **125 s** | 13 |

Pacing brings the visible run inside ~2 min while producing the identical event
stream (AUDIT-014). `medium` opens far more incidents (13) than `easy` (2) — the
detection stack responds to tier density, not a fixed script.

---

## C. Lifecycle ops

**5 / 5 PASS.**

| Op | Result |
|---|---|
| **C1 — stop mid-run** (AUDIT-003) | running `109/821` → `POST /stop` returned `state=stopped`, `sent=110` — the **true terminal snapshot**, never a stale `running`. |
| **C2 — reset while running** (AUDIT-004) | running → `POST /reset` → **200**, `state=idle`, `run_id=null` — transactional cancel → clear → idle. |
| **C2b — backend actually stopped** | `attempt_score` `19018 → 19018` across a 4 s window after the reset — the loop is genuinely cancelled, not still scoring behind an "idle" status. |
| **C3 — repeat run, same process** (AUDIT-005) | run 1 `821/821` → run 2 (launched from the terminal-dirty state) `821/821`, **distinct `run_id`s**, `auto_reset: true` reported. The second run of a tier is **not invisible**. |
| **C4 — tier switch and back** | `medium 701/701` → `easy 821/821` → `easy 821/821` — 3 distinct `run_id`s, both `easy` runs full. |

---

## D. Speed-1 (paced proof — a full run is ~real-time hours, not a demo speed)

`POST /v1/replay/start {"tier":"easy","speed":1}` → **202**, `state=running`; after
20 s it had scored `1/821` (paced at real inter-event gaps, **not** racing). A
`POST /v1/replay/stop` returned **`stopping`** and the status **stayed `stopping`
for ≥ 10 s** (5 polls) — see **DEF-D9-007**. `POST /v1/replay/reset` then cleaned
up to `idle`, `degraded: false` (a `reset` cancels the task, so it interrupts the
paced sleep; a `stop` does not).

The harness scored this a FAIL because its assertion required `stop → "stopped"`;
the underlying behaviour is DEF-D9-007 (a P3 stop-lag at low speed). Speed-1
**pacing itself works** (it does not finish instantly), the launch is accepted,
and `reset` always recovers. Speed-0-vs-60 determinism — the load-bearing
invariant — is covered by `verify_60x --gate crossing` (green, Session 1) and
Phase 10.

---

## Refresh / dashboard-open scenarios → Phase 11

`refresh during` · `refresh after` · `open dashboard mid-replay` · `open dashboard
post-replay` are browser behaviours verified in **Phase 11** (the backend
back-fill contract — `/v1/stream/recent?after=<uid>` strictly-after, in-order —
was verified in **Phase 7 Fault 4**).

---

## New defects

### DEF-D9-007 — `stop` lags at low replay speed (P3)
- **Observed:** at `speed=1`, `POST /v1/replay/stop` returns `stopping` and the
  status stays `stopping` until the loop's current paced `asyncio.sleep` finishes
  (can be minutes at speed 1). `reset` (which `task.cancel()`s) is immediate.
- **Root cause:** the replay loop only checks `_stop_requested` **between events**
  (`replay.py:518`); at low speed the inter-event `asyncio.sleep(delta_ms/1000/
  speed)` blocks that check. At `speed=60` (the demo speed) inter-event sleeps are
  ≤ ~4.6 s (audit-measured), so `stop` acknowledges within ~5 s — verified in C1
  (`stop` at 109/821 → `stopped` promptly).
- **Severity:** P3 — **not on the demo path** (speed 60 stops promptly), not a
  stale `running` (honestly `stopping`), and `reset` always recovers immediately.
- **Fix (Phase 13):** replace the bare `asyncio.sleep(delta/speed)` with a
  `stop`-aware wait (`asyncio.wait_for(self._stop_event.wait(), delta/speed)`).
- **Evidence:** §D; `phase-8-replay-console.log`.

### DEF-D9-008 — `reset` does not release persisted `enforcement_action` rows (P3)
- **Observed:** after ~20 replay + reset cycles, `enforcement_action` holds **105
  rows, 104 with `released_at IS NULL`**, while `open_incidents = 0` (every
  incident CLOSED). `GET /v1/demo/cotenant-ip` returns an IP even immediately
  after a fresh `reset` (`198.51.100.180`).
- **Root cause:** `replay.py::_close_open_incident_rows()` (called by `reset()`)
  calls `resolve_incident(…, resolution="reset")` to CLOSE each open incident but
  **never calls `release_enforcement_for_incident()`**. The operator resolve route
  (`routes_incidents.py:172`) *does* call it — so operator-resolved incidents
  release their enforcement, but reset-force-closed ones do not.
- **Severity:** P3. The live `PolicyEngine` ceiling **is** cleared by reset (in
  the `cleared` map). The orphan rows are a persisted audit-trail artifact. In the
  normal demo flow (attack → incidents open → click co-tenant) `cotenant-ip`
  orders by `(incident_id IS NOT NULL) DESC, applied_at DESC, expires_at DESC`, so
  the **current** run's freshly-enforced IP sorts first and the demo is
  unaffected. The stale rows only surface if `cotenant-ip` is called when nothing
  is currently enforced.
- **Fix (Phase 13):** one line — add `release_enforcement_for_incident(conn,
  row["incident_id"], _now_ms())` inside the `_close_open_incident_rows` loop,
  matching the operator path. Optionally add `enforcement_released: N` to the
  `cleared` map.
- **Evidence:** §"Refresh" DB query; `repository.py:491` vs `replay.py:355-368`.

---

## Observations (not defects)

- **AUDIT-017** — the "Attempts · 5 min" tile fix is verified at source
  (`D1Live.jsx:24-30` reads `feature_snapshot.attempts_per_merchant_5m`, a
  server number, **not** the 200-cap SSE buffer). Live: the field is populated and
  is a real sliding window (5 → 12 → decays on an `easy` run). The demo tiers do
  not naturally produce > 200 attempts in a 5-event-minute window (`easy` peaks at
  ~12), but the **frontend buffer cap is architecturally removed** — no client
  buffer limit can decide the metric. **PASS with a coverage note.**

---

## Verdict

**Phase 8 COMPLETE — the repeatability gate PASSES.** Every tier at speed 0 (×2)
and speed 60 completes to `finished` with the exact seeded event count
(`easy`=821, `medium`=701, `hard`=508, `evasive`=390); every launch mints a fresh
`run_id`; every `reset` returns 200 with a full `cleared` map and drives the Redis
window store back to floor 0; `attempt_score` parity holds on all 19 runs; stop
returns the true terminal snapshot; a repeated run of the same tier is not
swallowed. **The complete demo is repeatable.**

Two **P3** defects (DEF-D9-007 stop-lag at speed 1; DEF-D9-008 reset leaves
persisted enforcement rows) — neither on the demo path, both one-line Phase-13
fixes.
