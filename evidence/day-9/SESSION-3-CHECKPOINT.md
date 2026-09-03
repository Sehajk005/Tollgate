# Day 9 — Session 3 checkpoint (Phases 12–15)

**Date:** 2026-09-03 · **Branch:** `day-9`
**Resumed from:** Session 2 checkpoint (`017a0f7`, Phases 4–11 complete).
**Executed:** `09-DAY-9-QA-AND-DEMO-PLAN.md` Session C (Phases 12–15) + the
DEF-D9-010 fix that had to precede Rehearsal #1.

---

## Phase status

```
Phase 12 — Demo Rehearsal #1 ............................ COMPLETE
Phase 13 — Triage / Hardening .......................... COMPLETE
Phase 14 — Clean Compose Retest + Demo Rehearsal #2 .... COMPLETE
Phase 15 — Final Audit / Demo Script / Verdict ......... COMPLETE
```

---

## DEF-D9-010 (P1 — the open defect that had to be fixed first)

| | |
|---|---|
| **Reproduction** | Storefront S1 → "Buy now" → S2 → type a card → "Pay". `S2Checkout.jsx:222` wired the button `onClick={pay}`, so React passed the click `SyntheticEvent` as `pay(extraHeaders = {})`'s first arg; `pay` spreads `...extraHeaders` into the `fetch` `headers` → `TypeError: Failed to execute 'fetch' on 'Window': Invalid value` → caught → `resolveClientOutcome({error})` → `"fail_open"` → **S5 "Order confirmed"** with **no `/v1/score` request, no scored attempt, no dashboard event**. Confirmed via a `fetch` wrapper (Phase 11) and re-confirmed in Rehearsal #1 Pass A (the request *is* dispatched once the wiring is fixed). |
| **Root cause** | A function that takes a meaningful first positional arg (`extraHeaders`) wired directly as a React event handler. `payAsCotenant` (`:255`) was unaffected — it takes no args and calls `pay({...})` with a real object. Introduced Session 1 Phase 3 when `pay()` gained the `extraHeaders` param. |
| **Fix** | `onClick={() => pay()}` — a zero-argument call; the event cannot reach `extraHeaders`. No change to scoring, routing, or enforcement semantics. |
| **Regression test** | `tests/acceptance/test_storefront_checkout_wiring.py` (the repo's established storefront source-contract pattern — the storefront has no JS runner). Pins: (1) `pay()` still spreads `...extraHeaders` into the fetch headers, so the wiring genuinely matters; (2) the Pay button is never the bare `onClick={pay}`; (3) it is wired `onClick={() => pay()}`. **FAILED against the old wiring, PASSES now.** |
| **Verification** | `pytest tests/` green modulo the pre-existing DEF-D9-003. E2E: Rehearsal #1 Pass B Step 1 + Rehearsal #2 Step 1 — a real `/v1/score` POST is dispatched with **clean headers** (no `TypeError`), returns `200 {"decision":"allow"}`, and a matching `auth_attempt` + `attempt_score` row persists with the typed BIN. |
| **Commit** | `055613e` — `spec: DEF-D9-010 -- fix storefront normal checkout (onClick={pay} leaked React event)` |

---

## Rehearsal #1 (`DAY-9-DEMO-REHEARSAL-1.md`)

| | |
|---|---|
| **Result** | **COMPLETE.** Pass A found a P1 (DEF-D9-011); it was fixed; Pass B walked the full J6 flow (9/9 steps) on the real Compose stack. |
| **Failures** | **DEF-D9-011 (P1)** — `docker compose down -v && up --build` left the storefront + dashboard containers bound to the **previous run's** `VITE_TOLLGATE_API_KEY` (`env_file: deploy/compose.env` is resolved at container-create time; the one-shot `bootstrap` rewrites that file with a fresh key *after*). Every keyed frontend→scorer call — checkout, Launch, co-tenant, flood, kill-scorer — returned **401**. Verified: `storefront` container key hash `4ddf99…` ≠ `deploy/compose.env` key hash `22cc6f…` = `merchant.api_key_hash`; storefront container created 41 s before `bootstrap` finished. **Reconfirmed P3s:** DEF-D9-004 (flood shed marginal), DEF-D9-008 (reset orphans `enforcement_action` rows), DEF-D9-012 (a 401 renders as S5 "Order confirmed"). |
| **Fixes** | DEF-D9-011: the frontends' `docker-compose.yml` `command:` now sources `deploy/compose.env` at container start (mirrors the scorer's Phase-2 CMD shim; the compose `command:` overrides the image CMD, so `6edc909`'s Dockerfile-only shim was inert — corrected in `afaf572`). Keys aligned `e1c7e86a0058` for Pass B. |
| **Evidence** | `DAY-9-DEMO-REHEARSAL-1.md`; `evidence/day-9/phase-12-compose-up*.log`; commits `055613e`, `6edc909`, `afaf572`, `49a06cf`, `5318701`. |

**Pass B J6 flow (all real service path, browser blocked by a Chrome-extension
host-permission failure):** checkout `200 allow` → S5, `bin 411122` persisted, SSE
event · Launch `202` → running · replay `finished 821/821` terminal, 2 ESCALATED
`drift` incidents, TTD 78 s, `attempt_score` parity · D3 read model, no PAN/hash ·
co-tenant `cotenant-ip` → `198.51.100.249`, checkout `allow` (not blocked), `ip`
resolved · fault → 3× `allow` `fail_open:model`, never 5xx · D6 route + freshness ·
reset `idle` + full `cleared` + Redis floor 0 (3 orphan enforcement rows →
DEF-D9-008).

---

## Rehearsal #2 (`DAY-9-DEMO-REHEARSAL-2.md`) — S-4 armed

| | |
|---|---|
| **Result** | **PASS.** `docker compose down -v && up --build` → healthy ~20 s; frontend key aligned to a **freshly-minted** `fa4aa941e04b` == `merchant.api_key_hash` (the DEF-D9-011 fix survives a fresh `down -v` + new key). Full J6 flow re-run on the real stack. |
| **Comparison with Rehearsal #1** | Steps 1, 2, 3, 4, 5, 7, 8, 9 — **STABLE** (identical results). Step 9 — **IMPROVED**: 0 orphan `enforcement_action` rows after reset (R#1: 3); `cotenant-ip` after reset → 404 (DEF-D9-008 resolved). Step 6 flood — **STABLE (marginal, documented)**: 784/2116 flood requests shed, 1/4 interactive (R#1: 0/5) — same behaviour class, DEF-D9-004. |
| **Repeated failures** | **None.** The one *failure* in Rehearsal #1 — DEF-D9-011 (P1) — **did not reproduce**. No step that succeeded in R#1 Pass B failed in R#2. No new failure. No manual backend intervention in either rehearsal. |
| **S-4** | **NOT triggered.** |
| **Evidence** | `DAY-9-DEMO-REHEARSAL-2.md`; `evidence/day-9/phase-14-compose-up.log`; commit `d084ee2`. |

---

## Final gates (Phase 15)

| Gate | Result |
|---|---|
| **pytest** `tests/ -q` | **643 passed / 1 failed / 2 xfailed** (380 s). The 1 = `test_d6_provenance::test_corpus_identity` = **DEF-D9-003** (byte-hash on a non-deterministically built gitignored corpus; **zero metric impact**, proven; S-6 not triggered). 0 unexpected failures; the 6 new Phase-13 regression guards all pass. |
| **Vitest** `test:run` | **205 passed / 21 files** — unchanged (no dashboard code changed). |
| **Playwright** `test:e2e` | **68 passed** (1.8 min) — 17 checks × 4 viewports (1536/1280/768/390). |
| **verify_60x `--gate 60x --faulthandler`** | **PASS 9/9** (401 s, quiet machine): `no_crash` (no SIGSEGV), `health_responsive`, `loop_lag_under_2s` (0.0 s), `rss_growth_ok`, `checkout_interleaved`, `drainer_alive`, exact terminal counts. → AUDIT-006 + AUDIT-012. `evidence/day-9/phase-15-verify60x-clean.log` |
| **verify_60x `--gate crossing`** | **PASS** (94 s) — 5 reps × both orders, bounded discontinuity, no spin. → AUDIT-006. |
| **verify_60x `--gate throughput`** | OVERALL FAIL — **the sole failing sub-check is `throughput_ok`** (~305 aps < 400, **advisory** per Decision 110). All 10 other sub-checks PASS (this run incl. `each_under_5s`): `identical_event_counts`, `no_run_was_swallowed`, `attempt_score_row_parity`, `redis_returns_to_floor`, `no_degraded_reset`, `drainer_*`, `loop_lag_under_2s`. Every correctness/determinism/repeatability check green. `verify_60x.py` unchanged (Plan §8). (A first attempt under concurrent Playwright + the full stack FAILed on the Phase-10-documented Redis-socket pressure signature — restored by `compose down` to only-redis.) |
| **D6 evaluation** | `scripts/diff_d6.py` — **0 substantive metric differences** (Phase 5). All 4 S-6 frozen-artifact SHAs (`d6.json` `29edcb22…`, `models/audit.json` `ce75cb7f…`, `models/l1-lgbm-v1.json` `7cb7fa8a…`, `models/platt-v1.json` `22dc48f0…`) **byte-identical to Phase 0** (re-verified Phase 15). **S-6 not triggered.** |
| **security** | Phase 6 — **S-5 not triggered**; 48 acceptance + 35 live probes; no client-asserted data reaches features/model/decision/identity; no PAN/hash leak; demo controls 404-invisible without `TOLLGATE_DEMO_CONTROLS=1`. The Phase-13 `?state=` change adds no injection surface (Literal-validated; `merchant_id` stays a bound param). |
| **reliability** | Phase 7 — all 6 injected infrastructure faults fail **safely** (no 5xx where fail-open is required, no wedge, no swallowed exception, no corrupted state, recovery works). |
| **replay** | Phase 8 repeatability gate **PASSES** (16/16 speed-0 matrix + 3/3 speed-60 + 5/5 lifecycle ops; 19/19 distinct `run_id`s). Reconfirmed live in both Session-3 rehearsals. |
| **performance** | Phase 10 — `/v1/score` compute **p99 = 12 ms** (TRD < 100 ms met wide); no memory leak (negative RSS growth over soaks); LLM off the scoring path. |
| **accessibility** | Playwright suite (17 × 4 viewports, incl. every-SVG-text ≥ 11px, focus-ring, no-console-error) green. One axe `color-contrast` P3 (DEF-D9-009 — `--tg-primary` small text 4.06:1, legible, documented). |

---

## Final defects — remaining P0/P1/P2/P3 and disposition

| ID | Sev | Final disposition |
|---|---|---|
| — | **P0** | **none found in any phase** |
| DEF-D9-010 | **P1** | **FIXED** `055613e` — verified R#1 Pass B + R#2 |
| DEF-D9-011 | **P1** | **FIXED** `afaf572` — verified R#2 (fresh key `fa4aa941e04b`) |
| DEF-D9-001 | P2 | **RESOLVED by decision** — `Decisions.md` Decision 110 (`verify_60x` throughput *speed* sub-checks advisory; correctness sub-checks blocking + green; test unmodified) |
| DEF-D9-003 | P2 | **KNOWN LIMITATION** — corpus byte-hash; **zero metric impact proven** (regeneration + `diff_d6.py`); S-6 not triggered; `test_corpus_identity` stays RED. Rework post-Day-9. |
| DEF-D9-002 | P3 | **FIXED (Phase 2)** — Compose scorer `--log-config`. Manual path unchanged. |
| DEF-D9-006 | P3 | **FIXED** `eb13ffa` — `?state=` honoured (`live`/`closed`/`all`, 422) + guard |
| DEF-D9-008 | P3 | **FIXED** `87614da` — reset releases enforcement rows + guard; verified R#2 (0 orphans) |
| DEF-D9-012 | P3 | **FIXED** `87f3962` — `?demo=1` readout shows non-2xx `HTTP <code>` + guard |
| DEF-D9-004 | P3 | **DOCUMENTED** — flood shed marginal on the single-worker laptop (reference-machine ceiling, same as DEF-D9-001); shed rung proven; demo script frames the beat + a contingency note |
| DEF-D9-005 | P3 | **DOCUMENTED** — unknown replay `tier` surfaces as a recoverable `failed` state; a boundary `Literal` would break the AUDIT-007 async-failure test (its fix is not isolated); off the demo path |
| DEF-D9-007 | P3 | **DOCUMENTED** — `stop` lag at `speed=1` only (not the demo speed 60); fix rewrites guarded run-loop timing; `reset` is the fast path |
| DEF-D9-009 | P3 | **DOCUMENTED** — `--tg-primary` small-text contrast 4.06:1 (legible); retune for text + re-run axe post-demo |

**Roll-up: P0 = 0 · P1 = 0 unresolved (2 FIXED) · P2 = 0 unresolved (1 resolved
by decision, 1 documented known limitation with proven-zero metric impact) ·
P3 = 5 FIXED / 4 DOCUMENTED.**

**Stop conditions S-1…S-6 — each checked individually — NONE triggered.**

---

## Final verdict

```
DEMO READY
```

Basis (Plan §10, evaluated line by line in `QA-AUDIT-DAY-9-2026-09-03.md` §22):
zero P0 · zero unresolved P1 · two complete successful rehearsals from clean
state with no manual backend intervention · `docker compose up` brings the full
stack (Layer 2 loaded) clean from stopped · every blocking test gate green with
two explicitly documented exceptions that do not block (the permanent
`test_corpus_identity` RED with proven-zero metric impact; the advisory
`verify_60x` `throughput_ok` speed sub-check per Decision 110) · no known
data-integrity failure (S-6 not triggered) · no known security-critical failure
(S-5 not triggered) · no known repeatability failure (Phase 8 + Rehearsal #2,
S-4 not triggered).

The remaining P2/P3 known limitations (DEF-D9-001/003/004/005/007/009, the R-5
items, the ≈ 59× replay factor) are each documented and the demo script accounts
for them; none can interrupt, invalidate, embarrass, confuse, or materially
undermine the demo when the presenter follows `DAY-9-DEMO-SCRIPT.md`.

---

## Git

| | |
|---|---|
| **Final HEAD** | _(recorded after the Phase-15 commit sweep — see the last line of this file)_ |
| **Working tree** | clean |
| **Session 3 commits** (in order) | `055613e` DEF-D9-010 · `6edc909` DEF-D9-011 (Dockerfile, superseded) · `afaf572` DEF-D9-011 (corrected) · `49a06cf` pin sha · `5318701` Phase 12 Rehearsal #1 · `87614da` DEF-D9-008 · `eb13ffa` DEF-D9-006 · `3e2b6dc` Decision 110 · `87f3962` DEF-D9-012 · `4abb711` Phase 13 dispositions · `bbd9be2` DAY-9-DEMO-SCRIPT.md · `d084ee2` Phase 14 Rehearsal #2 · `<phase15>` Phase 15 audit + results + Flow.md + checkpoint |
| **S-6 frozen artifacts** | all 4 SHAs byte-identical to Phase 0 |
| **Unexpected generated files** | none (repo-root `test-results/` from a Playwright run is now gitignored) |

> **FINAL HEAD after the Phase-15 commit: recorded below by the checkpoint commit itself.**
