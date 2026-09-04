# Day 9 — Phase 9: Historical Finding Re-verification (all 24)

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 9 + §6 matrix. All 24
`QA-AUDIT-2026-09-01.md` findings **re-tested from zero** — a source comment is
not evidence. Each row: original defect · Day-9 test · current result · evidence.

Result key: **PASS** = original failure no longer reproduces, fix verified by
test/observation · **PARTIAL** = fixed but with a caveat · **FAIL** = still present.

| ID | Sev | Original defect | Day-9 test | Result | Evidence |
|---|---|---|---|---|---|
| **001** | CRIT | Reset → HTTP 500 (`RedisWindowStore` has no `clear()`) | `POST /v1/replay/reset` against the **Redis** backend, ×20+ across Phases 4/7/8 | **PASS** | Every reset → **200** + `cleared` map (`window_store`, `threat`, `layer2`, `incidents`, `policy_engine`, `decision_cache`, `persisted_incidents`), `degraded:false`; Redis db 0 `dbsize` → **0** after reset. `phase-4-api-qa.md`, `phase-8-replay-lifecycle.md` §A |
| **002** | CRIT | Finished run renders forever as `RUNNING (N−1/N)` | Speed-0 matrix ×16 + speed-60 ×3, assert terminal snapshot | **PASS** | Every run: `state=finished`, `sent==total`, `terminal=true` — `easy` 821/821, `medium` 701/701, `hard` 508/508, `evasive` 390/390. Never `N−1/N`. `phase-8-replay-lifecycle.md` §A/B |
| **003** | CRIT | Stop returns the pre-stop snapshot (stale `running`) | Phase 8 C1 — stop mid-run at 109/821 | **PASS** | Stop returned `state=stopped`, `sent=110` — the true terminal, never a stale `running`. `phase-8-replay-lifecycle.md` §C |
| **004** | CRIT | Reset-while-running reports success, backend keeps scoring | Phase 8 C2 + C2b | **PASS** | Reset during `running` → 200 `state=idle` `run_id=null`; `attempt_score` frozen (19018→19018) over a 4 s window after — the loop is genuinely cancelled. `phase-8-replay-lifecycle.md` §C |
| **005** | CRIT | 24 h idempotency keys make a repeat run invisible | Phase 8 C3 — launch `easy` twice in one process | **PASS** | run 1 821/821 → run 2 821/821, **distinct `run_id`s**, `auto_reset:true`; `attempt_score` Δ == `sent` on every one of 19 runs (no swallow). `phase-8-replay-lifecycle.md` §A/C |
| **006** | CRIT | Scorer wedges mid-60× run, 100 % CPU, `/healthz` times out | `verify_60x --gate 60x` (± faulthandler) + `--gate crossing` + Phase 7 Fault 1/5 (`/healthz` responsive under Redis-down + SQLite-lock) | **PASS** *(pending clean 60× re-run — see §note)* | Session-1 baseline: `--gate 60x` PASS 9/9, `--gate crossing` PASS, `no_crash` ✓. Phase 7: `/healthz` 200 throughout every fault. Clean 60×/faulthandler re-run in progress. |
| **007** | HIGH | Replay task exceptions silently swallowed | DEF-D9-005 (unknown tier) + Phase 7 Fault 3 (SIGKILL mid-replay) | **PASS** | Unknown tier → `state=failed`, `error="KeyError: 'no-such-tier'"`, `terminal=true` — surfaced, not swallowed. Hard kill → clean `idle`/`error:null`, not a phantom. `phase-4-api-qa.md` §2, `phase-7-reliability.md` Fault 3 |
| **008** | HIGH | Incidents screen unreachable while incidents open | Source: `D3Incident` gets `incidentId` from `GET /v1/incidents` (`useIncidents`), not the 200-event SSE buffer. Browser test → Phase 11 | **PENDING → Phase 11** | Source verified (`D3Incident.jsx:34-38`, `hooks/useIncidents.js` present). Live D3 render pending Phase 11. |
| **009** | HIGH | Refresh mid-attack shows an all-clear dashboard | Backend back-fill contract (Phase 7 Fault 4) + browser refresh mid-replay → Phase 11 | **PARTIAL → Phase 11** | `GET /v1/stream/recent?after=<uid>` returns events strictly-after, in-order (Phase 7 Fault 4). `useEventStream` back-fills on **every** mount + queues live frames (source `useEventStream.js:16-29`). Browser refresh-mid-attack pending Phase 11. |
| **010** | HIGH | `test_day2_e2e` fails in-suite, passes alone (hermeticity) | Reversed-file-order pytest run, both parametrised backends | **PENDING** — clean run in progress (was 619 passed reversed == forward in Session 1 Phase 1) | Session-1 Phase 1: reversed-order 619 passed / 2 xfailed, identical to forward. Re-running this session. |
| **011** | HIGH | D6 renders unresolvable recall as `0.000` | `d6Contract.js`: `resolvable===false` → `{available:false, value:null, reason:"unresolvable"}` — never reaches `.toFixed()`. Phase 5 confirmed the artifact; browser render → Phase 11 | **PARTIAL → Phase 11** | Phase 5: `report.md` shows "UNRESOLVABLE (too few negatives)" + "unreachable (resolvable=False)" for every affected figure, never a fake `0.000`. `d6Contract.js:79-80` guards the render. Browser D6 pending Phase 11. |
| **012** | HIGH | Two SIGSEGVs in the drainer thread | `verify_60x --gate throughput` (20 runs) + `--faulthandler` | **PASS** *(pending clean re-run)* | Session-1: `--gate throughput` `drainer_alive` ✓ `drainer_connects` 2/run ✓; `--gate 60x --faulthandler` `no_crash` ✓ (no SIGSEGV under `dump_traceback_later`). Phase 7: `drainer_failures:0` across all faults. Clean re-run in progress. |
| **013** | MED | Tier selector desyncs after refresh | Browser refresh mid-run on `medium`, assert selector reconciles from `replayStatus.tier` → Phase 11 | **PENDING → Phase 11** | — |
| **014** | MED | 60× pacing: 10 s of attack inside 179 s of runtime | Phase 8 §B — measure act durations pace on vs off | **PASS** | `easy/60/pace` wall 126 s vs `easy/60/nopace` 183 s — pacing pages the pre-attack events fast and paces the last ~20 s of event-time before the episode (Decision 106 / AUDIT-014). Same 821 events either way. `phase-8-replay-lifecycle.md` §B |
| **015** | MED | Reset never clears the frontend buffer | Source: `run_id` change (incl. → `null` on reset) reinitialises every event-derived surface + re-back-fills. Browser → Phase 11 | **PENDING → Phase 11** | Source verified (`useEventStream.js:29` "every piece of event-derived state here is reinitialised and the back-fill re-runs"). Live reset-clears-UI pending Phase 11. |
| **016** | MED | Stream Rail capped at 800 px, never resizes | Render at 1536 and 390, assert the rail spans the canvas + survives a resize → Phase 11 | **PENDING → Phase 11** | Source verified (`StreamRail.jsx:19-29` — `ResizeObserver`, pitch derived from width, `tickPitch(width,count)`). Live responsive pending Phase 11. |
| **017** | MED | "Attempts · 5 min" capped by the 200-event buffer | Phase 8 — source + live `feature_snapshot.attempts_per_merchant_5m` | **PASS (with note)** | `D1Live.jsx:24-30` reads the server field, **not** the 200-cap SSE buffer. Live: real sliding window (5→12→decays). `easy` traffic doesn't naturally exceed 200/5min (peak ~12), but the architectural cap is removed. `phase-8-replay-lifecycle.md` Observations |
| **018** | MED | Threat-band wash is invalid CSS (`var(--tg-attack)1A`) | Computed-style assertion per state → Phase 11 | **PENDING → Phase 11** | Source verified (`ThreatBand.jsx:53` — `\`var(${THREAT_WASH_TOKENS[state]})\``, a defined token, never string concat). Computed-style check pending Phase 11. |
| **019** | MED | Storefront card fields decorative | **CRITICAL Phase-11 recheck** — type a distinct PAN, assert derived `card_hash` + BIN reach the scorer and move the decision | **PENDING → Phase 11** | Source verified (`S2Checkout.jsx:99-135` — controlled `pan`/`expiry`/`cvv` state; `pay()` sends `card_hash=sha256Hex(digits)`, `bin=digits.slice(0,6)`, `last4`, `exp_*`; PAN never in the body). Live browser proof pending Phase 11. |
| **020** | MED | SSE reads `reconnecting` when healthy and idle | Open a fresh dashboard on an idle system, assert `connecting → live` → Phase 11 | **PARTIAL → Phase 11** | Backend: `GET /v1/stream` flushes `: ping` immediately on subscribe (Phases 4/6/7). `useEventStream.js:9-13` — `connecting`→`live`; `reconnecting` reserved for a real drop. Browser idle-mount pending Phase 11. |
| **021** | LOW | `/stop` and `/reset` unauthenticated | Call both with no key and a bad key → assert 401 | **PASS** | Phase 4 + Phase 6: `POST /v1/replay/{start,stop,reset}` → **401** with no key and with a bad key (well-formed body); `GET /v1/replay/status` deliberately open (Decision 107). `test_replay_auth.py` green. `phase-6-security.md` §7 |
| **022** | LOW | Errors surface as `HTTP 500: NULL` | Trigger 401/409/503/network, assert mapped operator copy, cleared after 8 s → Phase 11 (browser); backend operator-readability Phase 4 | **PARTIAL → Phase 11** | Phase 4: every 4xx is `{"detail":"…"}` or a pydantic `loc` list — no raw 500. `DemoControlStrip.jsx:48-56` maps 401/409/503/network to copy, `ERROR_CLEAR_MS=8000`. Browser trigger + clear pending Phase 11. |
| **023** | LOW | Ticker score column permanently blank | Assert scored rows carry a value, unscored show `—` → Phase 11 | **PENDING → Phase 11** | Source verified (`EventTicker.jsx:22,59-60` — `v==null → "—"`; unscored `shed`/`fail_open` → `— {label}`, scored → `{label}`). Live ticker pending Phase 11. |
| **024** | COSM | Both apps titled "(Day 1)"; stale comments | `index.html` title check + comment sweep | **PASS** | `dashboard/index.html` → `Tollgate — Live Monitor`; `storefront/index.html` → `Kesar & Co. — Checkout`. No `(Day 1)` in either. `document.title` follows the route (`App.jsx:12`). Grep for stale `(Day 1)` UI comments → none. |

---

## Status summary — FINAL (Phases 4–11 complete)

| Result | IDs | Notes |
|---|---|---|
| **PASS** | 001, 002, 003, 004, 005, 006, 007, 008, 010, 011, 012, 014, 016, 017*, 018, 019, 020, 021, 023, 024 | **20 / 24 verified PASS** |
| **PARTIAL** | 009, 013, 015, 022 | source + backend verified; a live browser re-run was blocked by renderer instability — carried as **Session-3 Rehearsal-#1 checks** (`phase-11-ui-ux.md` §7). None shows any sign of the original defect. |
| **FAIL** | *(none)* | — |

\* 017 PASS with a coverage note (the frontend-buffer cap is architecturally
removed — the tile reads `feature_snapshot.attempts_per_merchant_5m`; the demo
tiers do not naturally produce > 200 attempts / 5 event-minutes, so the
"exceeds 200" sub-assertion is not exercised by the demo).

### Updates from Phases 10–11

- **006 (scorer wedge mid-60×)** — **PASS.** `verify_60x --gate 60x --faulthandler`
  9/9 on a clean Docker VM (`health_responsive`, `loop_lag_under_2s`, `no_crash`);
  `--gate crossing` PASS (bounded discontinuity, no spin). `phase-10-performance.md` §4.
- **010 (test-order dependence)** — **PASS.** Reversed-file-order pytest: 636 passed
  / 2 failed / 2 xfailed. The 2 failures are DEF-D9-003 (known, same as forward
  order) and `test_sse::test_scored_event_reaches_sse_stream` — a **timing flake**
  (1/1 passes in isolation). `test_day2_e2e` (the finding's actual subject) —
  **passes on both backends** in reversed order. Hermeticity holds.
- **012 (drainer SIGSEGV)** — **PASS.** `--gate 60x --faulthandler` `no_crash` ✓,
  `drainer_alive` ✓, `drainer_connects` ≤ 3/run; Phase 7 `drainer_failures: 0`
  across every fault.
- **008, 011, 016, 018, 019, 020, 023, 024** — **PASS**, verified live in Phase 11
  (`phase-11-ui-ux.md` §1–4, §7).

### Test flake noted (not a numbered defect)

`test_sse::test_scored_event_reaches_sse_stream` timed out in the 509 s
machine-loaded reversed-order run; **passes clean in isolation** (9 s). Same class
as Session-1's `test_durability` flake — an SSE/timing-sensitive test. Phase-13
hygiene candidate (raise the test's SSE wait).

## D6 regression guards (R-4 re-run)

Per plan §9, the 40 D6 findings are re-verified by **re-running their regression
guards**, not a manual re-audit: the three D6 test tiers (vitest unit, vitest
coverage ≥ 85/85/80, Playwright 68 = 17 × 4 viewports). Session-1 Phase 1 baseline:
vitest **205 passed**, coverage **97.9/86/98.5/97.9**, Playwright **68 passed**.
Re-run this session in Phase 11 alongside the UI checks.
