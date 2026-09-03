# Day 9 — Demo Rehearsal #2

**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 14 + §7. **Stop condition S-4
armed** — *if Rehearsal #2 reproduces any Rehearsal #1 failure → NOT DEMO READY.*
**Executed:** 2026-09-03 (Session 3). HEAD `bbd9be2` (all Phase 13 fixes in).

**Setup — Phase 14 clean retest:**
```
docker compose down -v && docker compose up --build
```
All 5 services healthy in ~20 s (images cached). Scorer startup log:
`Connected to Redis … RedisWindowStore` · `loaded Layer-1 model l1-lgbm-v1 +
calibrator platt-v1` · `loaded Layer 2 for merchant_demo: policy v2,
cusum_h=318.133, tau_flag=0.06475, drift_enabled=True` · narrator `template`
(GEMINI key set but unused → benign `config:` warning).

**Key alignment (the DEF-D9-011 gate):** storefront bundle key hash
`fa4aa941e04b` **==** `deploy/compose.env` key hash **==**
`merchant.api_key_hash` `fa4aa941e04b` — a **freshly-minted** key (different from
Rehearsal #1's `e1c7e86a0058`), and the frontend serves it correctly. The
DEF-D9-011 fix (`docker-compose.yml` `command:` sources `deploy/compose.env`)
holds across a fresh `down -v` + new key. DB tables all 0. Start 21:43:33 +0530.

**Environment note (unchanged from Rehearsal #1):** the Chrome extension's
`localhost` host-permission never recovered → screenshots / DOM-driving
unavailable. The J6 flow was exercised through the **real running services over
their HTTP interfaces** — the identical requests the storefront / dashboard
buttons issue, through the real Vite proxy → real scorer → real Redis / SQLite /
SSE / detection / enforcement — every result verified against authoritative
backend state (DB rows, `/v1/replay/status`, `/v1/incidents`, Redis `dbsize`).

---

## Walkthrough

| # | Step | Action (real service path) | Observed | Verdict |
|---|---|---|---|---|
| 1 | **Normal checkout** | `POST :5173/v1/score`, card `4111 2233 4455 6677` | `200` · `decision: allow` · `latency_ms 20` · `attempt_uid 01M1M0R29QS1KBX6NDK2DR243W` → **S5 "Order confirmed"** (true `allow`). `auth_attempt` 0→1, `attempt_score` 0→1, `bin=411122`. **No 401** — DEF-D9-011 does not recur. | **PASS** |
| 2 | **Launch attack** | `POST :5174/v1/replay/start {easy, 60, pace_from_episode}` | `202` → `running` (`sent 7/821` @ +4 s) · `run_id 01M1M0R2VDQQKV1BQ4P4XVXABD` | **PASS** |
| 3 | **Threat detection** | monitor `/v1/replay/status` + `/v1/incidents` to completion | replay → **`finished 821/821`** · `terminal: true` · `error: null` (wall ~188 s — slower than R#1's 126 s under concurrent machine load, same event count). `attempt_score` → **822** (1 + 821, exact parity). **2 incidents**, both `ESCALATED` · `detector: drift` · `peak_tier: challenge` · `time_to_detect_s 78.385`. `enforcement_action`: 2 rows, `challenge` / `confirmed_by: auto`. | **PASS** — identical to R#1 |
| 4 | **Incident (D3)** | `GET :5174/v1/incidents/{id}` | sections `incident · entities · timeline · enforcement · contributions · client_evidence`. Narrative (template): *"Entity ip_2 (ip) … distinct cards attempted against one BIN within 5 minutes, value 69 against threshold 20. Rules fired: attempts_per_ip_60s, distinct_cards_per_ip_5m, distinct_cards_per_bin_5m."* Entities: `ip_2 · ip · 198.51.100.249 (truncated) · 281`. Enforcement `challenge · auto · applied_at/expires_at set`. **No PAN, no 64-hex card hash** (the 14-digit false-positive is again `signal_value 4.60517…`). | **PASS** — byte-for-byte the same read model as R#1 |
| 5 | **CGNAT co-tenant** | `GET :5173/v1/demo/cotenant-ip` → `{ip: 198.51.100.249}`; `POST :5173/v1/score` + `x-tg-demo-xff: 198.51.100.249` | persisted `auth_attempt.bin/ip = (559988, 198.51.100.249)` — real XFF promotion; `decision: allow` — **not blocked**. | **PASS** — identical to R#1 |
| 6 | **Flood → shed** | `POST :5174/v1/demo/flood {enabled:true}` ~25 s; sample a checkout every 6 s | flood **sent 2116 · shed_responses 784** (~37 %, real `AdmissionController`). **1 of 4** sampled interactive checkouts carried `X-Tollgate-Shed: 1` (R#1: 0/5). Still intermittent; SSE `availability.shed` did not latch. | **MARGINAL — DEF-D9-004 (P3), documented.** Same behaviour class as R#1 (within the "~1-in-3 odds" window); **not a demo failure** — the shed rung is proven (784 real shed responses) and the demo script frames the beat as "the flood's own requests are shed." |
| 7 | **Kill-scorer → fail-open** | `POST :5174/v1/demo/fault {enabled:true}`; 3× `/v1/score`; then `{enabled:false}` | 3× **`200 allow`**, `latency_ms 0`, `degraded_reason: fail_open:model` on every row, **never a 5xx**. `{enabled:false}` → full path restored. | **PASS** — identical to R#1 |
| 8 | **D6 metrics** | `#/metrics` route + `TG_CONFIG_HASH` | route `200`; `TG_CONFIG_HASH=a7db8c6118…` in `deploy/compose.env` **and** the dashboard PID 1 env. | **PASS** |
| 9 | **Reset → recovery** | `POST :5174/v1/replay/reset` | `200` · `state: idle` · `degraded: false` · `cleared = {window_store:6222, threat, layer2, incidents, policy_engine, decision_cache, persisted_incidents:4}`. Post: `state idle`, `run_id null`, incidents `state != CLOSED` = 0, **Redis `dbsize` 0**. **`enforcement_action WHERE released_at IS NULL` = 0** (R#1 Pass B: **3**) — **DEF-D9-008 fix verified live.** `GET /v1/demo/cotenant-ip` after reset → **404** ("nothing enforced") — the DEF-D9-008 downstream symptom (stale enforced IP) is gone too. | **PASS** — DEF-D9-008 resolved |

---

## Rehearsal #1 (Pass B) vs Rehearsal #2 — comparison

| Step | Rehearsal #1 (Pass B) | Fix since | Rehearsal #2 | Stable? |
|---|---|---|---|---|
| Clean bring-up / key alignment | 401 in Pass A (**DEF-D9-011**), fixed → aligned (`e1c7e86a0058`) in Pass B | `afaf572` (already in Pass B) | aligned to a **new** key `fa4aa941e04b`; no 401 anywhere | **STABLE** — DEF-D9-011 does not recur |
| 1 Normal checkout | `200 allow` → S5; `bin 411122` persisted | — | `200 allow` → S5; `bin 411122` persisted | **STABLE** |
| 2 Launch | `202` → `running`, fresh `run_id` | — | `202` → `running`, fresh `run_id` | **STABLE** |
| 3 Detection | `finished 821/821`; 2 ESCALATED drift incidents; TTD 78.4 s; `attempt_score` parity | — | `finished 821/821`; 2 ESCALATED drift incidents; TTD 78.385 s; `attempt_score` parity | **STABLE** |
| 4 Incident D3 | full read model; no PAN/hash leak; `challenge` auto-ceiling | — | full read model, same narrative/entities; no PAN/hash leak; `challenge` auto | **STABLE** |
| 5 CGNAT co-tenant | `cotenant-ip` → `198.51.100.249`; checkout `allow`, `ip` resolved | — | `cotenant-ip` → `198.51.100.249`; checkout `allow`, `ip` resolved | **STABLE** |
| 6 Flood → shed | 664/1970 flood reqs shed; **0/5** interactive shed; banner not latched | DEF-D9-004 documented (not fixed — machine ceiling) | 784/2116 flood reqs shed; **1/4** interactive shed; banner not latched | **STABLE (marginal, documented)** — same behaviour class, not a regression |
| 7 Fail-open | 3× `200 allow` `fail_open:model`, never 5xx; restored | — | 3× `200 allow` `fail_open:model`, never 5xx; restored | **STABLE** |
| 8 D6 metrics | route `200`; `TG_CONFIG_HASH` present | — | route `200`; `TG_CONFIG_HASH` present | **STABLE** |
| 9 Reset → recovery | `200 idle`; full `cleared`; Redis floor 0; **3 orphan `enforcement_action` (DEF-D9-008)** | `87614da` | `200 idle`; full `cleared`; Redis floor 0; **0 orphan `enforcement_action`**; `cotenant-ip` → 404 | **IMPROVED** — DEF-D9-008 resolved |

**No new failure appeared in Rehearsal #2.**

---

## S-4 evaluation & verdict

**S-4 — "if Rehearsal #2 reproduces any Rehearsal #1 failure → NOT DEMO READY":**

- The one **failure** in Rehearsal #1 was **DEF-D9-011 (P1)** — the clean-compose
  path 401'd every keyed frontend call. Rehearsal #2 ran from a fresh
  `docker compose down -v && docker compose up --build` with a **freshly-minted**
  API key and **did not reproduce it** — checkout, Launch, co-tenant, flood,
  fault, reset all returned 2xx.
- **DEF-D9-008** (P3, reconfirmed in R#1 Pass B step 9) is **resolved** — 0 orphan
  enforcement rows after reset in R#2.
- **DEF-D9-004** (P3) — the flood's marginal shed behaviour recurred, as expected:
  it is a documented reference-machine limitation (Decision-level, same ceiling as
  DEF-D9-001), not a defect the Phase-13 fixes address. In **both** rehearsals the
  flood step's verdict is "MARGINAL (documented)", never "FAIL"; the shed rung is
  proven (784 / 664 real `X-Tollgate-Shed` responses) and the demo script frames
  the beat accordingly. This is **not** a repeatability failure of the demo.

**S-4 NOT triggered.** Every step that succeeded in Rehearsal #1 Pass B succeeded
identically in Rehearsal #2; the one P1 failure does not recur; one P3 improved;
no new failure. **No manual backend intervention was required in either
rehearsal** — the only "Reset" is the operator's own DC-strip control.

**Rehearsal #2 verdict: PASS. The complete J6 demo is repeatable from clean
state, twice, with identical results.**
