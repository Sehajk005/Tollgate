# DAY-9-DEFECT-LOG

Running inventory of every defect found during Day 9 execution of
`09-DAY-9-QA-AND-DEMO-PLAN.md`. Severity per Plan §1 (P0 blocks the demo · P1 breaks a
core claim/flow · P2 visible defect a judge would notice · P3 polish/docs).

**"Fixed" = the failure was reproduced, the change was made, and the failure no longer
reproduces** (Plan §8, §9). A patch alone is not "fixed".

| ID | Sev | Phase found | Component | One-line | Status |
|---|---|---|---|---|---|
| DEF-D9-001 | P2 | 1 | `scripts/verify_60x.py` throughput gate / scorer serving path | `verify_60x --gate throughput` speed sub-checks fail: mean 190 attempts/s (target ≥ 400), 5/20 runs > 5 s | OPEN — quantify in Phase 10 |
| DEF-D9-002 | P3 | 1 | `services/scorer/app.py` logging config | README manual-path startup does not surface `tollgate.scorer` INFO lines (Redis / model / Layer-2 status) — only `uvicorn*` loggers are configured by `--log-level` | **FIXED (Phase 2)** — Compose scorer runs uvicorn with `--log-config deploy/uvicorn-logging.json`; the Layer-2 line is visible in the container log. Manual path unchanged (still applies there — reopen as P3 if manual-path observability is required). |
| DEF-D9-003 | P2 | 2 | `data/corpus/tollgate.db` (reference corpus) | Phase-2 bootstrap (before the corpus-working-copy guard) ran `learn_store_baseline` + `tune_cusum` against the bind-mounted reference corpus, bumping `store_baseline.updated_at` on 8 rows + appending 20 `policy_config` rows (since deleted). Corpus SHA no longer matches `eval/outputs/d6.json.provenance.corpus_db_sha256` → `test_d6_provenance::test_corpus_identity_is_recorded_and_matches_the_real_corpus` FAILS. | OPEN — **Phase 5 prerequisite** (regenerate `d6.json` provenance, or restore a pristine corpus). Recurrence prevented: bootstrap now copies the corpus to the volume first. |

---

## DEF-D9-001 — throughput gate speed sub-checks fail at baseline

| Field | Detail |
|---|---|
| **Severity** | P2 |
| **Category** | Performance |
| **Phase found** | 1 (baseline test matrix, tree unmodified at SHA `5a43e0c`) |
| **Component** | `scripts/verify_60x.py::gate_throughput` thresholds `each_under_5s` / `throughput_ok`; underlying: `services/scorer` serving path + Redis-over-Docker-bridge window store |
| **Repro** | `uv run python -m scripts.verify_60x --gate throughput --redis redis://localhost:6379/9` on the Day-9 baseline, machine otherwise idle. |
| **Expected** | Gate `pass: true` — each of 20 sequential `easy` speed-0 replays completes < 5 s and sustains ≥ 400 attempts/s. |
| **Actual** | Gate `pass: false`. `each_under_5s` FAIL — wall 3.34–6.03 s, mean 4.45 s, **5/20 over 5 s**. `throughput_ok` FAIL — attempts/s 136–246, **mean 190**. `health_p99_ms` 323.8 during the soak. All 9 other checks PASS: `all_finished`, `identical_event_counts` = `[821]`, `no_run_was_swallowed`, `redis_returns_to_floor` = 0, `no_degraded_reset`, `attempt_score_row_parity` (16 420 == 16 420), `drainer_alive`, `drainer_connects_within_budget` (2/run), `loop_lag_under_2s`. `rss_growth_mb` = 0.0. |
| **Root cause (hypothesis, not established)** | The gate's speed thresholds assume throughput the serial-HTTP harness cannot produce on this host: a single-threaded loop of `POST /v1/score` round-trips to a Uvicorn scorer whose window store is Redis across the Docker bridge, on Windows. Per-attempt cost ≈ 5.3 ms mean — inside the TRD `/v1/score` p99 < 100 ms budget. The prior audit already found the machine marginal (measured 58.5× vs a 60× target). To confirm in Phase 10: profile one `/v1/score`, compare Redis-bridge vs `localhost` vs in-memory window store, measure with a concurrent client. |
| **Evidence** | `evidence/day-9/phase-1/verify60x-throughput.json`, `verify60x-throughput.log`, `verify60x-remaining.log` |
| **Demo impact** | **None known.** The demo drives replay at speed 60 with episode pacing, never a 20× speed-0 soak. Live checkout latency (`/v1/score` = 36 ms in the Phase-1 smoke) is well within budget. |
| **Fix status** | Not attempted. Threshold **will not** be weakened (Plan §8). Decision deferred to Phase 10 — either (a) the serving path has a real inefficiency worth fixing, or (b) the gate threshold is unrealistic for this reference machine and is re-scoped with evidence and a recorded decision. |
| **Verification method (when actioned)** | Re-run `--gate throughput` ×2 from clean state; both `pass: true`, or a Decisions.md entry justifying a revised threshold with profiling data. |
| **Residual risk** | Low for the demo. Medium for any "handles production traffic" claim — Phase 10 must state the real single-instance ceiling. |

---

## DEF-D9-002 — manual-path startup hides Redis / model / Layer-2 status

| Field | Detail |
|---|---|
| **Severity** | P3 |
| **Category** | Observability / documentation |
| **Phase found** | 1 (manual-path startup baseline) |
| **Component** | `services/scorer/app.py` (no logging config for the `tollgate.scorer` logger); README "Running the demo" |
| **Repro** | Run the exact README command `… uv run uvicorn services.scorer.app:create_app --factory --port 8080 --log-level info`; observe stderr. |
| **Expected** | Operator can see whether Redis connected (vs in-memory fallback), which model loaded, and whether Layer 2 is active. |
| **Actual** | Only `uvicorn*` INFO lines + the two `config:` warnings appear. `Connected to Redis …`, `loaded Layer-1 model …`, `loaded Layer 2 for merchant_demo …` are emitted on the `tollgate.scorer` logger at INFO but never reach a handler — `--log-level` configures only Uvicorn's own loggers. The lines were only captured via a wrapper calling `logging.basicConfig(level=INFO)`. |
| **Root cause** | No root/app logging configuration; the app relies on Uvicorn's logging setup, which is scoped to `uvicorn`, `uvicorn.error`, `uvicorn.access`. |
| **Evidence** | `evidence/day-9/phase-1/scorer-startup.log` (README path — lines absent) vs `scorer-startup-info.log` (wrapper — lines present). |
| **Demo impact** | Cosmetic. But the **Phase 2 Compose exit gate** requires the Layer-2 line to be visible in the scorer startup log ("verified via … the scorer startup log, not merely 'it started'"), so this must be fixed as part of Phase 2's scorer entrypoint. |
| **Fix status** | **FIXED in Phase 2.** `deploy/uvicorn-logging.json` (a dictConfig based on uvicorn's default + a `tollgate` logger at INFO); the scorer Dockerfile CMD passes `--log-config deploy/uvicorn-logging.json`. Verified: `docker compose logs scorer` shows `Connected to Redis …`, `loaded Layer-1 model …`, `loaded Layer 2 for merchant_demo: policy v2, cusum_h=318.133 …`. |
| **Verification method** | `docker compose up` → `docker compose logs scorer \| grep "loaded Layer 2"` returns the line. ✓ |
| **Residual risk** | The README **manual** path (`uv run uvicorn … --log-level info`) still does not surface these lines — it does not pass `--log-config`. Cosmetic; reopen as P3 if manual-path observability is later required. |

---

## DEF-D9-003 — Phase-2 bootstrap drifted the reference corpus

| Field | Detail |
|---|---|
| **Severity** | P2 |
| **Category** | Data-artifact integrity (provenance) — self-inflicted during Phase 2 |
| **Phase found** | 2 (full `pytest tests/ -q` against the containerized Redis) |
| **Component** | `data/corpus/tollgate.db` (gitignored 18 MB negative-control reference corpus) |
| **Repro** | `uv run pytest tests/acceptance/test_d6_provenance.py::test_corpus_identity_is_recorded_and_matches_the_real_corpus` |
| **Expected** | `sha256(data/corpus/tollgate.db) == eval/outputs/d6.json["provenance"]["corpus_db_sha256"]` (`7f6ef6dd…`). Passed at the Phase-1 baseline. |
| **Actual** | Current corpus SHA `9e1e3346…` ≠ recorded `7f6ef6dd…`. `1 failed, 618 passed, 2 xfailed`. |
| **Root cause (established)** | While iterating on Phase 2, one `docker compose up` ran the `bootstrap` service **before** the corpus-working-copy guard existed. `scripts/learn_store_baseline --db data/corpus/tollgate.db` re-upserted 8 `store_baseline` rows with a fresh `updated_at = SystemClock().now_ms()` (`learn_store_baseline.py:222`, `updated_at` is wall-clock, non-deterministic), and `scripts/tune_cusum --db data/corpus/tollgate.db` appended 20 `policy_config` rows (versions 9 / 5). The 20 policy rows were then deleted (restoring `MAX(version)` to 8 / 4), but the `updated_at` bump and the DELETE's free pages remain — the file no longer hashes to `7f6ef6dd…`. |
| **Functional impact** | **None.** 618/619 pre-existing tests still pass; only this SHA-equality provenance check notices. `store_baseline.updated_at` is metadata read by no detector or metric; the removed `policy_config` v9 rows were never referenced (the eval pins `policy_version: 1`). Every S-6 artifact (`eval/outputs/d6.json`, `models/audit.json`, `models/l1-lgbm-v1.json`, `models/platt-v1.json`) SHA is **unchanged** from Phase 0. |
| **Evidence** | `evidence/day-9/phase-2-pytest.log`; the timestamp analysis (all 8 `store_baseline.updated_at == 1788419860256`, the 20 policy rows all `created_at == 1788419869235`). |
| **Fix status** | **Recurrence prevented** — `scripts/compose_bootstrap.py::ensure_corpus_working_copy()` now `shutil.copy2`s the corpus to `/data/corpus.db` on the volume and runs learn/tune against that copy; `data/corpus/tollgate.db` is never written under Compose (verified: `SELECT COUNT(*),MAX(version) FROM policy_config` = `(156, 8)` before and after a clean `down -v && up`). **The drift itself is NOT restored** — no pristine copy exists (corpus is gitignored, never tracked; `updated_at` is non-deterministic). |
| **Remediation (Phase 5, later session)** | Phase 5 re-derives `d6.json` via `eval.harness` to a scratch dir and `diff_d6.py`s it. Either (a) accept the regenerated provenance (records the current corpus SHA) after a reviewed diff shows 0 substantive metric differences, or (b) rebuild a pristine corpus (`eval.corpus.replay_corpus` — deterministic on seed 42 — then `learn_store_baseline` + `tune_cusum`) and regenerate `d6.json` against it. **Hard prerequisite for the Phase 5 gate.** |
| **Residual risk** | Low. The corpus is self-consistent and its attack/negative data (seed-42 deterministic) is untouched; only baseline metadata drifted. A metric-level diff in Phase 5 will confirm zero substantive change. |
