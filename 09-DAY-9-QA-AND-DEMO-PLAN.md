# Day 9 — Professional QA, Demo Rehearsal & Release Readiness

**Deliverable of *this* planning task:** this file, to be written to the repo root as
`09-DAY-9-QA-AND-DEMO-PLAN.md` as the first action of Day 9 execution.

---

## Context

Tollgate is a pre-auth card-testing defence built over Days 1–8. Day 9 exists to answer
one question with evidence: *if I demonstrated this to a judge today, would it work
correctly, visibly, repeatably and predictably from start to finish?*

Two prior audits bracket the current state. `QA-AUDIT-2026-09-01.md` found **24 defects
(6 critical)** and returned **NOT READY FOR DEMO** — the detection engine worked, but
every operator control that drives it was broken. `METRICS-AUDIT-2026-09-02.md` found
**40 D6 defects**. Both were remediated. Neither remediation has been independently
re-verified, and **none of it is committed**: 55 modified + ~60 untracked files sit in
the working tree at HEAD `8cf17d9`, which describes none of the code actually under test.

Day 9 treats the repository as a release candidate that must earn **DEMO READY** or
**NOT DEMO READY**. Nothing is assumed fixed because a patch exists or a document says so.

---

## 0. Specification reconciliation — findings from this planning pass

Read-only inspection of the repo against the 9 v2 spec documents, `Decisions.md`,
`Flow.md`, `README.md`, and all Day-6/8 audit artifacts. **Five contradictions found.**

### R-1 — `docker compose up` does not exist. **P0 prerequisite.**

| Source | Claim |
|---|---|
| `03-TRD-v2.md:18` | `Deployment \| docker compose up on a laptop` |
| `03-TRD-v2.md:426` | `docker compose up   # redis, scorer, dashboard, storefront` |
| `03-TRD-v2.md:73` | repo layout names `docker-compose.yml` |
| **Repository** | `docker-compose.yml` defines **only** `redis` + `redis-small`. `find . -iname "Dockerfile*"` → **zero results**. |
| `README.md:130-142` | Documents a manual `uv run uvicorn …` + two `npm run dev` startup. |

The stated deployment path is unimplemented. **Resolved: Day 9 builds it** (Phase 2) —
the judge's path must be real, and an untested deployment method is not a release gate.

### R-2 — App Flow J6 steps 6–8 are unbuilt. The spec calls step 6 "the demo".

`06-APPFLOW-v2.md:209` specifies 8 steps for Demo Act One.
`DemoControlStrip.jsx:7` states: *"The negative-control selector and flood / kill-scorer
toggles remain omitted."* Verified — `TIER_OPTIONS`, speed, pace-from-episode, Launch /
Stop / Reset only.

| J6 step | Status |
|---|---|
| 1–5 (normal checkout → launch → threat transition → incident → confirm) | Demonstrable through the UI today |
| **6 — legitimate customer checks out from the SAME CGNAT IP as the attacker** | **Not built.** Spec: *"Step 6 is the demo."* |
| **7 — flood toggle → rules-only shed rung** | **Not built.** The middle availability rung is assertable, never showable. |
| **8 — kill-scorer toggle → fail-open rung** | **Not built.** |

**Resolved: Day 9 builds 6–8** (Phase 3). These are the three claims a judge probes hardest.

### R-3 — The AUDIT-001..024 remediation has no in-repo evidence log.

Source comments prove the fixes were applied (`FIX-003 (AUDIT-001)` in
`packages/features/store.py:123`, `FIX-016 (AUDIT-017)` in `compute.py:192`, `FIX-020
(AUDIT-023)` in `EventTicker.jsx:54`, and ~15 more). But the remediation plan lives
**outside the repository** at `~/.claude/plans/https-claude-ai-code-artifact-c352b401-a-sprightly-seal.md`
(146 `FIX-0` references), and **no document records which findings were verified fixed,
how, or with what evidence.** Contrast the D6 work, which has four in-repo artifacts.

Consequence: **all 24 findings must be re-verified from zero** (Phase 9). Spot-checks
during this planning pass found `RedisWindowStore.clear()` present (A-001), replay
routes key-gated (A-021), checkout fields wired to controlled state with a real
browser-side SHA-256 (A-019), `(Day 1)` titles gone (A-024). Encouraging — not evidence.

### R-4 — The D6 remediation is **more** complete than the task brief assumes.

The brief warns that "frontend phases, rendering tests, routing, accessibility/responsive
testing and Playwright E2E were still incomplete at the checkpoint." That checkpoint is
superseded. `METRICS-IMPLEMENTATION-LOG-2026-09-02.md` records Phases 0–7 complete;
`METRICS-AUDIT-VERIFICATION-2026-09-02.md` records **40 FIXED / 0 retained / 0 N/A**,
with 205 vitest + 68 Playwright (17 checks × 4 viewports) + axe-clean + contrast ≥ 4.5:1.

Day 9 **re-runs** these gates rather than re-doing the work. One item is genuinely
outstanding and cannot be self-certified: **§31 step 11, the reviewer test** — a person
who has not read the source opens `#/metrics` and answers twelve questions aloud. Day 9
carries this as a human checkpoint, not a P-severity defect.

### R-5 — Two Day-8 features remain deferred and affect the demo narrative.

- `/v1/stream` **is unauthenticated** (Decision 94, re-deferred past Day 7; README:34).
  Loopback-only for the demo, but it publishes rule-fire detail. A judge may ask.
- **Outcome-derived features read `0.0`** (`decline_rate_per_ip_5m` and two siblings).
  App Flow J6 step 3 says *"decline rate departs the baseline band"* — it cannot. The
  spec already annotates this (Decision 34/C8), and the demo script must say so plainly.

### Reconciliation summary

| Area | Spec requires | Day 8 claims | Prior QA found | Repo actually contains |
|---|---|---|---|---|
| Deployment | `docker compose up` (4 services) | not addressed | not tested | redis only; **no Dockerfiles** |
| Replay lifecycle | repeatable demo | 8 wire states, backend-owned | 6 critical defects | fix code present, **unverified** |
| D6 Metrics | honest, complete | 40/40 fixed + 3 test tiers | AUDIT-011 | verification doc; **not independently tested** |
| J6 Act One | 8 steps | steps 1–5 | steps 6–8 not reached | **6–8 absent** |
| Whole tree | — | Days 1–8 complete | — | **entirely uncommitted** |

---

## 1. Objective and verdict definition

Produce an evidence-based **DEMO READY** / **NOT DEMO READY** verdict. No third option.

**DEMO READY requires all of:**
1. Zero P0. Zero unresolved P1.
2. Two complete demo rehearsals, both from clean state, both successful.
3. `docker compose up` brings the full stack clean from a stopped state.
4. Green: `pytest tests/`, `vitest run`, `playwright test`, `verify_60x --gate all`.
5. No known data-integrity failure.
6. No known security-critical failure.
7. No known repeatability failure — the same demo runs twice with no manual backend intervention.

**Severity rules:**

| | Definition |
|---|---|
| **P0** | The demo cannot proceed. Blocks the verdict. |
| **P1** | The demo proceeds but a core claim or flow is broken/wrong. Blocks the verdict. |
| **P2** | Visible defect or serious UX weakness a judge would notice. Documented, may ship. |
| **P3** | Polish / documentation. Documented, ships. |

If a remaining issue could reasonably **interrupt, invalidate, embarrass, confuse, or
materially undermine** the demo, the verdict is NOT DEMO READY.

---

## 2. Scope

**In scope:** everything in §4 below — environment, regression, API, detection,
evaluation, security, reliability, performance, UI/UX, replay, Docker, two rehearsals,
triage, hardening, final audit, demo script.

**Explicit scope additions (authorized during planning):** Phase 2 (containerization) and
Phase 3 (J6 steps 6–8). Both are construction, not remediation; both are gated by their
own tests before any QA phase runs against them.

**Out of scope:** `/v1/stream` authentication (Decision 94 — recorded as a known
limitation, not fixed); the BIN-metadata join; retraining any model; regenerating
`eval/outputs/d6.json` other than to prove deterministic reproduction; the
`handmade_40` human oracle fixtures (both stay `xfail`).

---

## 3. Prerequisites and stop conditions

**Verified present on this machine:** Python 3.13.3, Node v22.14.0, npm 11.7.0,
Docker 29.1.3, Compose v2.40.3-desktop.1, uv 0.11.0. `.env`, both frontend `.env` files,
all three `node_modules`, `models/`, `data/corpus/tollgate.db` (18 MB), `tollgate.db`.

**Must be resolved before Phase 4 (first QA phase) can begin:**

| # | Prerequisite | Why |
|---|---|---|
| PRE-1 | Working tree committed to a `day-9` branch | Baseline SHA otherwise describes none of the code under test; no revert point for Phase 13 |
| PRE-2 | Docker Compose stack exists and starts (Phase 2) | Every QA phase after it runs against the deployment path the judge uses |
| PRE-3 | `seed_merchant` / `learn_store_baseline` / `tune_cusum` bootstrap reproducible inside the stack | Without `store_baseline` + tuned `policy_config`, Layer 2 silently does not load and the demo degrades to the Day-5 rules+model path |
| PRE-4 | An attacker-IP source for J6 step 6 | The CGNAT money shot needs a real IP under live enforcement |

**STOP CONDITIONS — halt Day 9, report, do not continue:**

- **S-1** Baseline test run (Phase 1) shows ≥ 5 failures whose causes are not immediately
  classifiable → the tree is not a release candidate; triage before anything else.
- **S-2** Phase 2 containerization exceeds 4 hours or requires changing detection,
  scoring, or window semantics to work → stop, fall back to the README manual path as the
  demo path, and record R-1 as an unfixed P1.
- **S-3** Any Phase 3 control requires faking a decision, tier, or availability state
  rather than exercising the real code path → do not build it; record as a limitation.
- **S-4** Rehearsal #2 reproduces any Rehearsal #1 failure → **NOT DEMO READY**, stop
  hardening, write the audit.
- **S-5** Any security finding in Phase 6 that lets client-asserted data reach a feature,
  a model input, or an enforcement decision → P0, stop all other work.
- **S-6** `eval/outputs/d6.json` or `models/audit.json` SHA changes without a deliberate,
  reviewed, diffed regeneration → stop; the evaluation artifact has been contaminated.

---

## 4. Phases

Ordering respects **test before fixing**: the existing system is baselined unmodified
(Phase 1) before either authorized construction phase.

### Phase 0 — Baseline snapshot and commit  *(~45 min)*

1. Record: git SHA, branch, full `git status --porcelain`, Python/Node/npm/Docker/
   Compose/uv versions, `.env` contents with secrets redacted, Redis reachability,
   `tollgate.db` row counts (`merchant`, `attempt_score`, `incident`, `policy_config`,
   `store_baseline`), SHA-256 of `eval/outputs/d6.json` + `models/audit.json` +
   `models/l1-lgbm-v1.json` + `models/platt-v1.json`, `data/corpus/tollgate.db` size.
2. `git checkout -b day-9` from `day-2`.
3. Commit the tree **unmodified**, message recording it as the untested Day-8 +
   remediation baseline (AUDIT-001..024 + M-001..040), naming both remediation sources.
4. Record the new SHA as the **Day 9 baseline SHA**. Every later change is its own
   atomic commit.

**SHAs to honour throughout:** `d6.json` = `29edcb22…`, `models/audit.json` = `ce75cb7f…`.
Any change is stop condition S-6.

### Phase 1 — Baseline test run, unmodified  *(~1 h)*

Run **everything**, against the README manual path, before touching anything.

```bash
docker compose up -d redis redis-small
uv run pytest tests/ -q --durations=25          # expect ~619 passed, 2 xfailed
uv run pytest tests/ -q -m safety
uv run pytest tests/ -q -m slow
uv run pytest tests/ -q -m redis
uv run pytest tests/ -q -m metamorphic
uv run pytest tests/ -q -m characterization     # informational, never a gate
# reversed file order (hermeticity regression — AUDIT-010)
uv run pytest -q $(python -c "import pathlib;print(' '.join(sorted((str(p) for p in pathlib.Path('tests').rglob('test_*.py')), reverse=True)))")
npm --prefix services/dashboard run test:run
npm --prefix services/dashboard run test:cov    # thresholds 85/85/80
npx --prefix services/dashboard playwright test # 68 = 17 checks x 4 viewports
uv run python -m scripts.verify_60x --gate all --redis redis://localhost:6379/9
uv run python -m scripts.verify_60x --gate 60x --faulthandler
```

Record for each: total / passed / failed / skipped / xfail / xpass / error / warnings /
duration. **Classify every failure** as: genuine defect · stale test · environment ·
intentional xfail · spec mismatch · implementation mismatch · test-infrastructure.
**Do not modify any test to make the suite green.**

Also record the **manual-path startup baseline**: cold-start time to `/healthz` 200, and
the scorer's startup log lines (model load, Layer-2 load, narrator backend, Redis
connect-or-fallback, any `config:` warning).

### Phase 2 — Containerize the stated deployment path  *(~3 h, gated by S-2)*

Make `docker compose up` real: `redis`, `scorer`, `dashboard`, `storefront`
(+ `redis-small` retained for the eviction test, + a one-shot `bootstrap`).

**Design decisions this phase must implement:**

| Concern | Approach |
|---|---|
| Source of truth | Bind-mount the repo into the containers (dev-parity). `models/`, `config/`, `data/corpus/`, `tollgate.db`, `spool/` stay host-side — the corpus is 18 MB and gitignored; a self-contained image cannot rebuild it without a LightGBM retrain. |
| Bootstrap | A `bootstrap` one-shot service running `seed_merchant` → `learn_store_baseline` → `tune_cusum`, idempotent, that the scorer `depends_on: service_completed_successfully`. **Must handle the known `INSERT OR IGNORE` footgun** — if a merchant row already exists, `seed_merchant` prints a key that was never stored and every request 401s. Detect and either reuse or fail loudly; never print a dead key. |
| Vite proxy target | Both `vite.config.js` files hardcode `http://localhost:8080`. Parameterize to `process.env.TOLLGATE_SCORER_URL ?? "http://localhost:8080"` so the manual path stays byte-identical and the container path targets `http://scorer:8080`. Both apps also need `--host 0.0.0.0`. |
| `resolve_client_ip` under Docker | `net.py:12` trusts `X-Forwarded-For` only from `{127.0.0.1, ::1, testclient}`. A Vite container's bridge IP is none of these, so all storefront traffic collapses to one container IP. Introduce `TOLLGATE_TRUSTED_EDGE_HOSTS` (comma-separated, **default = today's frozenset**, so behaviour off-Docker is unchanged). This is exactly Threat Model K8's *"validated against the merchant's declared edge"* — spec-aligned, and it is also PRE-4's enabler. |
| D6 freshness under Docker | `services/dashboard/vite.config.js` shells out to `python -c "from eval.provenance import config_hash"`. A node image has no Python → `null` → D6 honestly renders *"freshness not verifiable in this build"*. **That is a silent degradation of a D6 honesty feature under the judge's own deployment path.** Fix by having `bootstrap` write the hash and passing it as `TG_CONFIG_HASH`; keep the `null` fallback intact. |
| Healthchecks | `redis-cli ping`; scorer `GET /healthz`; both Vite servers TCP. `depends_on: condition: service_healthy`. |
| Secrets | `VITE_TOLLGATE_API_KEY` and `TOLLGATE_OUTCOME_SECRET` via compose `env_file`. Never baked into an image, never committed. |

**Phase-2 exit gate:**
```bash
docker compose down -v && docker compose up --build   # from fully stopped
```
- All services healthy; record time-to-healthy per service.
- `/healthz` 200; storefront :5173 and dashboard :5174 load.
- SSE connects; `GET /v1/stream/recent` back-fills.
- Layer 2 **loaded** — verified via a `policy_config` + `store_baseline` row and the
  scorer startup log, not merely "it started".
- Narrator: template path works; `NARRATOR_BACKEND=gemini` with no key logs a `config:`
  warning and stays on template; with a key, one successful Gemini call observed.
- `pytest tests/ -q` still green against the containerized Redis.
- Record every startup failure **verbatim**, never summarized.

### Phase 3 — Build J6 steps 6–8  *(~3 h, gated by S-3)*

Three demo controls. **Every one must exercise the real code path.** All gated behind
`TOLLGATE_DEMO_CONTROLS=1` (default off) and visibly labelled in the UI as demo controls,
so production behaviour stays unambiguously distinguishable.

**Step 6 — CGNAT co-tenancy (the money shot).**
The storefront checkout must be attributable to an IP currently under enforcement.
- New `GET /v1/demo/cotenant-ip` (demo-gated, key-required) returns one IP from the live
  enforcement ledger, or 404 when none is enforced.
- Storefront `?demo=1` gains a clearly-labelled **"checkout as co-tenant"** control that
  sends `X-Forwarded-For: <that ip>`, honoured because the Vite proxy host is in
  `TOLLGATE_TRUSTED_EDGE_HOSTS` (Phase 2).
- The customer then hits the real `(ip, ua_class)` entity, the real store-relative
  quantile thresholds, and the real `challenge` auto-ceiling — passes one checkbox, gets
  the order. **Nothing about the decision is special-cased.**
- Tests: the co-tenant attempt resolves to `challenge` (not `block`); a script-class UA on
  the same IP does not; the route 404s when `TOLLGATE_DEMO_CONTROLS` is unset.

**Step 7 — Flood toggle (rules-only shed rung).**
- DC-strip toggle starting a **real** concurrent load against `/v1/score`, exceeding
  `admission: rate_per_s 50 / burst 200` (`config/policy.yaml`), draining the merchant
  token bucket through `AdmissionController.try_consume` exactly as a real flood would.
- Observed, not asserted: `X-Tollgate-Shed: 1`, `degraded_reason: "shed"`,
  `availability.shed: true` on SSE, the monochrome D0 rules-only banner, and a normal
  checkout still completing.
- **Never** a flag that sets `shed` directly.

**Step 8 — Kill-scorer toggle (fail-open rung).**
Two distinct stories; build the one that proves the claim, show the other for free:
- *In-scorer fail-open* (the rung the TRD names): a demo-gated fault injector making
  `score_attempt()` raise, driving the real `_fail_open` path at
  `services/scorer/routes_score.py:182` — `allow` returned, `degraded_reason:
  fail_open:<reason>` row written, `alert` on SSE once per clock window, D0 fail-open
  banner.
- *Scorer unreachable* (what App Flow step 8 literally shows): free under Phase 2 —
  `docker compose stop scorer`. The dashboard's connection chip degrades; the storefront's
  own client-side path completes the checkout.
- Tests: fail-open returns `allow` and **never a 5xx**; a sustained breach alerts exactly
  once per clock window; the injector is inert without the env flag.

**Phase-3 exit gate:** new acceptance tests green; full `pytest tests/` still green;
`vitest` + `playwright` still green; each control demonstrated once manually.

### Phase 4 — Backend / API QA  *(~1.5 h)*

Every route in `services/scorer/`: `routes_score`, `routes_stream`, `routes_replay`,
`routes_incidents`, `routes_outcome`, `/healthz`, `/metrics`.
Per route: happy path · auth present/absent/invalid · malformed body · oversized body ·
missing required fields · wrong types · duplicate `event_id` · different payload with the
same `event_id` · concurrent identical requests. Record status, body shape, and whether
the error text is operator-readable rather than a stack trace.

### Phase 5 — Detection & evaluation QA  *(~2 h)*

**Detection** — against the running service, not only unit tests: R1 (attempts/IP), R2
(distinct cards/IP), R3 (distinct cards/BIN) as **floors that never exceed the `challenge`
auto-ceiling** (Decisions 15/70); Layer 1 model + Platt + prior correction; Layer 2a
CUSUM; Layer 2b distinct-card SPRT; entity resolution `card → ipua → ip` (store-wide
unrepresentable); hysteresis (θ_T enter / θ_T − 0.08 exit); blast-radius `K_max`;
P3 corroboration; incident state machine `OPEN → ESCALATED → COOLING → CLOSED`;
control arm. **Do not change a threshold to make the demo more dramatic.**

**Evaluation** —
```bash
uv run python -m eval.harness --split all --seed 42 \
    --corpus-db data/corpus/tollgate.db --model-dir models/ --out <scratch>
python scripts/diff_d6.py eval/outputs/d6.json <scratch>/d6.json \
    --ignore provenance.build_hash --ignore provenance.generated_at \
    --ignore provenance.head_at_generation --ignore provenance.tree_dirty_at_generation
```
→ **0 substantive differences** required; `eval/outputs/d6.json` SHA unchanged.
Verify schema, provenance, negative controls, per-tier metrics incl. `tier_e`, prevalence
transform, calibration/ECE, cost model, cost-optimal thresholds, tier ladder, ROC/PR,
false-positive and false-negative behaviour. **Every metric reported with its measurement
conditions** — that rule is load-bearing in the Evaluation Protocol.

### Phase 6 — Security QA  *(~1.5 h, S-5 armed)*

Attack the **running** application, per `01-THREAT-MODEL-v2.md`.

Attacker-controlled inputs: IP, `event_id`, timestamps, user-agent, arbitrary client
fields, malformed and oversized payloads, hostile strings (prompt-injection shaped,
control characters, RTL, 10 KB unicode), entity identifiers, repeated IDs,
same-`event_id`-different-payload, forged/stale/replayed outcomes, and missing / invalid /
absent API keys.

Must verify:
- Client-asserted fields **cannot become features** (`test_trust_boundary.py` + live probe).
- Merchant identity derives **only** from the authenticated key.
- Server-minted `attempt_uid` used everywhere; `ip` server-observed (`net.py`); the new
  `TOLLGATE_TRUSTED_EDGE_HOSTS` does **not** widen the trust boundary by default.
- No raw PAN/CVV anywhere; card hashes never leak to SSE, D1, D3, or logs.
- Narrator cannot influence enforcement; hostile text cannot reach the prompt
  (`build_bundle()` single admission point, `CHARSET_RE` gate).
- Operator-only actions authenticated; `/v1/replay/{start,stop,reset}` all key-gated
  (AUDIT-021); `/status` deliberately open (Decision 107).
- Enforcement entity-scoped; automatic ceiling **is** `challenge`; `block`/`step_up`
  require confirmation.
- `/v1/outcome` HMAC + 5-min staleness + single-use nonce → 401/404/409/503 as specified.
- Phase-3 demo controls inert without `TOLLGATE_DEMO_CONTROLS=1`.

### Phase 7 — Reliability, state machine, failure injection  *(~1.5 h)*

Inject each fault and answer six questions: *does it fail · does it fail safely · does the
UI tell the truth · can the operator recover · is state/data preserved · can the demo continue?*

Redis unavailable at startup · Redis killed mid-run · Redis restarted · scorer restarted ·
scorer killed mid-replay · scorer killed after an accepted attempt · dashboard refresh
(idle / mid-replay / post-completion) · storefront refresh · SSE disconnect and reconnect ·
SSE → 5 s polling → SSE recovery · API timeout · Gemini unavailable · Gemini malformed
JSON / 429 / charset violation · reset during replay · stop during replay · duplicate
event · malformed request · invalid API key · SQLite locked · spool present at startup ·
stale spool segment · partial service startup · browser opened before backend ready.

### Phase 8 — Replay lifecycle  *(~1.5 h — highest-priority area)*

The full 16-step sequence, per tier and per speed:

start → running → progress → threat transition → incident → stop → reset → start again →
complete → reset → different tier → same tier again → refresh **during** → refresh
**after** → open dashboard **mid-replay** → open dashboard **post-replay**.

Matrix: `{easy, medium, hard, evasive}` × `{speed 0, 1, 60}` × `{pace_from episode on/off}`,
seeded, and repeated with the same seed. Assert per run: exact event count (`easy` = 821),
terminal state reaches `finished` (**never `N−1/N`** — AUDIT-002), `reset` → 200 with the
`cleared` map, Redis key count back to its floor, `attempt_score` row count == events
scored, `run_id` changes on every launch, no run silently swallowed (AUDIT-005).

**The acceptance criterion: the complete demo is repeatable. A demo that works once but
not twice is NOT demo-ready.**

### Phase 9 — Historical finding re-verification  *(~2 h)*

All 24 `QA-AUDIT-2026-09-01.md` findings re-tested from zero (§6 matrix), plus a re-run of
the 40 D6 findings' regression guards (the three D6 test tiers, not a manual re-audit — R-4).

### Phase 10 — Performance QA  *(~1 h)*

`/v1/score` p50/p95/p99 — **target p99 < 100 ms** (TRD §1). Sustained scoring; burst
scoring; replay at 60× (measure the **actual** factor — the prior audit measured 58.5×);
Redis behaviour; SQLite WAL; spool growth; drainer liveness; memory and CPU over a 20-run
soak (`verify_60x --gate throughput`); concurrent browser + API activity. Verify the **LLM
is never on the scoring path** (Gemini dispatched out-of-band, Decision 98). Exercise each
availability rung: full → rules-only → fail-open.

### Phase 11 — UI/UX QA  *(~2 h)*

**Storefront** (must still look like a merchant, not a security console — `08-UIUX-SPEC-v2.md`):
S1 product · S2 checkout · normal checkout · latency readout · tier badge (incl. `shed`,
`fail_open`) · S3 challenge · S5 confirmed · S6 blocked · S7 throttle · demo control strip ·
reset · repeated checkout · malformed input · empty input · refresh · back/forward ·
reload mid-activity. **Re-test AUDIT-019 specifically** — fields now appear wired
(controlled state, browser-side SHA-256, real BIN slice); confirm a typed value actually
reaches the scorer and changes the decision.

**Dashboard** — D0: navigation, threat indicator, three monochrome system-state banners
(advisory / rules-only / fail-open), connection state, recovery. D1: threat band, event
stream, four tiles, attempt count, card-per-IP, empty state, live and replay update.
D3: narrative, timeline, contributions, entities, client-asserted evidence, proposed
action, confirm, resolve, audit trail, pseudonymisation, **no PAN or card-hash leakage**.
D6: every required metric, prevalence, honest model-vs-baseline (B0 must **not** be
silently omitted — it beats the model on AP at all four tiers and the summary must say so),
readable cost-curve geometry, visible optima, valid sensitivity ribbon, negative controls,
constants not presented as measurements, `resolvable: false` handled honestly, no
misleading `0.000`, no stale captions, no backend/frontend mismatch, responsive at
1536/1280/768/390, accessibility. **"The JSON is correct" is not sufficient** — the prior
audit's finding was precisely that a correct artifact was rendered through a misleading
selection.

### Phase 12 — Demo Rehearsal #1  *(~1 h)*  → §7

### Phase 13 — Triage and hardening  *(~2–3 h)*

Every defect gets an ID, severity, category, repro, expected, actual, root cause (or
"not established"), evidence, component, fix status, verification method, residual risk.
**"Fixed" means reproduced after the change and verified** — never "a patch was made."
Each fix is its own atomic commit. Fix P0 and P1 only; P2/P3 are documented unless the fix
is trivial and isolated.

### Phase 14 — Compose retest + Demo Rehearsal #2  *(~1.5 h)*

`docker compose down -v` → `docker compose up --build` → full clean-state bootstrap →
repeat the **identical** demo. Compare against Rehearsal #1 (§7). S-4 armed.

### Phase 15 — Final audit and demo script  *(~1.5 h)*

Write the artifacts in §11. Verdict last, after the evidence.

---

## 5. Test matrix

| Suite | Command | Baseline expectation | Gate |
|---|---|---|---|
| Backend full | `uv run pytest tests/ -q` | 619 passed, 2 xfailed | **blocking** |
| Safety | `pytest -q -m safety` | green | **blocking** |
| Slow | `pytest -q -m slow` | green | **blocking** |
| Redis | `pytest -q -m redis` | green (skips if down) | **blocking** with Redis up |
| Metamorphic | `pytest -q -m metamorphic` | green (M1–M8) | **blocking** |
| Characterization | `pytest -q -m characterization` | informational | never a gate |
| Reversed order | reversed-file-order invocation | green (AUDIT-010) | **blocking** |
| Frontend unit | `vitest run` | 205 passed / 21 files | **blocking** |
| Frontend coverage | `vitest run --coverage` | ≥ 85 / 85 / 80 | **blocking** |
| Browser E2E | `playwright test` | 68 (17 × 4 viewports) | **blocking** |
| 60× stability | `verify_60x --gate all` | 3 runs, no wedge | **blocking** |
| Native-fault path | `verify_60x --gate 60x --faulthandler` | no SIGSEGV | **blocking** |
| Throughput / repeatability | `verify_60x --gate throughput` | 20 runs, identical counts | **blocking** |
| Artifact reproduction | `scripts/diff_d6.py` | 0 substantive diffs | **blocking** |
| `handmade_40` × 2 | — | xfail (human oracle absent) | never a gate |

---

## 6. Historical defect matrix — all 24 re-verified

Each row is reported as: **Finding · Historical status · Current test · Result · Evidence ·
Remaining risk.** Planning-pass spot-checks are noted; none is treated as verification.

| ID | Sev | Historical finding | Day 9 test |
|---|---|---|---|
| 001 | CRIT | Reset → HTTP 500, `RedisWindowStore` has no `clear()` | Reset against the **Redis** backend; assert 200 + `cleared` map + Redis keys at floor. *(spot-check: `clear()` now at `redis_store.py:130`)* |
| 002 | CRIT | Finished run renders forever as `RUNNING (N−1/N)` | Run `easy` to completion in-browser; assert `finished 821/821` and controls re-enabled |
| 003 | CRIT | Stop returns the pre-stop snapshot | Stop mid-run; assert the returned snapshot is the TRUE terminal state, never a stale `running` |
| 004 | CRIT | Reset-while-running reports success, backend keeps scoring | Reset during an active run on both backends; assert transactional cancel→await→clear→`idle`, or a 409 with state untouched |
| 005 | CRIT | 24 h idempotency keys make a repeat run invisible | Launch `easy` twice in one process; assert the second emits 821 events under a new `run_id` with run-scoped keys |
| 006 | CRIT | Scorer wedges mid-60× run, 100 % CPU, `/healthz` times out | `verify_60x --gate all` + `--gate crossing` + a browser 60× run with a wall-clock `/v1/score` injected at ~50 % |
| 007 | HIGH | Replay task exceptions silently swallowed | Force a replay-task exception; assert state `failed` with `error` populated and surfaced in the UI |
| 008 | HIGH | Incidents screen unreachable while incidents open | Open incidents, navigate to D3; assert the list is populated *(spot-check: `hooks/useIncidents.js` now exists)* |
| 009 | HIGH | Refresh mid-attack shows an all-clear dashboard | Refresh mid-attack; assert back-fill via `/v1/stream/recent` reconstructs band, tiles and incidents |
| 010 | HIGH | `test_day2_e2e` fails in-suite, passes alone | Reversed-file-order run + both parametrised backends |
| 011 | HIGH | D6 renders unresolvable recall as `0.000` | D6 test tiers + visual pass; assert `resolvable:false` never reaches `.toFixed()` |
| 012 | HIGH | Two SIGSEGVs in the drainer thread | `--gate throughput` (20 runs) + `--faulthandler`; assert drainer alive and `connect()` ≤ 2 per run |
| 013 | MED | Tier selector desyncs after refresh | Refresh mid-run on `medium`; assert the selector reconciles from `replayStatus.tier` |
| 014 | MED | 60× pacing: 10 s of attack inside 179 s of runtime | Measure act durations with `pace_from: episode` on and off |
| 015 | MED | Reset never clears the frontend buffer | Reset; assert ticker, rail, tiles and band all reinitialise on `run_id` change |
| 016 | MED | Stream Rail capped at 800 px, never resizes | Render at 1536 and 390; assert the rail spans the canvas and survives a resize |
| 017 | MED | "Attempts · 5 min" capped by the 200-event buffer | Drive > 200 attempts inside 5 event-minutes; assert the tile exceeds 200 and is monotonic |
| 018 | MED | Threat-band wash is invalid CSS (`var(--tg-attack)1A`) | Computed-style assertion per state *(spot-check: now `THREAT_WASH_TOKENS`)* |
| 019 | MED | Storefront card fields decorative | Type a distinct PAN; assert the derived `card_hash` and BIN reach the scorer and move the decision *(spot-check: controlled inputs + browser SHA-256)* |
| 020 | MED | SSE reads `reconnecting` when healthy and idle | Open a fresh dashboard on an idle system; assert `connecting → live` |
| 021 | LOW | `/stop` and `/reset` unauthenticated | Call both with no key and a bad key; assert 401 *(spot-check: header + `Depends` present)* |
| 022 | LOW | Errors surface as `HTTP 500: NULL` | Trigger 401 / 409 / 503 / network failure; assert mapped operator copy, cleared after 8 s |
| 023 | LOW | Ticker score column permanently blank | Assert scored rows carry a value and unscored rows show `—` *(spot-check: FIX-020 comment present)* |
| 024 | COSM | Both apps titled "(Day 1)"; stale comments | *(spot-check: titles now "Live Monitor" / "Kesar & Co. — Checkout")* — sweep the remaining stale comments |

---

## 7. Demo rehearsal protocol

**Setup, identical for both rehearsals:** clean state via `docker compose down -v` →
`docker compose up --build`. Two browser windows side by side — **LEFT: storefront :5173 ·
RIGHT: dashboard :5174**. No developer console open. No terminal in frame except where the
script explicitly calls for one. Wall-clock start time recorded.

**Both rehearsals run the identical script.** Rehearsal #1 discovers defects; Rehearsal #2
proves the fixes and proves repeatability.

Record at every step: exact timestamp · action · where clicked · what appeared · latency ·
visible state changes · narrator output · incidents opened · errors · unexpected UI ·
freezes · confusing moments · **anything requiring developer knowledge to understand**.

**Rehearsal #1 simultaneously drafts the script** as this table — presenter narrative
derived from the working demo, never written independently of it:

| Step | Presenter action | Where to click | What appears | What to say | Why it matters | Expected timing |

**Timing to measure:** total duration · per-act duration · attack setup · time to detection
(`time_to_detect_s`, event time) · **incident banner → operator action (target < 60 s, App
Flow J3)** · metrics walkthrough · dead time · unnecessary waiting. Act One's budget is
~3 min (J6), Act Two ~2 min (J7). If pre-roll or post-roll dominates, identify a
demo-specific pacing control that preserves the exact event sequence and semantics —
**never falsify the attack, never alter detection semantics for presentation.**

**Presentation-quality assessment**, from the perspective of someone who has never seen the
code: would a judge understand what is happening · does the screen change when expected ·
is the visual hierarchy obvious · does anything look unfinished or like a placeholder · are
errors understandable · is the next click obvious · does the dashboard tell the same story
being told aloud · does the storefront look like a real merchant · does the dashboard look
like a professional risk instrument · are numbers and charts readable at demo resolution ·
is anything cut off · are animations too slow or too fast · is there dead time ·
**is any step nondeterministic?**

**Rehearsal comparison table:**

| Step | Rehearsal 1 | Fix / change | Rehearsal 2 | Stable? |

Same failure twice → confirmed defect, **NOT DEMO READY** (S-4). A new failure in #2 →
recorded, and the system is not demonstrably stable.

**Demo script acts** (written only after a successful rehearsal): Opening (the problem in
one or two sentences, why card testing matters, what is about to be shown) · Act 1 normal
checkout (what the storefront represents, what the dashboard represents, latency, why
protection is invisible to the customer) · Act 2 attack begins (what the simulator
represents, why virtual time, and the `×60 VIRTUAL CLOCK · WINDOWS PRESERVED · TTD IN EVENT
TIME` banner — **verified on screen during rehearsal, not quoted from the spec**) · Act 3
incident (threat state, evidence, narrative, contributions, entity scope, why the system
does not immediately block) · Act 4 operator action (proposed vs in-force, confirmation,
why `challenge` is the automatic ceiling, what changes after, how the attacker's attempts
are affected) · Act 5 resolution (cooling, closed incident, enforcement release, audit
trail) · Act 6 metrics (model, baseline, negative controls, prevalence, cost model, why the
numbers are trustworthy, **and the limitations**).

**Honesty requirements for Act 6.** B0 outperforms the learned model on AP at all four
tiers; the model is decisively better on `hard`, where B0 fires 0/3 rules. Tier E recall is
0.39 (model) / 0.28 (B0) — the worst number in the deck — and its target-FPR point is
`UNRESOLVABLE (too few negatives)`. Six features are excluded by the discriminability
audit, so the model runs on four live features. Say all of it. Do not hide bad results.

**Honesty requirement for Acts 2–3.** Outcome-derived decline features read `0.0` (R-5);
the decline-rate beat in J6 step 3 cannot be shown, and the script must not imply it.

---

## 8. Rules that constrain remediation

Binding for the whole day. Do not: hardcode UI values for the rehearsal · modify evaluation
artifacts to improve displayed metrics · weaken or delete failing tests · hide errors ·
suppress warnings without investigation · fabricate output · hand-edit replay state · touch
Redis during a final rehearsal except an explicit clean-state reset · skip Docker Compose
because dev servers work · claim a fix without reproducing it · mock real behaviour during
the final demo · silently change the specification.

Any demo-specific control **must be clearly distinguished from production behaviour**
(the `TOLLGATE_DEMO_CONTROLS` gate plus visible UI labelling). Deterministic replay and
virtual-clock semantics are preserved absolutely: same events, same order, same virtual
times, same decisions — only the sleep may change (Decision 106).

---

## 9. Evidence standard

Every claim carries evidence. Not *"replay works"* but:

> `easy`, seed 42, speed 60, `pace_from: episode` — completed 821/821; dashboard reached
> `finished`; reset returned 200 with `cleared: {windows: N, threat: 1, incidents: M,
> policy: 1}`; Redis key count returned to floor 3; a second identical replay produced 821
> events under a new `run_id`; verified in the browser and in `scorer.log`.

Not *"reset fixed"* but: reproduced the historical failure, applied the fix, ran reset
against the Redis backend, received 200, verified every layer cleared, relaunched the same
replay successfully.

Not *"demo works twice"* but: rehearsal 1 completed at `HH:MM:SS`; rehearsal 2 at
`HH:MM:SS`; both from clean state; both reached incident; both completed; both reset;
**no manual backend intervention required**.

---

## 10. Release-readiness gate

The verdict is exactly **DEMO READY** or **NOT DEMO READY**. Not "mostly ready." Not "ready
with minor issues."

**DEMO READY** ⟺ zero P0 · zero unresolved P1 · two successful complete rehearsals · clean
`docker compose up` from stopped · all blocking test gates green · no known data-integrity
failure · no known security-critical failure · no known repeatability failure.

---

## 11. Artifacts Day 9 produces

Repo root, matching the existing `<TOPIC>-<KIND>-<DATE>.md` convention:

1. `09-DAY-9-QA-AND-DEMO-PLAN.md` — this plan, written first
2. `QA-AUDIT-DAY-9-2026-09-03.md` — the final audit in the 23-section structure (executive
   summary → final verdict), every defect carrying ID · severity · category · repro ·
   expected · actual · root cause · evidence · component · fixed? · verification · residual risk
3. `DAY-9-TEST-RESULTS.md` — every suite, every count, every failure classified
4. `DAY-9-DEMO-REHEARSAL-1.md`
5. `DAY-9-DEMO-REHEARSAL-2.md`
6. `DAY-9-DEMO-SCRIPT.md` — the six acts, derived from the working demo
7. `DAY-9-DEFECT-LOG.md`
8. `evidence/day-9/` — scorer logs, `verify_60x` JSON reports, `diff_d6` output, replay
   status captures, screenshots, timing tables

Plus updates to `Decisions.md` (containerization; the trusted-edge env var; the demo-control
gate) and `README.md` / `Flow.md` (the Docker path, J6 6–8, Day 9 status) — **and no
duplicate competing source of truth.**

---

## 12. Time budget

| Phase | Est. |
|---|---|
| 0 Baseline + commit | 0.75 h |
| 1 Baseline test run | 1 h |
| 2 Containerization | 3 h |
| 3 J6 steps 6–8 | 3 h |
| 4 Backend/API QA | 1.5 h |
| 5 Detection + evaluation QA | 2 h |
| 6 Security QA | 1.5 h |
| 7 Reliability / failure injection | 1.5 h |
| 8 Replay lifecycle | 1.5 h |
| 9 Historical 24-finding re-verification | 2 h |
| 10 Performance QA | 1 h |
| 11 UI/UX QA | 2 h |
| 12 Rehearsal #1 | 1 h |
| 13 Triage + hardening | 2–3 h |
| 14 Compose retest + Rehearsal #2 | 1.5 h |
| 15 Audit + script | 1.5 h |
| **Total** | **~26–27 h** |

This is **not one working day.** Three sessions with hard checkpoints:

- **Session A — Phases 0–3** (~8 h). Checkpoint: baseline recorded, `docker compose up`
  works, J6 6–8 built and tested. Nothing is yet claimed about readiness.
- **Session B — Phases 4–11** (~13 h). Checkpoint: complete defect inventory, no fixes
  applied beyond P0 blockers that prevent further testing.
- **Session C — Phases 12–15** (~6 h). Checkpoint: the verdict.

If Day 9 must compress to one session, the irreducible core is **0, 1, 8, 9, 12, 14, 15**
(baseline · full test run · replay lifecycle · historical re-verification · two rehearsals ·
audit) — and the verdict must then state explicitly that Docker Compose, J6 6–8, security,
performance and failure injection were **not covered**, which on its own forces NOT DEMO
READY under the gate in §10.

---

## 13. Verification of this plan's own execution

Day 9 is complete when: all eight artifacts exist · every §5 gate has a recorded result ·
every §6 row has a result and evidence · both rehearsals have timestamped transcripts · the
§7 comparison table is filled · and `QA-AUDIT-DAY-9-2026-09-03.md` §23 states one of the two
permitted verdicts with the §10 checklist evaluated line by line.

**No verdict is written before the evidence it rests on.**
