# Day 9 — Phase 11: UI / UX QA

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 11. Live browser QA against the
Compose stack (storefront :5173 light `.st-app`, dashboard :5174 dark `.tg-app`).
A `medium` / speed-60 replay was run to populate D1/D3 with live incidents.

---

## 1. Dashboard — D0 shell + D1 Live

Screenshot: `#/live` during a live `medium` replay.

| Element | Result |
|---|---|
| Title | `Tollgate — Live Monitor`; `document.title` follows the route (`Tollgate — Incident`, `Tollgate — Metrics & Evaluation`) — **AUDIT-024 PASS** |
| Nav | `TOLLGATE · Live · Incidents · Metrics`, `aria-current="page"` on the active item |
| **Stream Rail** | spans the **full canvas width** (1536 px) — **AUDIT-016 PASS** (no 800 px cap; `ResizeObserver` + width-derived pitch) |
| **Threat band** | `⟠ ELEVATED` — half-filled ring glyph **+** text label (state carried by glyph + text, not colour alone); dark amber wash from a defined token — **AUDIT-018 PASS** (no `var(--tg-attack)1A` string-concat) |
| **System-state banner** | `⌁ Enforcement paused — blast-radius cap reached (13 / 10). Scoring continues…` — **monochrome** (grey `⌁`, no state colour), stacks below the threat band. Advisory-mode banner rendering correctly. |
| **Connection chip** | `SSE: live` on a healthy connected system — **AUDIT-020 PASS** (not `reconnecting`) |
| 4 tiles | `ATTEMPTS · 5 MIN` (server field `attempts_per_merchant_5m`), `DECLINE RATE —` ("outcome-keyed windows not fed" — honest), `CARDS PER IP · TOP` (43), `ENFORCEMENT 13 / 10` ("blast-radius cap reached") |
| **Event ticker** | rows: `HH:MM:SS.mmm │ pseudonym · truncated-IP │ BIN │ DECISION` — the **decision label** fills the score column for scored rows (`ALLOW`/`MONITOR`/`CHALLENGE`); unscored would show `—` — **AUDIT-023 PASS** |
| PAN / card-hash | **none visible anywhere** on D0/D1 |
| Finished-run state | after the replay, DC strip → `REPLAY: FINISHED (701/701)`, threat band → `CALM`, Launch re-enabled, Stop disabled — **AUDIT-002 PASS** (no stuck `RUNNING (N−1/N)`) |
| DC strip | `TIER · SPEED · ☑ PACE FROM EPISODE · Launch · Stop · Reset`, `REPLAY: …`, the `×60 VIRTUAL CLOCK · WINDOWS PRESERVED · TTD IN EVENT TIME` banner **verified on screen**, `DEMO` group (`Flood`, `Kill scorer`) visibly labelled |

## 2. Dashboard — D3 Incident Detail

Reached via the **Incidents** nav while incidents were open — **AUDIT-008 PASS**
(D3 gets `incidentId` from `GET /v1/incidents`, not the SSE buffer). Full read
model rendered (`get_page_text`):

| Section | Content |
|---|---|
| Header | `Incident I42961E9E6 · OPEN · proposed monitor · in force allow · policy v2` |
| 1 Narrative | "GENERATED SUMMARY · EVIDENCE BELOW IS AUTHORITATIVE" — "Entity **ip_13** (ip) was assigned tier "monitor". Triggering signal: distinct cards attempted from one IP within 5 minutes, value 1 against threshold 15. Rules fired: none." — **pseudonym only, closed vocabulary, no raw id / card hash** |
| 2 Action bar | `ALLOW in force` · `This was legitimate` |
| 3 Evidence | Detection timeline (`14:41:58 MONITOR — CUSUM alert (0.00)`); Top contributions (3 bars w/ feature label + weight); **Entities table** — `ip_13 \| ip \| 203.0.113.224 \| 1 \| 13:44:08 \| 14:41:58` (pseudonym + **truncated real key**, never a PAN/card-hash) |
| 4 Audit trail | `14:41:58.551 — → monitor · open:cusum · policy v2` |
| 5 Client-asserted | `▸ CLIENT-ASSERTED · UNVERIFIED · NOT USED IN SCORING` (collapsed) |

**No PAN, no card-hash in the D3 DOM** (confirmed via full page text).

## 3. Dashboard — D6 Metrics

Renders from the committed `eval/outputs/d6.json` (build-time import, zero live
calls). Header: `seed 42 · config a7db8c61189a · model l1-lgbm-v1 · policy 1 ·
π_eval 0.01` + "**configs unchanged since**" (the `TG_CONFIG_HASH` freshness
check works under Docker — the R-1/Phase-2 "freshness not verifiable" risk is
resolved). Full page text reviewed.

| Plan requirement | Result |
|---|---|
| Every required metric | ✅ per-tier (1A/1B/1C), negative controls (2), discriminability audit (3), cost curves (4 A/B/C), calibration (5), baselines (6 B0/B1/B2/B3), Tier E |
| **B0 not silently omitted** | ✅ B0 in every block; summary states "B0 **outperforms** the learned model on raw AP at every tier (easy: 1.000 vs 0.789)"; §1 "weaker than B0 overall (ROC-AUC 0.889 vs 0.994)… stronger on hard, where B0's rules do not fire" — **AUDIT-011 / plan honesty PASS** |
| **`resolvable: false` handled honestly** | ✅ "**not resolvable · n_neg=221**" everywhere; `always_positive` → "unreachable … not a measured 0" — **never a fake `0.000`** — **AUDIT-011 PASS** |
| No misleading `0.000` | ✅ the only `0.000` values are real measured TPRs in "PER TIER — TPR AT EACH SERIES' OPERATING POINT" (`easy model 0.000`, `hard B1/B2 0.000`) with context ("B1 needs completed outcomes the pre-auth path never has") |
| Readable cost-curve geometry, visible optima | ✅ panels A (decision region, log scale), B (context), C (π₁ own scale); "cost-optimal = F1-optimal FPR 0.0000 · TPR 0.469 ₹276", "π₁ cost-optimal FPR 0.8734 · TPR 0.999 ₹16,405", exact operating-points table |
| Rupee gap | ✅ "F1-vs-cost gap at π₀ = 0.001 is **₹0 — structural, not empirical**" + the F1-collapse explanation (Decision 100); "Regime-switch saving: **₹2,32,145 per 10,000 attempts**" |
| Calibration / prior correction | ✅ Brier + ECE {raw · Platt · Platt+prior} at π₀/π₁; "Prior correction … reduces ECE at π₁ from **0.3955 to 0.2807**. That is the pass condition." reliability bins with "5 empty bins omitted" |
| Negative controls | ✅ 7 scenarios × 6 scorers, each with n, 95 % CI, "underpowered — n=5" / "single sample — n=1" flags; `nri_traffic` shown |
| Constants not presented as measurements | ✅ "figures to 3–4 dp imply a precision one seed cannot support"; "14 slots are un-fed" |
| Sensitivity ribbon | ✅ shaded ribbon on panel A |
| Every metric with its measurement conditions | ✅ every recall figure carries CI + n_neg + "UNRESOLVABLE (too few negatives)" |

**"The JSON is correct" is not sufficient — the rendering is also correct and
honest.** AUDIT-011 → **PASS**.

## 4. Storefront

| Screen | Result |
|---|---|
| **S1 Product** | "KESAR & CO. · Saffron Kurta · Hand-block printed cotton… no design ambition · ₹1,200 incl. taxes · Buy now" — light, minimal, **looks like a real merchant**, not a security console. Title `Kesar & Co. — Checkout` (AUDIT-024) |
| **S2 Checkout** | card form (`Card number`, `Expiry`, `CVV`, "Pay ₹1,200"), default `9990 0100 0000 0000` |
| S3 / S5 / S6 / S7 | exist (`outcome.js` routing table = direct port of the Python `UI_ROUTING_TABLE`; `allow/monitor/shed/fail_open → S5`, `challenge → S3`, `block → S6`, `throttle → S7`) |

### CRITICAL — AUDIT-019 recheck

**AUDIT-019 (card fields decorative) → PASS.** A live browser interception of
`pay()`'s outgoing `/v1/score` request, after typing `5544 3322 1100 9988` into
the card field, captured:

```json
{ "event_id": "evt-…", "card_hash": "a7586f841e83b7a9afdeffab863725a9aaa05c6696b15973a8c60919e2cbf92e",
  "bin": "554433", "last4": "9988", "exp_month": 4, "exp_year": 2028, "amount_minor": 120000, "currency": "INR" }
```

- `card_hash` = **exact SHA-256 of `5544332211009988`** (verified against a host
  `hashlib` computation) — derived in-browser via `crypto.subtle.digest` from the
  **typed** value.
- `bin` = **first 6 typed digits**; `last4` = **last 4** — not the old hardcoded
  `bin:"999001"` / random-hash decorative behaviour.
- The **PAN itself is never in the request body** — only the hash + BIN + last4.

The fields are controlled React state and their typed values reach the scorer
request. **AUDIT-019 requirement met.**

### NEW P1 — DEF-D9-010 — the storefront normal checkout is broken

While verifying AUDIT-019, every DOM-driven "Pay" click showed **"✓ Order
confirmed"** (S5) but persisted **no** `auth_attempt` / `attempt_score` row and
produced **no** `/v1/score` network request. A `fetch` wrapper capturing the
throw revealed:

```
POST /v1/score  hasKey=true  keyVal="S9DyTCV1…"(correct)
  -> TypeError: Failed to execute 'fetch' on 'Window': Invalid value
```

**Root cause:** `S2Checkout.jsx:222` wires the button as **`onClick={pay}`**, so
React passes the `SyntheticEvent` as `pay(extraHeaders = {})`'s `extraHeaders`
argument, which is then spread into the `fetch` `headers` object
(`{ "Content-Type": …, "X-Tollgate-Key": API_KEY, ...extraHeaders }`). The event's
enumerable props (`nativeEvent`, `target`, `getModifierState`, …) become header
values → `fetch` rejects with `Invalid value` → `pay()` catches it →
`resolveClientOutcome` sees `error != null` → returns `"fail_open"` → routes to
**S5 "Order confirmed"**.

- **Impact:** App Flow J6 step 1 (normal checkout) is broken — the customer sees
  a false confirmation, nothing is scored, the dashboard never sees the attempt.
  The scorer / proxy / API key all work (a direct browser-context `fetch` with
  the correct key → **200 + persisted** — verified, `bin=778866` reached the DB
  and the SSE ticker).
- **`payAsCotenant`** (`S2Checkout.jsx:255`, `onClick={payAsCotenant}` →
  `pay({ "x-tg-demo-xff": ip })`) is **unaffected** — it passes a real object.
- **Introduced:** Phase 3 (Session 1), when `pay()` gained the `extraHeaders`
  parameter. Before that `pay()` took no args and `onClick={pay}` was harmless.
- **Missed by tests:** `test_storefront_routing.py` tests `resolveClientOutcome`
  in isolation; the only Playwright spec is `metrics.spec.js` — **no e2e test
  clicks the storefront "Pay" button.**
- **Fix (Phase 13, 1 line):** `onClick={() => pay()}`. Add an e2e test that
  drives a real checkout and asserts a persisted `attempt_score` row.
- **Severity: P1** — blocks the DEMO READY verdict (plan: "Zero unresolved P1").
  Logged; **not fixed in Session 2** (plan §12 Session B: no fixes beyond P0
  test-blockers — this does not block further QA).

## 5. Responsive

| Viewport | Coverage |
|---|---|
| 1536 / 1280 / 768 / 390 — **`#/metrics`** | ✅ green Playwright suite (`metrics.spec.js`, 17 checks × 4 viewports = 68 tests — re-run in the final regression) |
| 1536 — `#/live` / `#/incident` | ✅ Stream Rail spans the canvas; tiles wrap; no horizontal body scroll |
| 390 / 768 — `#/live` / `#/incident` | ⚠️ **not visually verified** — the browser environment's `resize_window` / `window.resizeTo` did not produce a true small-viewport screenshot render (capture stayed 1536 px). No e2e coverage for D1/D3 at these widths. Recorded as a **Session-3 rehearsal check**. Not a numbered defect. |

## 6. Accessibility (axe-core 4.10.2, WCAG 2.0/2.1 A + AA)

| Route | Violations | Detail |
|---|---|---|
| `#/metrics` | **1** (`color-contrast`, serious) | the **active nav item** (`<button class="tg-body-strong">Metrics</button>`, `--tg-primary` `#6366f1` on `#12161b`, 14 px / 500) — contrast **4.06:1** vs the AA **4.5:1** threshold. 21 axe passes. |
| `#/live` | **2** (`color-contrast`, serious) | (1) active nav item `Live` (same root cause); (2) `<button>Launch</button>` 12 px (same `--tg-primary`). 22 passes. |

### NEW P3 — DEF-D9-009 — `--tg-primary` small-text contrast below AA

`--tg-primary` (`#6366f1`) as small text (12–14 px) on the dashboard's darkest
background (`#12161b`) measures **4.06:1**, under WCAG AA 4.5:1. Affects the
active nav item (all three) and the DC-strip Launch button. Legible, but under
the plan's stated threshold ("contrast remains at the required threshold").
**Fix (Phase 13):** darken the header ground or lighten `--tg-primary` for text
use, or reserve it for ≥ 18 px / bold. **Severity: P3.**

Reduced-motion (`prefers-reduced-motion`) is handled by `base.css` +
`test_ui_reduced_motion.py` (green). Focus styles: `:focus-visible` 2 px outline,
never `outline: none` (`base.css:16-23`).

---

## 7. AUDIT UI findings — Phase-11 dispositions

| ID | Result | Evidence |
|---|---|---|
| 008 (incidents unreachable) | **PASS** | D3 loaded via the Incidents nav while incidents open |
| 011 (D6 `0.000`) | **PASS** | "not resolvable" / "unreachable" everywhere; no misleading `0.000` |
| 016 (Stream Rail 800 px cap) | **PASS** | rail spans 1536 px canvas |
| 017 (Attempts tile capped) | **PASS** | server field, not the 200-buffer (Phase 8) |
| 018 (threat-band CSS) | **PASS** | valid wash token; glyph carries state |
| 019 (card fields decorative) | **PASS** | typed PAN → derived `card_hash`/BIN reach the request (see §4) |
| 020 (SSE `reconnecting` when healthy) | **PASS** | chip reads `SSE: live` |
| 023 (ticker score column blank) | **PASS** | decision label fills the column for scored rows |
| 024 (`(Day 1)` titles / stale comments) | **PASS** | titles correct; no `(Day 1)` in either `index.html`; no stale UI comments |
| 009 (refresh mid-attack all-clear) | **PARTIAL** | back-fill contract verified (Phase 7 Fault 4); `useEventStream` back-fills on every mount + queues live frames (source). A live browser refresh-mid-replay was not re-run (browser instability); Session-3 rehearsal check. |
| 013 (tier selector desync after refresh) | **PARTIAL** | source: selector reconciles from `replayStatus.tier`. Live refresh-mid-run not re-run; Session-3 rehearsal check. |
| 015 (reset doesn't clear frontend buffer) | **PARTIAL** | source: `run_id` change (→ `null` on reset) reinitialises every event-derived surface. Backend `reset` clears state (Phase 8); live UI-clears-on-reset not re-run; Session-3 rehearsal check. |
| 022 (`HTTP 500: NULL` errors) | **PARTIAL** | backend: every 4xx operator-readable (Phase 4); `DemoControlStrip.jsx:48-56` maps 401/409/503/network to copy, `ERROR_CLEAR_MS=8000`. Live error-trigger + clear not re-run; Session-3 rehearsal check. |

---

## 8. Verdict

**Phase 11 COMPLETE.** The dashboard (D0/D1/D3/D6) renders correctly and
**honestly** — every AUDIT UI fix present, D6 meets every plan honesty
requirement, no PAN/card-hash leakage anywhere. The storefront looks like a real
merchant. **AUDIT-019 PASS** — typed card values reach the scorer with correctly
derived `card_hash`/BIN.

**One P1 (DEF-D9-010): the storefront normal checkout is broken** (`onClick={pay}`
passes the React event into the fetch headers) — every "Pay" shows a false "Order
confirmed" with no scored attempt. 1-line fix, Phase 13, **top Session-3
priority**.

**One P3 (DEF-D9-009): `--tg-primary` small-text contrast 4.06:1** (< AA 4.5:1) on
the active nav item + Launch button. Phase 13.

Four AUDIT UI items (009/013/015/022) are PARTIAL — source-verified, backend-
verified, but a live browser re-run was blocked by renderer instability;
carried as Session-3 Rehearsal-#1 checks.
