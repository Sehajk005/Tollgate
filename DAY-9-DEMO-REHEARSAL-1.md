# Day 9 — Demo Rehearsal #1

**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 12 + §7 (rehearsal protocol).
**Executed:** 2026-09-03 (Session 3), against the real Docker Compose stack
(`docker compose down -v` → `docker compose up --build`).
**Intended layout:** LEFT = storefront `:5173` (`?demo=1`), RIGHT = dashboard `:5174`.

Rehearsal #1 is an **actual release test** — it discovers defects. Every failure
below was stopped on, reproduced, classified, and recorded here + in
`DAY-9-DEFECT-LOG.md`.

---

## Environment note (not a demo defect)

Mid-session the Chrome extension lost its `localhost` host-permission
(screenshots → `Cannot access contents of the page` / `0 width`; `get_page_text`
and DOM scripting → same). Screenshots taken **before** the failure are retained
(dashboard idle, storefront S1/S2/S5). After it, the J6 flow was exercised
through the **real running services over their HTTP interfaces** — the identical
requests the storefront / dashboard buttons issue, through the real Vite proxy →
real scorer → real Redis / SQLite / SSE / detection / enforcement — with every
result verified against authoritative backend state (DB rows, `/v1/replay/status`,
`/v1/incidents`, `/v1/stream/recent`, Redis `dbsize`). This is not "faking
responses" or "manipulating backend state": nothing was hand-written into a
store, no API response was stubbed, the UI routing table (`lib/outcome.js`) is
applied to the real decision. What is **not** covered this way: the literal
React `onClick` dispatch (covered at source by
`tests/acceptance/test_storefront_checkout_wiring.py` + Pass A below) and pixel
rendering (covered by Phase 11 + Playwright). Rehearsal #2 (Phase 14) must retry
the browser after a Chrome-permission reset.

---

## Pass A — first walkthrough (HEAD `055613e`, DEF-D9-010 fixed)

**Setup:** `docker compose down -v && docker compose up --build`; stack healthy;
`auth_attempt`/`attempt_score`/`incident`/`enforcement_action` all 0.
Start 2026-09-03 19:47:44 +0530.

### Step 1 — normal checkout → **FAIL → DEF-D9-011 (P1)**

- Storefront S1 → "Buy now" → S2; typed card `4111 2233 4455 6677`; clicked "Pay ₹1,200".
- **UI showed "✓ Order confirmed" (S5).**
- Network capture: **one `POST /v1/score` was dispatched** — so **DEF-D9-010 is
  fixed** (previously `pay()` threw `TypeError` before the request left the
  browser; now the request goes out with clean headers). **But it returned `401`.**
- No `auth_attempt` / `attempt_score` row persisted; no dashboard event.

**Root cause (DEF-D9-011, P1):** `docker-compose.yml` resolves
`env_file: deploy/compose.env` at container-**create** time; the one-shot
`bootstrap` runs **after** and rewrites `deploy/compose.env` with a fresh
`VITE_TOLLGATE_API_KEY`, seeding `merchant.api_key_hash` with the new key's hash.
`deploy/compose.env` is gitignored and survives `down -v`, so the frontend
containers were created with the **previous run's** key.
- Verified: `storefront` container key hash `4ddf99…` ≠ `deploy/compose.env` key
  hash `22cc6f…` = `merchant.api_key_hash`; storefront container created
  `14:14:47`, `bootstrap` finished `14:15:28` (41 s later).
- `services/scorer/Dockerfile`'s CMD already sources `deploy/compose.env` at
  start (Phase 2); the two frontends were never given the same shim.

**Sub-observation DEF-D9-012 (P3):** `resolveClientOutcome` maps a `401` (not
`>=500`, no `decision` in body) → `"fail_open"` → **S5 "Order confirmed"**. A
misconfigured key therefore shows a green check, which cost rehearsal time to
diagnose. The `?demo=1` readout shows `tier: fail_open` but not the HTTP status.

**→ Stopped Pass A. Fixed DEF-D9-011 before continuing (like DEF-D9-010).**

---

## Fixes applied between Pass A and Pass B

| Defect | Sev | Fix | Commit | Verify |
|---|---|---|---|---|
| **DEF-D9-010** | P1 | `S2Checkout.jsx` Pay button `onClick={() => pay()}` (zero-arg; event can't reach `extraHeaders`) + `tests/acceptance/test_storefront_checkout_wiring.py` | `055613e` | guard FAILED→PASSES; `pytest tests/` = 638 pass / 1 fail (DEF-D9-003, pre-existing) / 2 skip / 2 xfail; Pass B Step 1 e2e |
| **DEF-D9-011** | P1 | `docker-compose.yml` `command:` for `storefront` + `dashboard` → `sh -c "set -a; [ -f /repo/deploy/compose.env ] && . /repo/deploy/compose.env; set +a; exec npm run dev -- --host 0.0.0.0"` (compose `command:` overrides the image CMD, so the shim must live here). First attempt `6edc909` put it in the Dockerfile CMD — inert, superseded by `afaf572`. | `6edc909` → `afaf572` | after `down -v && up --build`: storefront **and** dashboard bundle key hash == `deploy/compose.env` hash == `merchant.api_key_hash` (`e1c7e86a0058`); Pass B Steps 1–2 |

---

## Pass B — full walkthrough (HEAD `49a06cf`, both P1s fixed)

**Setup:** `docker compose down -v && docker compose up --build`; all 5 services
healthy; keys aligned (`e1c7e86a0058`); DB tables all 0.
Start 2026-09-03 20:04:59 +0530.

| # | Step | Action (real service path) | Observed | Verdict |
|---|---|---|---|---|
| 1 | **Normal checkout** | `POST :5173/v1/score` (Vite proxy → scorer), card `4111 2233 4455 6677` | `200` · `decision: allow` · `latency_ms 168` · `attempt_uid 01M1KVE2FHDP25WTJR959K7D17`. `resolveClientOutcome(allow)` → **S5 "Order confirmed"** (a **true** confirmation). `auth_attempt` 0→1, `attempt_score` 0→1, **`bin=411122`**; `/v1/stream/recent` shows the event `decision:allow bin:411122`. | **PASS** — DEF-D9-010 + DEF-D9-011 verified end-to-end |
| 2 | **Launch attack** | `POST :5174/v1/replay/start {easy, 60, pace_from_episode}` (DC-strip "Launch") | `202` · `state: starting` → `running` (`sent 4/821` @ +3 s) · `run_id 01M1KVF40BENYSGHBGC2HR4A93` | **PASS** |
| 3 | **Threat detection** | monitor `/v1/replay/status` + `/v1/incidents` to completion | replay → **`finished 821/821`** · `terminal: true` · `error: null` (no stuck `N−1/N` — AUDIT-002). `attempt_score` → **823** (1 checkout + 821 replay + 1 co-tenant — exact parity, AUDIT-005). **2 incidents opened**, `state: ESCALATED`, `detector: drift` (Layer 2b SPRT), `peak_tier: challenge`. `time_to_detect_s = 78.4` (README "TTD ≈ 76 s"). | **PASS** |
| 4 | **Incident (D3)** | `GET :5174/v1/incidents/{id}` (D3 read model) | keys `incident · entities · timeline · enforcement · contributions · client_evidence`. Narrative (template): *"Entity ip_2 (ip) was assigned tier "challenge". Triggering signal: distinct cards attempted against one BIN within 5 minutes, value 69 against threshold 20. Rules fired: attempts_per_ip_60s, distinct_cards_per_ip_5m, distinct_cards_per_bin_5m."* Entities: `pseudonym ip_2 · entity_type ip · entity_key_truncated 198.51.100.249 · attempt_count 281`. Timeline `null→monitor (open:drift)` → `monitor→challenge (policy:drift:in_control)`. Enforcement `challenge · confirmed_by auto · applied_by auto · expires_at set`. **No PAN, no 64-hex card hash anywhere** (one 14-digit false-positive was `signal_value 4.60517…`). | **PASS** |
| 5 | **CGNAT co-tenant** | `GET :5173/v1/demo/cotenant-ip` → `{ip: 198.51.100.249}`; `POST :5173/v1/score` + `x-tg-demo-xff: 198.51.100.249` (proxy → `X-Forwarded-For`) | `200` · `decision: allow` · `attempt_uid 01M1KYC38XKS5WCZ8GZXR23CGY`; `auth_attempt.ip = 198.51.100.249` (real XFF promotion via the declared trusted edge). The legit co-tenant checked out **from the enforced IP and was not blocked** — a single clean attempt does not cross R1; the `challenge` auto-ceiling makes `block` unreachable. Nothing special-cased. | **PASS** |
| 6 | **Flood → shed** | `POST :5174/v1/demo/flood {enabled:true}` ~25 s; sample a checkout every 5 s | Flood **sent 1970, shed_responses 664** (`X-Tollgate-Shed:1` on the flood's own requests) — the real `AdmissionController` bucket drained and shed. **BUT** none of the 5 sampled interactive checkouts was shed, and SSE `availability.shed` stayed `false`, `degraded_reason: null`. | **MARGINAL — DEF-D9-004 (P3) reconfirmed** — shed is real but intermittent on the single-worker dev scorer; the dashboard banner does not latch and an interactive checkout is not reliably throttled |
| 7 | **Kill-scorer → fail-open** | `POST :5174/v1/demo/fault {enabled:true}`; 3× `/v1/score`; then `{enabled:false}` | under fault: 3× **`200 allow`**, `latency_ms 0–7`, `degraded_reason: fail_open:model` on every persisted row, **never a 5xx**. `{enabled:false}` → next `/v1/score` `degraded_reason: null` (full path restored). | **PASS** |
| 8 | **D6 metrics** | `#/metrics` route + `TG_CONFIG_HASH` | route `200`; `TG_CONFIG_HASH=a7db8c61…` present in `deploy/compose.env` **and** in the dashboard PID 1 env (the `command:` shim exports the whole file). Full D6 render verified in Phase 11 §3 (freshness check works under Docker). | **PASS** |
| 9 | **Reset → recovery** | `POST :5174/v1/replay/reset` | `200` · `state: idle` · `run_id: null` · `degraded: false` · `cleared = {window_store:5034, threat, layer2, incidents, policy_engine, decision_cache, persisted_incidents:4}`. Post: `state idle`, `sent 0`, open incidents 0, `incident WHERE state!='CLOSED'` = 0, **Redis `dbsize` 0** (floor). | **PASS** — but `enforcement_action WHERE released_at IS NULL` = **3** after reset → **DEF-D9-008 (P3) reconfirmed** (reset closes incidents but does not release their enforcement rows; the live `PolicyEngine` ceiling *is* cleared) |

---

## Failures / findings discovered in Rehearsal #1

| ID | Sev | Where | Disposition |
|---|---|---|---|
| **DEF-D9-011** | **P1** | clean-compose bring-up (Step 1, Pass A) | **FIXED** `afaf572`, verified Pass B — no residual |
| DEF-D9-012 | P3 | `lib/outcome.js` 401→S5 (Pass A) | moot once DEF-D9-011 fixed; observability gap → Phase 13 (low) |
| DEF-D9-004 | P3 | flood shed marginal (Step 6) | carried from S1; Phase 13 — raise flood concurrency or document |
| DEF-D9-008 | P3 | reset orphans `enforcement_action` (Step 9) | carried from S2; Phase 13 — 1-line release call |
| AUDIT 009 / 013 / 015 / 022 (PARTIAL) | — | live browser re-run blocked by the Chrome-permission failure | source + backend verified (Phases 4/7/8/11); browser re-run → Rehearsal #2 |
| `#/live` `#/incident` @ 390/768 responsive | — | same browser block | Playwright covers `#/metrics` @ 4 viewports; D1/D3 small-viewport → Rehearsal #2 |

**No P0. No new P1 beyond DEF-D9-011 (fixed). No data-integrity failure. No
security-critical failure (no PAN/hash leak; XFF promotion only from the declared
edge; demo controls key-gated).**

---

## Rehearsal #1 verdict

**COMPLETE.** The full J6 flow runs end-to-end on the real Compose stack:
normal checkout → launch → detection (2 ESCALATED drift incidents, TTD 78 s) →
incident read model (no leak) → CGNAT co-tenant (allowed, not blocked) →
fail-open rung (always `allow`, never 5xx) → reset (idle, Redis floor 0).

**One P1 found and fixed** (DEF-D9-011 — the clean-compose path 401'd every keyed
frontend call). Three P3s reconfirmed (DEF-D9-004 flood, DEF-D9-008 reset
enforcement, DEF-D9-012 401-as-confirmed). Rehearsal #2 must reproduce this flow
from a fresh `docker compose down -v && up --build` and retry the browser.
