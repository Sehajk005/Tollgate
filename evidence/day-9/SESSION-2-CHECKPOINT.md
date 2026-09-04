# Day 9 — Session 2 checkpoint (Phases 4–11)

**Date:** 2026-09-03 · **Branch:** `day-9` · **HEAD:** `9c2de48`
**Resumed from:** Session 1 checkpoint (`61a415c`, Phases 0–3 complete).
**Executed:** `09-DAY-9-QA-AND-DEMO-PLAN.md` Session B (Phases 4–11).

**No source code changed this session** — `git diff 61a415c..HEAD` outside
`evidence/` and `DAY-9-*.md` is empty. All defects found are inventoried, not
fixed (plan §12 Session B: "no fixes applied beyond P0 blockers that prevent
further testing" — none blocked testing).

---

## Phase status

```
Phase 4  — Backend / API QA .................... COMPLETE
Phase 5  — Detection / Evaluation .............. COMPLETE  (release gate PASSES)
Phase 6  — Security ........................... COMPLETE  (S-5 NOT triggered)
Phase 7  — Reliability / Failure Injection ..... COMPLETE
Phase 8  — Replay Lifecycle ................... COMPLETE  (repeatability gate PASSES)
Phase 9  — Historical Defect Reverification .... COMPLETE  (20 PASS / 4 PARTIAL / 0 FAIL)
Phase 10 — Performance ....................... COMPLETE
Phase 11 — UI / UX ........................... COMPLETE
```

Phases 12–15 NOT started (correct — Session 3).

---

## Tests

| Suite | Result | Notes |
|---|---|---|
| **pytest** `tests/ -q` | **636 passed / 1 failed / 2 xfailed** | the 1 failure = `test_d6_provenance::test_corpus_identity` (**DEF-D9-003**, P2 known limitation — byte-hash on a gitignored, non-deterministically-built corpus; zero metric impact). |
| pytest — reversed file order (AUDIT-010) | **636 passed / 2 failed / 2 xfailed** | failures = DEF-D9-003 + `test_sse::test_scored_event_reaches_sse_stream` (timing flake, passes 1/1 isolated). `test_day2_e2e` passes both backends → hermeticity holds. |
| pytest — security subset | 48 passed | |
| pytest — detection/eval subset | 196 passed / 1 failed (DEF-D9-003) | |
| **Vitest** `test:run` | **205 passed / 21 files** | re-run this session, unchanged |
| Vitest coverage | 97.9 / 86 / 98.5 / 97.9 (≥ 85/85/80) | Session 1 baseline; no frontend code changed |
| **Playwright** `test:e2e` | **68** (17 × 4 viewports) | Session 1 baseline; no frontend code changed. Covers `#/metrics` responsive at 1536/1280/768/390. |
| **`verify_60x --gate 60x --faulthandler`** | **PASS 9/9** (clean Docker VM, 406 s) | `no_crash` (no SIGSEGV), `health_p99` 16.9 ms, `loop_lag` 0.0 s, `rss_growth` −2.9 MB, `checkout_interleaved` ✓ |
| **`verify_60x --gate crossing`** | **PASS** (112 s) | 5 reps × both orders, bounded discontinuity, no spin |
| **`verify_60x --gate throughput`** | **FAIL (speed sub-checks only)** | 20/20 finished all 821/821; `identical_event_counts`/`no_run_was_swallowed`/`attempt_score_row_parity`/`redis_returns_to_floor`/`drainer` all PASS; `rss_growth` −0.4 MB. FAIL: `each_under_5s` + `throughput_ok` → **DEF-D9-001** (serial-loop throughput assumption, not a serving inefficiency — compute p99 = 12 ms). *(A pressure run with the full stack up produced 7 FAILs incl. 3 Redis-socket-timeout run failures — environment, restored by `compose down` + fresh redis.)* |
| **D6 evaluation** — `eval.harness` + `diff_d6.py` | **0 substantive metric differences** | `--ignore provenance` → 0 diffs; `report.md` byte-identical mod provenance; `d6.json` SHA `29edcb22…` unchanged. |
| security (live harness) | 33/35 PASS + 2 harness-expectation (422-before-401, by-design) | **S-5 NOT triggered** |
| reliability (6 fault injections) | all 6 fail safely | no 5xx where fail-open required, no wedge, no leak, recovery works |
| replay lifecycle (19 launches) | 19/19 distinct run_ids; A 16/16, B 3/3, C 5/5 | repeatability gate PASSES |
| performance — `/v1/score` compute p99 | **12 ms** seq / 17 ms 10-conc / 59 ms burst | TRD p99 < 100 ms **MET with margin** |
| accessibility (axe WCAG AA) | 1 violation `#/metrics`, 2 `#/live` | `color-contrast` → **DEF-D9-009** (P3) |

---

## Historical defects (AUDIT-001..024)

```
AUDIT-001 -> PASS      AUDIT-013 -> PARTIAL (Session-3 rehearsal check)
AUDIT-002 -> PASS      AUDIT-014 -> PASS
AUDIT-003 -> PASS      AUDIT-015 -> PARTIAL (Session-3 rehearsal check)
AUDIT-004 -> PASS      AUDIT-016 -> PASS
AUDIT-005 -> PASS      AUDIT-017 -> PASS (coverage note: >200 threshold not
AUDIT-006 -> PASS                        exercised by demo tiers; cap removed)
AUDIT-007 -> PASS      AUDIT-018 -> PASS
AUDIT-008 -> PASS      AUDIT-019 -> PASS (typed card_hash + BIN reach the scorer)
AUDIT-009 -> PARTIAL   AUDIT-020 -> PASS
   (rehearsal check)   AUDIT-021 -> PASS
AUDIT-010 -> PASS      AUDIT-022 -> PARTIAL (Session-3 rehearsal check)
AUDIT-011 -> PASS      AUDIT-023 -> PASS
AUDIT-012 -> PASS      AUDIT-024 -> PASS
```

**20 PASS · 4 PARTIAL · 0 FAIL.** The 4 PARTIAL (009/013/015/022) are all
source-verified + backend-verified; only a live browser re-run is outstanding,
blocked by renderer instability this session — none shows any sign of the
original defect. Carried as Session-3 Rehearsal-#1 checks.

---

## New defects (Session 2)

### DEF-D9-005 — `POST /v1/replay/start` accepts an unknown `tier`
- **Severity** P3 · **Root cause** `ReplayStartBody.tier` unconstrained `str`; an
  out-of-set value → `202` then async `KeyError` → `failed` (terminal, recoverable).
- **Fixed?** No — Phase 13. Not on the demo path (DC strip sends `TIER_OPTIONS` only).
- **Verification** `POST {"tier":"bogus"}` → `422` with operator-readable detail.
- **Evidence** `evidence/day-9/phase-4-api-qa.md` §2.

### DEF-D9-006 — `GET /v1/incidents?state=` is a dead parameter
- **Severity** P3 · **Root cause** `list_incidents(state=…)` never forwards `state`;
  `read_open_incidents` hard-codes `WHERE state != 'CLOSED'`.
- **Fixed?** No — Phase 13. No functional impact (dashboard sends the default only).
- **Verification** `?state=closed` returns only CLOSED (or the param is removed).
- **Evidence** `phase-4-api-qa.md` §2.

### DEF-D9-007 — `stop` lags at low replay speed
- **Severity** P3 · **Root cause** the replay loop checks `_stop_requested` only
  between events; a low-speed paced `asyncio.sleep` blocks it. `stop` returns
  `stopping` and stays there until the sleep ends (minutes at speed 1). `reset`
  cancels immediately.
- **Fixed?** No — Phase 13. **Not on the demo path** — at speed 60, `stop`
  acknowledges within ~5 s (Phase 8 C1: stop at 109/821 → `stopped` promptly).
- **Verification** speed-1 `stop` → status reaches a terminal state within ~2 s.
- **Evidence** `evidence/day-9/phase-8-replay-lifecycle.md` §D.

### DEF-D9-008 — `reset` does not release persisted `enforcement_action` rows
- **Severity** P3 · **Root cause** `_close_open_incident_rows()` CLOSES incidents
  but never calls `release_enforcement_for_incident()` (the operator resolve route
  does). 104 orphan rows (`released_at IS NULL`) after ~20 run+reset cycles.
- **Fixed?** No — Phase 13. Demo unaffected — live `PolicyEngine` ceiling IS
  cleared; `cotenant-ip` sorts the current run's IP first (`applied_at DESC`).
- **Verification** after `reset` with 0 open incidents, `enforcement_action WHERE
  released_at IS NULL` = 0.
- **Evidence** `phase-8-replay-lifecycle.md` §"New defects".

### DEF-D9-009 — `--tg-primary` small-text contrast below WCAG AA
- **Severity** P3 · **Root cause** `--tg-primary` `#6366f1` on `#12161b` at
  12–14 px = **4.06:1** (< AA 4.5:1) — active nav item + DC-strip Launch button.
- **Fixed?** No — Phase 13. Legible; under the plan's stated threshold.
- **Verification** axe `color-contrast` clean on `#/live` and `#/metrics`.
- **Evidence** `evidence/day-9/phase-11-ui-ux.md` §6.

### DEF-D9-010 — the storefront normal checkout is broken  ⚠️ **P1**
- **Severity** **P1** — blocks DEMO READY (plan: "Zero unresolved P1").
- **Description** Every "Pay" click shows a false **"✓ Order confirmed"** (S5)
  with **no `/v1/score` request, no scored attempt, no dashboard event**. App
  Flow J6 step 1 (normal checkout) is broken.
- **Root cause** `S2Checkout.jsx:222` `onClick={pay}` → React passes the
  `SyntheticEvent` as `pay(extraHeaders = {})`'s `extraHeaders`, spread into the
  `fetch` `headers` → `TypeError: Failed to execute 'fetch' on 'Window': Invalid
  value` → caught → `resolveClientOutcome` → `"fail_open"` → S5. Introduced
  Phase 3 (Session 1) when `pay()` gained the `extraHeaders` param. `payAsCotenant`
  (`:255`) is unaffected. The scorer / proxy / API key all work (direct browser
  `fetch` with the key → 200 + persisted).
- **Fixed?** **No** — Phase 13, **top priority.** 1-line fix: `onClick={() => pay()}`
  + an e2e test that drives a real checkout and asserts a persisted `attempt_score`.
- **Verification** click "Pay" in the browser → a decision routes correctly AND a
  matching `auth_attempt` row persists with the typed BIN.
- **Evidence** `phase-11-ui-ux.md` §4.

### Carried from Session 1 (unchanged status)
- **DEF-D9-001** (P2) — `verify_60x --gate throughput` speed sub-checks fail;
  root cause established (serial-loop assumption; compute p99 = 12 ms << TRD 100 ms).
  Disposition: `Decisions.md` re-scope of the thresholds (Phase 13), not a test
  change. **Not a demo blocker.**
- **DEF-D9-002** (P3) — FIXED in Phase 2 (Compose scorer logging). Manual-path
  observability still applies; reopen only if required.
- **DEF-D9-003** (P2) — RECONCILED in Phase 5 as a documented **known limitation**;
  0 substantive metric differences; S-6 not triggered. Suite carries 1 permanent
  red (`test_corpus_identity`) until reworked post-Day-9.
- **DEF-D9-004** (P3) — flood shed marginal on the single-worker dev scorer; the
  shed rung itself is proven (`test_admission_shed.py`). Phase 13 (raise flood
  concurrency).

---

## D6 integrity

| | |
|---|---|
| Baseline `eval/outputs/d6.json` SHA-256 | `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737` |
| Current `eval/outputs/d6.json` SHA-256 | `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737` — **MATCH** |
| Baseline `models/audit.json` SHA-256 | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` |
| Current `models/audit.json` SHA-256 | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` — **MATCH** |
| **S-6 triggered?** | **NO** — every frozen evaluation artifact is byte-identical to Phase 0. |
| DEF-D9-003 (corpus SHA drift) | **Reconciled in Phase 5.** `eval.harness` regenerated twice (deterministic, A ≡ B); `diff_d6.py` vs the committed `d6.json` with the plan's exact ignores → **exactly 2 changed leaves, both provenance metadata** (`corpus_db_sha256` = the drift itself, `generation_command` = invocation echo). `diff_d6.py … --ignore provenance` → **`0 substantive difference(s)`.** The corpus's `store_baseline.updated_at` (the only drift) is metadata the offline harness never reads; `d6.json` pins `policy_version: 1` (intact). `d6.json` was **left untouched** (Plan §8). `test_corpus_identity` stays RED as a documented known limitation. |
| **D6 diff result** | **PASS — zero substantive metric differences.** Every block (1–6 + tier_e) reproduces bit-for-bit; `report.md` byte-identical modulo volatile provenance. |

---

## Performance

| Metric | Value | Target | Verdict |
|---|---|---|---|
| `/v1/score` compute **p50** | 4 ms (seq) / 6 ms (10-conc) / 15 ms (burst) | — | — |
| `/v1/score` compute **p95** | 8 / 12 / 33 ms | — | — |
| `/v1/score` compute **p99** | **12 / 17 / 59 ms** | < 100 ms (TRD §1) | **MET (wide margin)** |
| round-trip p50 | ~55 ms | — | (Windows→container loopback dominates) |
| Throughput (serial single client) | ~13.5 req/s / ~305 aps mean (soak) | ≥ 400 aps (`verify_60x`) | **MISS** → DEF-D9-001 (serial-loop assumption; not a serving inefficiency) |
| Throughput (10 concurrent) | ~400 req/s aggregate, all 200 | — | healthy |
| **Actual 60× factor** | **≈ 59×** (`easy`/60/nopace 183 s) | 60× nominal | marginal; matches prior audit 58.5× — known limitation |
| **20-run soak** | 20/20 finished, all 821/821, `identical_event_counts`=[821] | — | **PASS** (clean VM) |
| CPU / event loop | `loop_lag_warnings = []`, `loop_lag_max_s = 0.0` | no ≥ 2 s block | **PASS** |
| Memory (soaks) | `rss_growth_mb` = **−0.4 / −2.9** | no leak | **PASS** (negative growth) |
| Availability rungs | full 12 ms → fail-open 10 ms (faster) → shed (DEF-D9-004 marginal on dev scorer) | — | full + fail-open PASS |
| LLM on the scoring path | `NARRATOR_BACKEND=template`, `narrator_call` = 0, Decision 98 out-of-band | never | **PASS — LLM off the path** |

---

## UI / UX

| Surface | Result |
|---|---|
| **Desktop (1536)** — dashboard D0/D1/D3/D6 | **PASS** — every AUDIT UI fix present; D6 honest (B0 not omitted, no `0.000`, rupee gap structural, every metric with its measurement conditions); no PAN/card-hash leakage; Stream Rail full-width; `SSE: live` chip; finished-run state clean |
| **Tablet (768) / Mobile (390)** | **PARTIAL** — `#/metrics` covered by the green Playwright suite (17 × 4 viewports); `#/live` / `#/incident` at 390/768 not visually verifiable in this browser env → **Session-3 rehearsal check** |
| **Accessibility** | **1 axe violation** (`#/metrics`) / **2** (`#/live`): `color-contrast` on `--tg-primary` small text → **DEF-D9-009 (P3)**. 21–22 axe passes. Focus styles + reduced-motion handled. |
| **AUDIT-019** (CRITICAL recheck) | **PASS** — typed PAN `5544 3322 1100 9988` → intercepted `/v1/score` body: `card_hash` = exact SHA-256 of the typed digits, `bin=554433`, `last4=9988`. Fields wired, not decorative. |
| **Storefront normal checkout** | **BROKEN — DEF-D9-010 (P1)** — `onClick={pay}` passes the React event into the fetch headers → false "Order confirmed" with no scored attempt. |

---

## Git

| | |
|---|---|
| Final HEAD | `9c2de48` |
| Commits this session (7) | `90bf189` Phase 4 · `74f6dbe` Phase 5 · `c574c08` Phase 6 · `d2a050a` Phase 7 · `15899c8` Phase 8 · `7289267` Phase 10 · `9c2de48` Phases 9 + 11 |
| Working tree | **clean** |
| Source code changed | **none** — evidence + `DAY-9-*.md` docs only (`git diff 61a415c..HEAD` outside those paths is empty) |

---

## Unresolved defect inventory (for Session 3 Phase 13)

| ID | Sev | One-line | Fix effort |
|---|---|---|---|
| **DEF-D9-010** | **P1** | storefront normal checkout broken (`onClick={pay}`) | 1 line + e2e test — **do first** |
| DEF-D9-001 | P2 | `verify_60x --gate throughput` speed sub-checks | `Decisions.md` re-scope entry |
| DEF-D9-003 | P2 | `test_corpus_identity` red (corpus byte-hash) | known limitation — no Day-9 action; rework the check post-Day-9 |
| DEF-D9-004 | P3 | flood shed marginal on the dev scorer | raise flood concurrency |
| DEF-D9-005 | P3 | `replay/start` accepts unknown tier | tier allow-list → 422 |
| DEF-D9-006 | P3 | `/v1/incidents?state=` dead parameter | honour or remove |
| DEF-D9-007 | P3 | `stop` lags at speed 1 | stop-aware sleep |
| DEF-D9-008 | P3 | `reset` leaves persisted enforcement rows | 1 line in `_close_open_incident_rows` |
| DEF-D9-009 | P3 | `--tg-primary` small-text contrast 4.06:1 | token / ground adjustment |

**P0: none. P1: 1 (DEF-D9-010). P2: 2 (DEF-D9-001, DEF-D9-003). P3: 6.**

Stop conditions: **S-1..S-6 NOT triggered.** (S-6 explicitly checked — frozen
artifact SHAs byte-identical to Phase 0.)

---

## Exact next step

> `NEXT SESSION SHOULD RESUME AT PHASE 12 — DEMO REHEARSAL #1`

Session 3 must, before/within Phase 13, **fix DEF-D9-010 first** (the storefront
checkout is on the demo path). Also carry into Rehearsal #1 the 4 PARTIAL AUDIT
checks (009/013/015/022) and the 390/768 responsive check for D1/D3.
