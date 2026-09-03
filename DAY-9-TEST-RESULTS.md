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

---

## Phase 2 — Containerization exit gate

Full detail: `evidence/day-9/phase-2-containerization.md`.

| Suite / check | Command | Result | Notes |
|---|---|---|---|
| `docker compose up --build` from `down -v` | `docker compose down -v && docker compose up --build` | ✅ | exit 0; all 5 long-running services healthy ~43 s after first container start; `bootstrap` exit 0 |
| Backend full vs **containerized** Redis | `TOLLGATE_REDIS_URL=redis://localhost:6379 uv run pytest tests/ -q` | ❌→⚠️ | **618 passed / 1 failed / 2 xfailed** (484 s). The 1 failure = **DEF-D9-003** — `test_d6_provenance.py::test_corpus_identity_is_recorded_and_matches_the_real_corpus`. |
| `/healthz`, `:5173`, `:5174`, dashboard `/v1` proxy | curl | ✅ | 200 / 200 / 200 / 200 |
| SSE + `/v1/stream/recent` | curl `-N` | ✅ | `: ping` heartbeat; `{"events":[]}` fresh |
| `/v1/incidents` | curl | ✅ | 200 — was **500** (`unable to open database file`) before the `tollgate_data` volume fix |
| Layer 2 loaded (DB rows + startup log) | `docker compose logs scorer` + DB query | ✅ | `policy_config` v2 w/ thresholds + `store_baseline` row; log line `loaded Layer 2 for merchant_demo: policy v2 …` |
| Redis connect (not fallback) | startup log | ✅ | `Connected to Redis … using RedisWindowStore` |
| Narrator template / gemini-no-key warning | replay + `validate_startup()` | ✅ | incidents narrated `narrative_source='template'`; missing-key warning emitted |
| Replay lifecycle through the stack | `POST /v1/replay/{start,reset}` | ✅ | `finished 821/821`; reset 200 with `cleared` map; Redis `dbsize`→0 |
| Trusted-edge XFF (Step 6 / PRE-4 enabler) | `X-Forwarded-For` via Vite proxy | ✅ | resolves to the forwarded IP through the declared-edge proxy container; ignored for a non-edge peer |
| S-6 artifacts (`d6.json`, `models/audit.json`, `l1-lgbm-v1.json`, `platt-v1.json`) SHA | `sha256sum` | ✅ | **unchanged** from Phase 0 |

### Failure classification (Phase 2)

| Item | Classification | Disposition |
|---|---|---|
| `test_d6_provenance::test_corpus_identity_is_recorded_and_matches_the_real_corpus` | **Newly introduced this phase, self-inflicted.** While iterating on the bootstrap, one `docker compose up` ran `learn_store_baseline` + `tune_cusum` against the bind-mounted `data/corpus/tollgate.db` before the corpus-working-copy guard existed → `store_baseline.updated_at` (wall-clock, non-deterministic) bumped on 8 rows + 20 `policy_config` rows appended (since deleted). Corpus SHA no longer matches `d6.json.provenance.corpus_db_sha256`. **No metric/detection impact** — 618/619 other tests green; the removed policy rows were unreferenced; `updated_at` is metadata; every S-6 artifact SHA unchanged. | **DEF-D9-003, P2.** Recurrence prevented (`compose_bootstrap.ensure_corpus_working_copy()`). **Phase 5 prerequisite:** regenerate `d6.json` provenance after a reviewed metric diff, or restore/rebuild a pristine corpus. Not restorable in Session 1 (no pristine copy; `updated_at` non-deterministic). |

Stop condition **S-2 not triggered** (phase well under 4 h; no detection/scoring/window
semantics change). Stop condition **S-6 not triggered** (all four frozen artifact SHAs
intact).

---

---

## Phase 3 — J6 steps 6–8 exit gate

Full detail: `evidence/day-9/phase-3-j6-6-8.md`.

| Suite / check | Result | Notes |
|---|---|---|
| New acceptance tests `test_demo_{fault,cotenant_ip,flood}.py` | ✅ **19 passed** | 6 + 8 + 5 |
| Full `pytest tests/ -q` after Phase 3 | ⚠️ **637 passed / 1 failed / 2 xfailed** | the 1 failure = **DEF-D9-003** (Phase-2 corpus drift). `test_durability` flaked once under machine load in a background run; **passes clean in isolation** (`1 passed in 13.32 s`). |
| `vitest run` | ✅ 205 passed / 21 files | DC-strip toggle changes — no regression |
| `playwright test` | ✅ 68 (67 + 1) | one D6-layout test (`no metric-row label overlaps its bar track`) flaked under 4-worker + Docker contention; **4/4 pass isolated**. Unrelated to Phase 3 (dashboard `#/metrics`, not the demo strip). |
| Step 8 (fault) demonstrated | ✅ | `fault:true` → `/v1/score` = 200 `allow` (never 5xx), `degraded_reason: fail_open:model`; off → full path restored |
| Step 7 (flood) demonstrated | ⚠️ | real `AdmissionController` path: flood `shed_responses: 155`, `X-Tollgate-Shed: 1` observed after ~16 s sustained; **DEF-D9-004** (P3) — marginal/slow on the dev scorer |
| Step 6 (co-tenant) demonstrated | ✅ | `GET /v1/demo/cotenant-ip` → `198.51.100.249` (real attacker IP); co-tenant checkout via the storefront proxy → `auth_attempt.ip = 198.51.100.249`, decision `allow` (not blocked) |
| Controls inert without `TOLLGATE_DEMO_CONTROLS` | ✅ | all `/v1/demo/*` → 404; the fault flag alone (no env) does not change `/v1/score`; UI groups render only with `VITE_TOLLGATE_DEMO_CONTROLS=1` |
| S-3 (any control faking a decision/tier/availability state) | **not triggered** | every control drives a real path; source-level test asserts the flood never sets `shed` directly |

---

---

# SESSION 2 (Phases 4–11)

Machine / stack unchanged. QA phases run against the **Docker Compose stack** (the
judge's path) unless noted. Stack: 5 services healthy; scorer `RedisWindowStore`,
Layer 1 + Layer 2 (`policy v2, cusum_h=318.133`), `TOLLGATE_DEMO_CONTROLS=1`.

## Phase 4 — Backend / API QA

Full detail: `evidence/day-9/phase-4-api-qa.md` · harness + raw results:
`evidence/day-9/phase-4-api-qa-harness.py` / `phase-4-api-qa-results.json`.

| Suite / check | Command | Result | Notes |
|---|---|---|---|
| API route matrix (every `services/scorer` route × happy/auth/malformed/oversized/missing/wrong-type/dup-`event_id`/diff-payload/concurrent/wrong-method/unknown-route) | `phase-4-api-qa-harness.py` | ✅ **66 / 66 PASS** | 0 FAIL. Every route enforces its auth boundary; every 4xx is operator-readable (`{"detail": "…"}` or a pydantic `loc` list); no raw stack trace, no unmapped 500. |
| `/v1/score` idempotency (`sha256(merchant\|event_id\|payload_digest)`) | live + DB | ✅ | dup identical → same `attempt_uid` (1 `auth_attempt` row); same `event_id` + changed payload → new `attempt_uid` (by design, Threat Model §3); 10× concurrent identical → **1** distinct uid, 1 row |
| `/v1/replay/*` lifecycle (start 202 / 409-busy / stop true-terminal / reset 200+`cleared`) | live | ✅ | `stop` returns `stopped` not stale `running`; `reset` `cleared` map + `degraded:false`; rejected call leaves state untouched |
| `/v1/replay/start` unknown `tier` | live | ⚠️ | **202** then async `KeyError` → `failed` (terminal, recoverable). **DEF-D9-005 (P3)** — boundary should 422. Not on the demo path. |
| `/v1/incidents?state=` filter | live + source | ⚠️ | param declared + documented, **never applied**. **DEF-D9-006 (P3)** — dead parameter, no functional impact. |
| `/v1/outcome` wire outcomes (401 unsigned / stale / bad-sig, 422 extra/missing) | live | ✅ | happy + 404 + 409 + 503 covered by `test_outcome_hmac.py` (green) and Phase 6 |
| `/v1/demo/*` (gate ON) auth + validation + fault→fail-open | live | ✅ | `fault:true` → `/v1/score` 200 `allow` never 5xx; restored to OFF; gate-OFF 404 behaviour covered by `test_demo_*` (green) + Phase 6 |
| oversized body (~4 MB) | live | ⚠️ obs | 200, no cap, ~0.4 s — no 500/hang. Phase 6 DoS-surface note. |

**Phase 4 verdict: GREEN.** No P0/P1/P2. Two P3 defects (DEF-D9-005, DEF-D9-006),
both Phase-13 candidates, neither on the demo path.

## Phase 5 — Detection & Evaluation QA (release gate)

Full detail: `evidence/day-9/phase-5-detection-eval.md` · `phase-5-diff_d6.txt` ·
`phase-5-live-detection-harness.py` / `phase-5-live-detection-results.json`.

| Suite / check | Command | Result | Notes |
|---|---|---|---|
| **DEF-D9-003 reconciliation** (corpus SHA drift) | `eval.harness` ×2 → `diff_d6.py` | ✅ **RECONCILED** | harness deterministic (A≡B); plan's exact `diff_d6` invocation → **2 changed leaves, both provenance metadata** (`corpus_db_sha256` = the drift, `generation_command` = invocation echo); `--ignore provenance` → **0 substantive difference(s)**; `report.md` byte-identical mod provenance. `d6.json` SHA `29edcb22…` + `models/audit.json` `ce75cb7f…` **unchanged from Phase 0**. **S-6 NOT triggered.** |
| Detection + eval acceptance subset | `pytest tests/ -q -k "<subset>"` | ⚠️ **196 passed / 1 failed** | the 1 = `test_d6_provenance::test_corpus_identity` (DEF-D9-003, P2 known limitation — byte-hash check on a non-deterministically-built gitignored input; zero metric impact). CUSUM/SPRT/calibration/hysteresis/K_max/control-arm/state-machine/entity-resolution/corroboration/metamorphic M1–M8 all ✅ |
| Detection — live (`easy` seed42 speed60 pace episode, real `score_attempt`) | `phase-5-live-detection-harness.py` | ✅ **8 / 8** substantive checks | 821/821 events; decision histogram `{allow:269, challenge:552}` — **0 auto block/step_up** (ceiling holds); R1/R2/R3 floors all fire; 2 `drift` incidents ESCALATED, TTD 76/78 s; entity type `ip` only; `k_max:10 advisory:false`; control arm 29/821; state machine ESCALATED→CLOSED on resolve, all enforcement released; `reset` 200 + `cleared`. |
| Evaluation — D6 reproduction | `eval.harness --split all --seed 42` + `diff_d6.py` | ✅ **0 substantive metric differences** | schema v2, provenance complete; per-tier (incl `tier_e`) matches README (model 0.00/0.973/0.732/0.391, B0 0.997/0.985/0.125/0.284); prevalence transform π₀/π₁/π_t; ECE π₀ 0.262→0.0007 w/ prior corr; cost `c_fn=5200 c_fp=1800` rupee_gap 0 structural, saving 23214508; `theta_challenge=0.257`; B0 ROC-AUC 0.994 > model 0.889; 7 negative controls; 6 features excluded → 4 live; every metric carries its measurement conditions; `unreachable`/`resolvable:false` never a fake `0.000`. |

**Phase 5 verdict: GREEN — release gate PASSES.** No new defects. DEF-D9-003
remains OPEN as a P2 documented known limitation (does not block the gate; the
gate's requirement — "0 substantive differences, `d6.json` SHA unchanged" — is met).

## Phase 6 — Security QA (S-5 armed)

Full detail: `evidence/day-9/phase-6-security.md` · harness + results:
`phase-6-security-harness.py` / `phase-6-security-results.json`.

| Suite / check | Command | Result | Notes |
|---|---|---|---|
| **S-5 stop condition** (client data → feature / model / decision / identity) | `phase-6-security-harness.py` §1 | ✅ **NOT triggered** | hostile body (`ip`, `merchant_id`, `attempts_per_ip_60s=999999`, `score_calibrated=0.999`, `decision="block"`, `rules_fired`, PAN, cvv) → persisted row: `merchant_id=merchant_demo` (from key), `attempts_per_ip_60s=1` (server), `score_calibrated=9.57e-05` (model), `rules_fired=[]`, `attempt_uid` ULID, no PAN/cvv. Response `allow`, not injected `block`. |
| Trusted-edge XFF boundary | harness §2 | ✅ | non-edge peer (redis `172.28.0.20`) XFF → **ignored**; declared-edge proxy (`172.28.0.11`) XFF → honoured (Threat Model K8). Default set not widened. |
| PAN / CVV / card-hash leakage | harness §3 | ✅ | no `card_hash` key on 200 scanned SSE events (Decision 34); PAN + hash absent from scorer logs; `test_no_pan.py` green |
| Hostile strings (10KB unicode / RTL / control chars / injection-shaped / CRLF) | harness §4 | ✅ | all → 200, no 5xx |
| `/v1/outcome` HMAC lifecycle | harness §5 (live) | ✅ | valid → **200 + persisted** (`sig_verified=1`); replayed nonce → **409**; unknown event → **404**; stale ts → **401**; unsigned → **401**; tamper (sign-A-send-B) → 401 via `test_outcome_hmac.py` |
| Narrator isolation | source + `test_narrator_injection` | ✅ | `build_bundle()` frozen dataclass, closed vocab, `__post_init__` raises; `assemble_prompt` `CHARSET_RE` gate → `PromptGateError` → template; no `user_agent`/free text enters; runs out-of-band (Decision 98) |
| Operator-action auth | harness §7 | ✅ | replay start/stop/reset + incidents list/detail/confirm/resolve all **401** without a key (well-formed body); `/v1/replay/status` open (Decision 107); SQLi-shaped + 64 KB key → 401 |
| 422-before-401 on malformed **unauthenticated** body | harness §7 | ℹ️ observation | consistent FastAPI validation-before-handler ordering; **not a bypass** (well-formed unauthenticated → 401 before any effect). By-design; noted for the audit, no DEF-ID. |
| Demo controls inert by default | throwaway scorer, no env | ✅ | `/v1/demo/{cotenant-ip,flood,fault}` → **404** with `TOLLGATE_DEMO_CONTROLS` unset; `test_demo_*` green |
| Security acceptance subset | `pytest -k "trust_boundary or no_pan or outcome_hmac or replay_auth or narrator_* or simulator_safety or admission or fail_open"` | ✅ **48 passed** | |

**Phase 6 verdict: GREEN. S-5 NOT triggered.** No P0/P1/P2, no new numbered
defect. R-5 items (`/v1/stream` unauth, outcome features `0.0`) reconfirmed as
documented known limitations. One hardening note (no body-size cap; token-bucket
is the volume mitigation).

## Phase 7 — Reliability / Failure Injection

Full detail: `evidence/day-9/phase-7-reliability.md`. Six infrastructure faults
injected against the running Compose stack; each answers *fails safely · UI truth
· recover · data preserved · demo continues*.

| # | Fault | Result |
|---|---|---|
| 1 | Redis killed mid-scoring | ✅ 5 scores → 200 `allow` `fail_open:window_store`, **never 5xx**; `/healthz` 200; SSE `fail_open:true` frames |
| 1b | Redis restarted | ✅ scorer **auto-recovers, no restart** — `degraded_reason:null`, window counting again |
| 2 | Scorer restarted (SIGTERM) | ✅ healthy 8 s; drainer resumes from persisted byte offset (no re-drain); `attempt_score` 6767→6767; replay `idle` not stuck |
| 3 | Scorer SIGKILL mid-replay | ✅ post-kill replay `idle`/`run_id:null`/`terminal:true`/`error:null` — no phantom `running`; scored events survived; fresh launch works, no manual intervention |
| 4 | SSE drop → polling contract | ✅ `/v1/stream/recent?after=<uid>` strictly-after, in-order; `: ping` flush on subscribe |
| 5 | SQLite `BEGIN EXCLUSIVE` held 4 s | ✅ `/v1/incidents` 200 (WAL read), `/v1/score` 200 (writes spool not SQLite), `drainer_failures:0` — scoring decoupled from DB contention |
| 6 | Redis unavailable at startup | ✅ `ERROR … falling back to InMemoryWindowStore` (explicit); scores 200 via real in-mem window path (not fail-open); restore → `RedisWindowStore` |

Cross-referenced: reset/stop during replay → Phase 8; browser refresh / SSE→poll→SSE
in-browser → Phase 11; dup event / malformed / bad key → Phase 4; Gemini faults →
`test_narrator_*` (23 passed), narrator is out-of-band (Decision 98).

Background-task exceptions surfaced not swallowed (AUDIT-007); drainer never
wedged (`drainer_failures:0` throughout); `/healthz` always responsive (no CPU
loop); no corrupted state after all faults + restores (5/5 services healthy,
reset → `idle` + full `cleared` map).

**Phase 7 verdict: GREEN.** No new defects. Two hardening observations (InMemory
fallback logs a full traceback; spool grows unbounded — `down -v` resets it).
