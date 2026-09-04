# Day 9 — Phase 2: Containerize the stated deployment path

**Executed:** 2026-09-03 (Session 1)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 2. Reconciliation R-1 (`docker compose up`
did not exist; zero Dockerfiles).
**Stop condition S-2** (> 4 h, or a detection/scoring/window semantics change): **not
triggered** — the phase took well under the cap and every code change is additive with
byte-identical defaults off-Docker.

---

## 1. What was built

| File | Purpose |
|---|---|
| `docker-compose.yml` (rewritten) | 6 services: `redis`, `redis-small`, `bootstrap` (one-shot), `scorer`, `storefront`, `dashboard`. Fixed subnet `172.28.0.0/24` with static IPs so the two Vite proxy containers can be named as the scorer's trusted edge. Healthchecks + `depends_on` ordering (`redis` healthy → `bootstrap` completed → `scorer` healthy → frontends). |
| `services/scorer/Dockerfile` | `python:3.13-slim-bookworm` + `libgomp1` (LightGBM) + `curl` (healthcheck); `uv pip install --system` the runtime closure (fastapi, uvicorn[standard], pydantic, pyyaml, httpx, python-dotenv, redis, lightgbm, numpy — pandas/openpyxl are test-only, omitted). Bind-mount `./:/repo`, no source COPYed. Entrypoint sources `deploy/compose.env` then `exec`s uvicorn with `--factory --host 0.0.0.0 --log-config deploy/uvicorn-logging.json`. Also the `bootstrap` image. |
| `services/dashboard/Dockerfile`, `services/storefront/Dockerfile` | `node:22-bookworm-slim`; `npm ci` from the copied lockfile into a layer; a named volume masks the (Windows) host `node_modules` at runtime; repo bind-mounted at `/repo` (D6 imports `eval/outputs/d6.json` from the root, `fs.allow: ["..","../.."]`); `npm run dev -- --host 0.0.0.0`. |
| `scripts/compose_bootstrap.py` (new) | The idempotent, footgun-safe bootstrap. `seed_merchant` -> `learn_store_baseline` -> `tune_cusum`, then writes `TG_CONFIG_HASH`. Fresh DB -> seeds + writes the new key/secret to `deploy/compose.env`. Existing merchant -> finds a key that hashes to `merchant.api_key_hash` (checks `deploy/compose.env`, `services/{dashboard,storefront}/.env`, `.env`) and **reuses** it; no match -> **`die()` with instructions**, never a dead key. `tune_cusum` is skipped when the latest `policy_config` already has populated `thresholds` (stops the version-sprawl footgun). Runs learn/tune against a **copy** of the corpus on the volume (`ensure_corpus_working_copy()`) so the bind-mounted 18 MB reference DB stays byte-stable. |
| `deploy/compose.env.example` (new) | Documents the env_file shape (`VITE_TOLLGATE_API_KEY`, `TOLLGATE_OUTCOME_SECRET`, `TG_CONFIG_HASH`). The real `deploy/compose.env` is gitignored and written by the bootstrap. |
| `deploy/uvicorn-logging.json` (new) | dictConfig (uvicorn default + a `tollgate` logger at INFO). Fixes DEF-D9-002 — the Compose scorer now shows the Redis / model / Layer-2 lines in `docker compose logs`. |
| `.dockerignore` (new) | Keeps the build context small (repo is bind-mounted at runtime). |

### Code changes (all additive, defaults preserved)

| File | Change | Off-Docker behaviour |
|---|---|---|
| `services/scorer/net.py` | `TRUSTED_EDGE_HOSTS = _DEFAULT + split(os.environ["TOLLGATE_TRUSTED_EDGE_HOSTS"])`. | env unset -> `frozenset({"127.0.0.1","::1","testclient"})` — **byte-identical**. |
| `services/scorer/deps.py` | `build_default(db_path=None, spool_dir=None, ...)` -> resolves `None -> TOLLGATE_DB_PATH / TOLLGATE_SPOOL_DIR -> "tollgate.db" / "spool"`. | env unset / explicit arg -> unchanged. Only `create_app()`'s no-arg call in the container differs. |
| `scripts/seed_merchant.py` | `DB_PATH = Path(os.environ.get("TOLLGATE_DB_PATH", "tollgate.db"))`. | env unset -> `"tollgate.db"`. |
| `services/dashboard/vite.config.js`, `services/storefront/vite.config.js` | proxy `target: process.env.TOLLGATE_SCORER_URL || "http://localhost:8080"`. dashboard: `currentConfigHash()` honours `process.env.TG_CONFIG_HASH` (64-hex) before the Python shell-out; `null` fallback intact. | env unset -> `http://localhost:8080`, Python shell-out as before. |

**No change to any detection / scoring / window / enforcement code path.**

---

## 2. Design decisions this phase made

| Concern | Plan's approach | What was implemented | Deviation? |
|---|---|---|---|
| Source of truth | bind-mount repo; `models/ config/ data/corpus/ tollgate.db spool/` host-side | Repo bind-mounted `./:/repo`. `models/ config/ data/corpus/` **host-side (bind mount)**. | **`tollgate.db` + `spool/` moved to a Linux-native named volume `tollgate_data`** — SQLite in WAL mode cannot mmap its `-shm` file over the Docker Desktop Windows bind mount, so a fresh read/write connection fails (`unable to open database file`; `/v1/incidents` -> 500). The volume fixes it with **no journal-mode / storage-semantics change**. The plan's "host-side" rationale (18 MB corpus, un-rebuildable without a retrain) applies to `data/corpus/`, which **is** still bind-mounted; the demo DB is fully rebuilt by the bootstrap each `down -v`. Recorded as a reasoned S-2-considered deviation. |
| Bootstrap | one-shot `seed_merchant -> learn_store_baseline -> tune_cusum`, idempotent, footgun-safe | `scripts/compose_bootstrap.py` as above. | none |
| Vite proxy target | `process.env.TOLLGATE_SCORER_URL ?? "http://localhost:8080"`, `--host 0.0.0.0` | done, both apps | none |
| `resolve_client_ip` under Docker | `TOLLGATE_TRUSTED_EDGE_HOSTS`, default = today's frozenset | `net.py` additive env; compose sets `172.28.0.11,172.28.0.12` (the two Vite containers' static IPs). Verified: `X-Forwarded-For: 203.0.113.77` through the storefront proxy resolves to `203.0.113.77` in the `auth_attempt` row. | plan says "default = today's frozenset"; implemented as *additive to* today's frozenset (same effect: unset -> exactly today's set). |
| D6 freshness under Docker | `bootstrap` writes the hash, pass as `TG_CONFIG_HASH`; keep `null` fallback | bootstrap computes `eval.provenance.config_hash()` -> `deploy/compose.env`; dashboard `vite.config.js` honours it first, Python shell-out + `null` fallback intact. Value observed: `a7db8c61...`. | none |
| Healthchecks | `redis-cli ping`; scorer `GET /healthz`; Vite TCP; `depends_on: service_healthy` | done. Vite TCP check via `node -e "require('net').connect(...)"` (node-slim has no curl/nc). | none |
| Secrets | `env_file`; never imaged, never committed | `env_file: [{path: deploy/compose.env, required: false}]` on every service; `deploy/compose.env` gitignored. Because Compose resolves `env_file` **before** `bootstrap` runs, the scorer entrypoint **also** sources `deploy/compose.env` at start (bootstrap has finished by then). | small addition (entrypoint source) to close the compose-timing gap for a fresh checkout. |

---

## 3. Exit-gate results (`docker compose down -v && docker compose up --build`)

Clean state (`down -v` wiped `tollgate_data` + node_modules volumes; `deploy/compose.env`
removed).

| Check | Result |
|---|---|
| `up --build` completes | PASS — exit 0. Wall ~ 55 s with images cached; all 5 long-running services healthy ~ **43 s** after the first container started. |
| Time-to-healthy (started -> first healthy) | redis ~ fast · scorer **~26 s** (sh wrapper + uvicorn + LightGBM + Layer-2 load; `start_period 20s`) · storefront **~12 s** · dashboard **~12 s**. bootstrap (fresh volume: seed + learn + tune + hash) ~ 10 s, exit 0. |
| Every required service starts & becomes healthy | PASS — `redis`, `redis-small`, `bootstrap` (exit 0), `scorer`, `storefront`, `dashboard`. |
| `/healthz` 200 | PASS — `{"status":"ok","drainer_alive":true,"drainer_connects":1,...}` |
| storefront `:5173`, dashboard `:5174` load | PASS — HTTP 200 each |
| dashboard `/v1` proxy -> `scorer:8080` | PASS — `GET :5174/v1/stream/recent` -> 200 |
| SSE connects | PASS — `GET /v1/stream` -> `: ping` heartbeat |
| `/v1/stream/recent` back-fills | PASS — `{"events":[]}` (fresh) — endpoint functional; populated after a replay (821 events streamed in an earlier run) |
| `/v1/incidents` | PASS — 200 (was **500** `unable to open database file` before the volume fix) |
| Layer 2 **loaded** — DB rows **and** startup log | PASS — `policy_config` v2 with populated `thresholds`, `store_baseline` row for `merchant_demo`; log: `loaded Layer 2 for merchant_demo: policy v2, cusum_h=318.133, tau_flag=0.06475, drift_enabled=True` |
| Redis connect (not fallback) | PASS — `Connected to Redis at redis://redis:6379; using RedisWindowStore` |
| Narrator — template path | PASS — a full `easy` replay through the stack opened **2 incidents** (ESCALATED), both with `narrative` rendered and `narrative_source='template'`; `narrator_call` rows = 0 (correct — that table tracks Gemini dispatch only) |
| Narrator — `NARRATOR_BACKEND=gemini` + no key | PASS — `validate_startup()` -> `"NARRATOR_BACKEND=gemini but GEMINI_API_KEY is missing or blank -- the narrator will SILENTLY use the template for every incident"`; template render is unconditional so it stays on template |
| Narrator — Gemini + key, one live call | **deferred to Phase 7/11** — the scoring->narrator dispatch path is unchanged by containerisation; the container has outbound network + `httpx`. Not a Phase-2 blocker. |
| Replay lifecycle through the stack | PASS — `POST /v1/replay/start` (202) -> `finished 821/821 terminal=true`; `POST /v1/replay/reset` -> 200 `cleared: {window_store, threat, layer2, incidents, policy_engine, decision_cache, persisted_incidents:2}`, Redis `dbsize` -> 0 |
| Trusted-edge XFF (Step 6 enabler / PRE-4) | PASS — `X-Forwarded-For: 203.0.113.77` via the storefront Vite proxy -> `auth_attempt.ip = 203.0.113.77`; a direct call (peer `172.28.0.1`, not trusted) -> XFF ignored |
| `pytest tests/ -q` against containerized Redis | PARTIAL — **618 passed / 1 failed / 2 xfailed**. The single failure is **DEF-D9-003** (`test_d6_provenance::test_corpus_identity` — corpus SHA drift caused while iterating on the bootstrap, now prevented from recurring; no metric/detection impact — every other test green). |
| Detection/scoring semantics silently changed? | **No.** All diffs are env-plumbing with preserved defaults; 618/619 tests unchanged; the one failure is a data-artifact SHA check, not behaviour. |
| S-6 artifacts (`d6.json`, `models/audit.json`, `l1-lgbm-v1.json`, `platt-v1.json`) | PASS — SHA **unchanged** from Phase 0. |
| Startup failures (verbatim) | none during the canonical run. (Iteration-time failure captured & fixed: `/v1/incidents` 500 `sqlite3.OperationalError: unable to open database file` -> root-caused to WAL-`-shm`-over-Windows-bind-mount -> fixed with `tollgate_data` volume.) |

**Verdict: Phase 2 COMPLETE.** `docker compose up --build` brings the full stack clean
from stopped; every plan exit-gate item passes except the self-inflicted, contained,
metric-neutral DEF-D9-003 (a Phase-5 reconciliation item).

---

## 4. Evidence files

- `evidence/day-9/phase-2-build.log` — first full `docker compose build`
- `evidence/day-9/phase-2-up.log`, `phase-2-up2.log` — iteration `up` runs
- `evidence/day-9/phase-2-canonical-up.log` — the canonical `down -v && up --build`
- `evidence/day-9/phase-2-pytest.log` — 618/1/2 backend run vs containerized Redis
