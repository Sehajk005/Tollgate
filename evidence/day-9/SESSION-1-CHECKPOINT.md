# Day 9 — Session 1 checkpoint (Phases 0–3)

**Date:** 2026-09-03 · **Branch:** `day-9` (from `day-2` @ `8cf17d9`) · **HEAD:** `eeb8051`
**Executing:** `09-DAY-9-QA-AND-DEMO-PLAN.md` Session 1 (Phases 0–3 only).

---

## Phase status

```
Phase 0  COMPLETE   baseline snapshot + plan written + committed
Phase 1  COMPLETE   baseline test matrix + manual-path startup baseline
Phase 2  COMPLETE   docker compose up --build brings the full stack clean from stopped
Phase 3  COMPLETE   J6 steps 6-8 built on real code paths, 19 new tests green
```

Phases 4–15 **not started** (correct — Session 1 stops here).

---

## Git

| | |
|---|---|
| Day 9 baseline SHA | `5a43e0c` (`spec: Day 9 baseline -- untested Day-8 + remediation working tree`) |
| HEAD | `eeb8051` |
| Commits this session | `5a43e0c` baseline · `a5f16d7` Phase 0 plan+evidence · `75d113f` Phase 1 · `e690db4` Phase 2 · `eeb8051` Phase 3 |
| Working tree | **clean** (everything committed) |
| S-6 frozen artifacts | `eval/outputs/d6.json` `29edcb22…` · `models/audit.json` `ce75cb7f…` — **unchanged** |

---

## Tests

| Gate | Baseline (Phase 1) | After Phase 3 |
|---|---|---|
| `pytest tests/ -q` | 619 passed / 2 xfailed | **637 passed / 1 failed / 2 xfailed** — the 1 failure is DEF-D9-003 |
| safety / slow / redis / metamorphic / characterization | 6 / 21 / 16 / 8 / 4 | (unchanged) |
| reversed-file-order (AUDIT-010) | 619 passed | (hermetic) |
| `vitest run` | 205 / 21 files | **205** |
| `vitest --coverage` | 97.9 / 86 / 98.5 / 97.9 (≥ 85/85/80) | (unchanged) |
| `playwright test` | 68 (17×4) | **68** (1 D6-layout test flakes under contention, 4/4 isolated) |
| `verify_60x --gate 60x` (± faulthandler) | PASS 9/9, no crash | (unchanged) |
| `verify_60x --gate crossing` | PASS | (unchanged) |
| `verify_60x --gate throughput` | **FAIL** speed sub-checks (DEF-D9-001) | (unchanged) |

**Failures still present:** `test_d6_provenance::test_corpus_identity` (DEF-D9-003).
`test_durability` flaked once in a machine-loaded background run; passes clean isolated.

---

## Docker

`docker compose down -v && docker compose up --build` → **all 5 long-running services
healthy ~43 s from the first container start**; `bootstrap` exits 0.

| Check | Result |
|---|---|
| `/healthz` 200 · storefront :5173 · dashboard :5174 · dashboard `/v1` proxy | all 200 |
| SSE connects · `/v1/stream/recent` back-fills | pass |
| `/v1/incidents` | 200 (was 500 before the `tollgate_data` volume fix) |
| Layer 2 loaded | `policy v2` + `store_baseline` row + startup log `loaded Layer 2 for merchant_demo …` |
| Redis connected (not fallback) · narrator template | pass |
| replay 821/821 + reset (`cleared` map, Redis floor 0) | pass |
| trusted-edge XFF through the Vite proxy | resolves to the forwarded IP |

Ports: storefront `:5173`, dashboard `:5174`, scorer `:8080`, redis `:6379`, redis-small `:6380`.

---

## J6

| Step | Status | Evidence |
|---|---|---|
| 6 — CGNAT co-tenant | built + demonstrated | `GET /v1/demo/cotenant-ip` → `198.51.100.249`; co-tenant checkout via the storefront proxy → `auth_attempt.ip = 198.51.100.249`, `allow` (not blocked). 8 acceptance tests. |
| 7 — flood → shed | built + demonstrated, MARGINAL | real `AdmissionController` path: `shed_responses: 155`, `X-Tollgate-Shed: 1` after ~16 s sustained. **DEF-D9-004** (P3). 5 acceptance tests. |
| 8 — fault → fail-open | built + demonstrated | `fault:true` → `/v1/score` = 200 `allow`, `degraded_reason: fail_open:model`, never 5xx; off → full path. 6 acceptance tests. |

All gated behind `TOLLGATE_DEMO_CONTROLS=1` (default off); `/v1/demo/*` → 404 when unset.
S-3 not triggered.

---

## Defects (`DAY-9-DEFECT-LOG.md`)

| ID | Sev | Root cause | Fixed? | Verification | Evidence |
|---|---|---|---|---|---|
| DEF-D9-001 | P2 | `verify_60x --gate throughput` speed sub-checks fail — mean 190 aps vs ≥ 400; single-threaded HTTP loop + Redis-over-Docker-bridge on Windows. Determinism/repeatability/drainer all green. | No — deferred to **Phase 10**. | Re-run `--gate throughput` ×2 green, or a `Decisions.md` entry re-scoping the threshold with profiling. | `evidence/day-9/phase-1/verify60x-throughput.json` |
| DEF-D9-002 | P3 | README manual-path startup did not surface the `tollgate.scorer` INFO lines. | **Fixed (Phase 2)** — Compose scorer uvicorn `--log-config deploy/uvicorn-logging.json`. | `docker compose logs scorer \| grep "loaded Layer 2"` returns the line. | `evidence/day-9/phase-1/scorer-startup*.log` |
| DEF-D9-003 | P2 | Early Phase-2 bootstrap iteration mutated `data/corpus/tollgate.db` (`store_baseline.updated_at` + free pages) before the corpus-working-copy guard. SHA ≠ `d6.json.provenance.corpus_db_sha256`. **No metric/detection impact** — every S-6 SHA unchanged, 636/637 tests green. | **Recurrence prevented**; drift not restored (no pristine copy). | **Phase 5 prerequisite** — regenerate `d6.json` provenance after a reviewed metric diff, or rebuild a pristine corpus. | `evidence/day-9/phase-2-pytest.log` |
| DEF-D9-004 | P3 | J6 flood marginal/slow on the single-worker dev scorer (~50 ms/request ≈ 50/s admission refill) — bucket takes ~15 s to empty, then sheds intermittently. Shed rung proven by `test_admission_shed.py`. | No — Phase 13 / Phase 10. | Flood → continuous `X-Tollgate-Shed: 1` within ~3 s. | `evidence/day-9/phase-3-j6-6-8.md` §3 |

---

## Artifacts produced this session

- `09-DAY-9-QA-AND-DEMO-PLAN.md` (repo root — authoritative plan, written first)
- `DAY-9-TEST-RESULTS.md` · `DAY-9-DEFECT-LOG.md`
- `evidence/day-9/phase-0-baseline.md` · `phase-1/` (18 logs) · `phase-2-containerization.md`
  + 5 logs · `phase-3-j6-6-8.md` + 2 logs · this checkpoint
- Docs: `Decisions.md` Decision 109 (containerization) · `README.md` Docker Compose section

Not yet produced (Session 2/3 per Plan §11): `QA-AUDIT-DAY-9-2026-09-03.md`,
`DAY-9-DEMO-REHEARSAL-1/2.md`, `DAY-9-DEMO-SCRIPT.md`. `Flow.md` Docker/J6 update deferred
to the Phase-15 consolidation pass (avoid a competing source of truth mid-day).

---

## Exact resume point

> **NEXT SESSION SHOULD RESUME AT PHASE 4** (Backend / API QA), then Phases 5–11 per
> `09-DAY-9-QA-AND-DEMO-PLAN.md` §12 "Session B".

Do not re-run Phases 0–3 — evidence and commits above are complete.

**Carry into Session 2:**
- DEF-D9-003 is a **hard prerequisite for the Phase 5 gate** — reconcile the corpus /
  `d6.json` provenance before running `diff_d6.py`.
- The Compose stack is torn down (`docker compose down`); images are built and cached, so
  `docker compose up --build` is fast. `deploy/compose.env` is gitignored and re-written
  by `bootstrap`.
- `TOLLGATE_DEMO_CONTROLS` / `VITE_TOLLGATE_DEMO_CONTROLS` are set for the demo services in
  `docker-compose.yml`. Phase 6 (security) must confirm the `/v1/demo/*` surface is inert
  with them unset (it is — `test_demo_*` covers it) and that the `x-tg-demo-xff` proxy
  promotion does not widen the trust boundary off the demo path.
- DEF-D9-001 (throughput) is a Phase 10 item; DEF-D9-004 (flood) a Phase 13/10 item.
