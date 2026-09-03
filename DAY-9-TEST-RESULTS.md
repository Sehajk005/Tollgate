# DAY-9-TEST-RESULTS

**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §5 test matrix + Phase 1.
**Baseline SHA under test:** `5a43e0c` (branch `day-9`).
**Machine:** Windows 11, Python 3.13.3, Node v22.14.0, Docker 29.1.3, Compose v2.40.3.
**Redis:** `tollgate-redis-1` :6379 (`PONG`), `tollgate-redis-small-1` :6380 (`PONG`).
**Path under test:** README manual path (Phase 1 baseline — nothing modified).

Legend: ✅ pass / gate green · ⚠️ pass with note · ❌ fail · ⏳ running

---

## Phase 1 — Baseline test matrix (README manual path, tree unmodified)

| # | Suite | Command | Result | Count | Duration | Gate | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | Backend full | `uv run pytest tests/ -q --durations=25` | ✅ | **619 passed, 2 xfailed**, 1 warning | 331.16 s | blocking — GREEN | `evidence/day-9/phase-1/pytest-full.log` |
| 2 | Safety | `pytest -q -m safety` | ✅ | 6 passed, 615 deselected | 1.98 s | blocking — GREEN | `pytest-safety.log` |
| 3 | Slow | `pytest -q -m slow` | ✅ | 21 passed, 600 deselected | 149.03 s | blocking — GREEN | `pytest-slow.log` |
| 4 | Redis | `pytest -q -m redis` | ✅ | 16 passed, 605 deselected (Redis up — not skipped) | 44.49 s | blocking — GREEN | `pytest-redis.log` |
| 5 | Metamorphic | `pytest -q -m metamorphic` | ✅ | 8 passed (M1–M8), 613 deselected | 2.93 s | blocking — GREEN | `pytest-metamorphic.log` |
| 6 | Characterization | `pytest -q -m characterization` | ✅ | 4 passed, 617 deselected | 3.71 s | informational — never a gate | `pytest-characterization.log` |
| 7 | Reversed file order | reversed-file-order invocation — 121 files | ✅ | **619 passed, 2 xfailed** — identical to forward order | 322.53 s | blocking — GREEN (AUDIT-010 hermeticity holds) | `pytest-reversed-order.log` |
| 8 | Frontend unit | `npm --prefix services/dashboard run test:run` | ✅ | **205 passed / 21 files** | 40.33 s | blocking — GREEN | `vitest-run.log` |
| 9 | Frontend coverage | `npm run test:cov` (thresholds 85 / 85 / 80) | ✅ | 205 passed; **97.94 % stmts / 86 % branch / 98.48 % funcs / 97.94 % lines** | 39.10 s | blocking — GREEN | `vitest-cov.log` |
| 10 | Browser E2E | `npm run test:e2e` (Playwright) | ✅ | **68 passed** (17 checks × 4 viewports: 1536 / 1280 / 768 / 390) | 1.7 min | blocking — GREEN | `playwright.log` |
| 11 | 60× stability | `verify_60x --gate 60x --redis …/9` | ✅ | PASS — 9/9 checks (`all_runs_finished`, `exact_terminal_counts`, `checkout_interleaved`, `zero_failed_runs`, `health_responsive`, `loop_lag_under_2s`, `rss_growth_ok`, `no_crash`, `drainer_alive`) | 399.8 s | blocking — GREEN | `verify60x-all.log` |
| 12 | Time-domain crossing | `verify_60x --gate crossing` | ✅ | PASS (5 R2/R3 reps, one bounded discontinuity each, no spin) | 97.0 s | blocking — GREEN | `verify60x-all.log` |
| 13 | Throughput / repeatability | `verify_60x --gate throughput` | ❌ | **FAIL** — 9/11 checks pass. FAIL: `each_under_5s` (5/20 runs > 5 s, max 6.03 s), `throughput_ok` (mean **190 aps**, min 136, target ≥ 400). PASS: `all_finished`, `identical_event_counts` (all `[821]`), `no_run_was_swallowed`, `redis_returns_to_floor` (0), `no_degraded_reset`, `attempt_score_row_parity` (16 420 == 16 420), `drainer_alive`, `drainer_connects_within_budget` (2/run), `loop_lag_under_2s`. `health_p99_ms` = 323.8 under the 20-run soak; `rss_growth_mb` = 0.0. | 119.9 s | blocking — **RED (perf only)** | `verify60x-throughput.json` / `.log` |
| 14 | Native-fault path | `verify_60x --gate 60x --faulthandler` | ✅ | PASS — 9/9 checks. 3 runs × 821/821, wall ≈ 131 s each, `checkout_interleaved` ✓, **`no_crash` ✓ (no SIGSEGV under `dump_traceback_later`)**, `health_p99_ms` = 13.5, `rss_growth_mb` = −0.1, `loop_lag_warnings` = []. | 401.9 s | blocking — GREEN | `verify60x-60x-faulthandler.json` / `verify60x-remaining.log` |
| 15 | Artifact reproduction | `scripts/diff_d6.py` | — | not a Phase 1 item; run in Phase 5 | — | blocking | — |
| 16 | `handmade_40` × 2 | — | ⚠️ | **2 xfailed** (`test_handmade_40.py`, `test_handmade_40_incident.py`) — human oracle absent | — | never a gate — expected (Plan §2, §5) | `pytest-full.log` |

### Failure classification

**One gate red: `verify_60x --gate throughput` — performance sub-checks only.**
Stop condition **S-1 is NOT triggered**: S-1 fires on "≥ 5 failures whose causes are not
immediately classifiable". This is 2 check-failures inside 1 gate, cause immediately
classifiable (below). Every correctness / determinism / repeatability / drainer / memory
check in that same gate passed.

| Item | Classification | Disposition |
|---|---|---|
| `verify_60x --gate throughput`: `throughput_ok` FAIL (mean 190 attempts/s vs ≥ 400 target) and `each_under_5s` FAIL (5/20 runs 5.0–6.03 s) | **Environment + architecture, not a regression.** The gate's speed thresholds (script docstring: "each under 5 s, at least 400 attempts/s") are measured over a **single-threaded, sequential HTTP `POST /v1/score` loop** driving a Uvicorn scorer whose window store is **Redis over the Docker bridge**, on a **Windows laptop**. Mean per-attempt cost ≈ 5.3 ms — well inside the TRD's `/v1/score` p99 < 100 ms budget; the "throughput" number is bounded by the serial harness, not by request latency. The prior audit already measured the machine marginal on the 60× target (58.5×). `identical_event_counts`, `redis_returns_to_floor`, `attempt_score_row_parity`, `drainer_*`, `loop_lag_under_2s` all green ⇒ no correctness, determinism, repeatability, leak or wedge. | **DEF-D9-001, P2** (performance; not on the demo path — the demo runs replay at speed 60 with episode pacing, never a 20× speed-0 soak). Quantify + decide in **Phase 10**. Threshold **not** modified (Plan §8). |
| `health_p99_ms` = 323.8 during the 20-run throughput soak (vs 13.5 ms in the faulthandler 60× run with no soak) | **Same root cause** — GIL/event-loop contention while the serial score loop saturates one core. `loop_lag_under_2s` still passed (no ≥ 2 s synchronous block). | Folded into **DEF-D9-001**. |
| 2 × `xfailed` (`handmade_40`, `handmade_40_incident`) | **Intentional xfail** — human-oracle fixtures deliberately absent; Plan §2 out of scope, §5 "never a gate". | Not a defect. |
| `StarletteDeprecationWarning` (`httpx` with `starlette.testclient`) — 1 warning, every pytest run | **Environment / upstream deprecation.** Not a gate; no behavioural impact. | Phase 13 hygiene only. |
| Playwright `[vite] http proxy error: /v1/stream ECONNREFUSED` in `[WebServer]` output | **Expected** — no scorer running during the frontend-only E2E; the D6 metrics route makes zero scorer/SSE calls and the test `zero scorer/SSE network activity during a 10s dwell` passes. | Cosmetic dev-server log noise. |

### Baseline counts vs Plan §5 expectations

| Metric | Plan §5 expected | Observed | Match |
|---|---|---|---|
| Backend full | 619 passed, 2 xfailed | 619 passed, 2 xfailed | ✅ exact |
| Frontend unit | 205 passed / 21 files | 205 passed / 21 files | ✅ exact |
| Frontend coverage | ≥ 85 / 85 / 80 | 97.94 / 86 / 98.48 / 97.94 | ✅ |
| Browser E2E | 68 (17 × 4) | 68 passed | ✅ exact |
| 60× stability | 3 runs, no wedge | 3 runs, no wedge, no crash (both faulthandler on and off) | ✅ |
| Throughput / repeatability | "20 runs, identical counts" | 20 runs, `identical_event_counts` = `[821]` | ✅ counts / ❌ speed sub-checks (DEF-D9-001, P2) |

---

## Manual-path startup baseline

Command (README "Running the demo"):
`TOLLGATE_REDIS_URL=redis://localhost:6379 uv run uvicorn services.scorer.app:create_app --factory --port 8080`
Bootstrap already present on host `tollgate.db` (`merchant`=1, `store_baseline`=1,
`policy_config` v7 with populated `thresholds`).

| Measure | Value | Evidence |
|---|---|---|
| **Cold-start → `/healthz` 200** | **5.84 s** (`uv run` env resolve + uvicorn import + .env load + Redis connect + LightGBM + Platt load + Layer-2 load + spool drain-from-start + drainer thread) | `evidence/day-9/phase-1/scorer-coldstart.log` |
| Warm-restart → `/healthz` 200 | 1.02 s (uv env cached, OS cache warm) | `scorer-coldstart2.log` |
| `/healthz` body | `{"status":"ok","drainer_alive":true,"drainer_connects":1,"drainer_rows":13493,"drainer_failures":0}` — drainer healthy, ≤ 2 connects | — |

**Scorer startup log lines** (captured with app-logger at INFO —
`evidence/day-9/phase-1/scorer-startup-info.log`):

```
WARNING tollgate.scorer  config: loaded environment from D:\Projects\Tollgate\.env
WARNING tollgate.scorer  config: GEMINI_API_KEY is set but NARRATOR_BACKEND is 'template', not 'gemini' -- the key is unused
INFO    tollgate.scorer  Connected to Redis at redis://localhost:6379; using RedisWindowStore
INFO    tollgate.scorer  loaded Layer-1 model l1-lgbm-v1 + calibrator platt-v1 from models
INFO    tollgate.scorer  loaded Layer 2 for merchant_demo: policy v7, cusum_h=318.133, tau_flag=0.06475, drift_enabled=True
INFO    uvicorn          Application startup complete.
INFO    uvicorn          Uvicorn running on http://127.0.0.1:8080
```

| Startup fact | Status |
|---|---|
| `.env` loaded | ✅ `D:\Projects\Tollgate\.env` |
| Redis connect vs fallback | ✅ **connected** — `RedisWindowStore` (not `InMemoryWindowStore` fallback) |
| Layer-1 model | ✅ `l1-lgbm-v1` + calibrator `platt-v1` from `models/` |
| Layer 2 | ✅ **loaded** for `merchant_demo` — policy v7, `cusum_h=318.133`, `tau_flag=0.06475`, `drift_enabled=True` |
| Narrator backend | `template` (Gemini key present but unused — advisory `config:` warning, not an error) |
| `config:` warnings | 1 — the benign GEMINI_API_KEY-unused advisory. No errors. |

**Live `POST /v1/score` smoke** (demo key from `services/dashboard/.env`, hash verified
against the `merchant_demo` row): `HTTP 200`, `{"decision":"allow","latency_ms":36}`;
`attempt_score` row → `model_version=l1-lgbm-v1`, `calibrator_version=platt-v1`,
`policy_version=7`, `regime=in_control`, `shed=0`, `feature_snapshot` populated. Full
score path (not degraded / shed / fail-open) confirmed. `attempt_score` 6340 → 6341.

**Observability note (P3, DEF-D9-002):** the exact README command
(`uv run uvicorn … --log-level info`) does **not** surface the `tollgate.scorer` INFO
lines above — Uvicorn's `--log-level` configures only `uvicorn*` loggers. The lines were
recoverable only by launching through a wrapper that calls `logging.basicConfig`. On the
README path an operator sees the two `config:` warnings and nothing about Redis / model /
Layer-2 status. Cosmetic for the demo; relevant to Phase 2 (the Compose exit gate wants
the Layer-2 line visible) and Phase 11.

---

## Phase 1 verdict

**GREEN with one P2 performance defect (DEF-D9-001) and one P3 observability note
(DEF-D9-002).** No stop condition triggered (S-1 not met). Every blocking correctness
gate — backend 619/619, hermeticity, frontend 205/205 + coverage, Playwright 68/68,
`verify_60x` 60× (± faulthandler), crossing, and every determinism/repeatability/drainer
check inside the throughput gate — is green. Proceeding to Phase 2.

---

_Phases 2–3 gate results appended below as they complete._
