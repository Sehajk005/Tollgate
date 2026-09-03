# Day 9 — Demo Script

Derived from what **actually succeeded** in Demo Rehearsals #1 (Pass B) and #2
against the real Docker Compose stack. Nothing here is aspirational — if a beat
is not in a green rehearsal transcript it is not in this script.

Six acts (App Flow J6 Act One + J7 Act Two). Budget: Act 1 ~3 min, Act 2 ~2 min.

---

## Setup (before the audience is watching)

```bash
docker compose down -v          # true clean slate
docker compose up --build       # ~60-90 s to all-healthy; wait for it
```

Confirm, in a terminal that is **not** on screen during the demo:

```bash
docker compose ps               # all 5 long-running services "healthy"
curl -s localhost:8080/healthz  # {"status":"ok",...}
```

Two browser windows, side by side, **no dev console open**:

| | |
|---|---|
| **LEFT** | storefront — `http://localhost:5173/?demo=1` |
| **RIGHT** | dashboard — `http://localhost:5174/` |

Starting state to verify on screen: dashboard threat band reads **`○ CALM`**,
`SSE: live` chip, "No incidents…", DC strip `REPLAY: IDLE`. Storefront shows the
Kesar & Co. product page.

**Known-good API key check** (contingency, off screen): the storefront must be
able to reach the scorer. If the very first checkout shows `HTTP 401` in the
`?demo=1` readout, the frontend containers booted before `bootstrap` wrote the
key — `docker compose up -d --force-recreate storefront dashboard` and retry.
(This is DEF-D9-011; the fix in `docker-compose.yml` `command:` makes it not
recur, but the check costs 3 seconds.)

---

## Act 1 — Normal checkout (the invisible protection)

| Step | Do | Expect on screen | Say |
|---|---|---|---|
| 1.1 | LEFT: "Buy now" → the checkout form | card form, "Pay ₹1,200" | "A real merchant checkout. The shopper types a card and pays." |
| 1.2 | LEFT: leave the default card, click **Pay ₹1,200** | routes to **"✓ Order confirmed"**; the `?demo=1` readout shows `/v1/score latency: ~15 ms · tier: allow` | "Behind that button, every attempt is scored — pre-authorization — in about 15 milliseconds. The shopper sees nothing. That is the point: protection the customer never feels." |
| 1.3 | RIGHT: the event ticker | one new row: `HH:MM:SS · pseudonym · truncated-IP · BIN · ALLOW` | "The risk console sees the attempt: a pseudonymous entity, a truncated IP, the BIN — never the card number. It stays on the left." |

**Backend evidence (if asked):** a `POST /v1/score` returned `200 {"decision":"allow"}`;
an `auth_attempt` + `attempt_score` row persisted with the typed BIN; the SSE
stream carried the event. Rehearsal #1 Pass B Step 1.

---

## Act 2 — The attack begins

| Step | Do | Expect | Say |
|---|---|---|---|
| 2.1 | RIGHT: DC strip — TIER `easy`, SPEED `60`, ☑ PACE FROM EPISODE — click **Launch** | `REPLAY: RUNNING (n/821)`; the ticker starts filling | "This is a recorded card-testing attack, replayed at 60× virtual time. The banner says it: **×60 VIRTUAL CLOCK · WINDOWS PRESERVED · TTD IN EVENT TIME** — the clock is fast, the detection windows are real, and time-to-detect is measured in the attack's own time, not ours." |
| 2.2 | wait ~60-80 s | threat band **`○ CALM` → `⟠ ELEVATED`**; the `ATTEMPTS · 5 MIN` and `CARDS PER IP` tiles climb | "Same IP, many cards, fast. The rules floor notices first — attempts per IP, distinct cards per IP, distinct cards per BIN." |
| 2.3 | continue | an **incident opens** (Incidents nav badge; system-state banner); threat band deepens | "Layer 2 — a sequential drift test on distinct cards — opens an incident. Time-to-detect here was ~78 seconds of event time." |

**Honesty note (say if the decline-rate beat comes up):** the outcome-derived
decline-rate features read `0.0` on this pre-auth path — there is no completed
auth outcome to derive them from. The detection above does not use them.

---

## Act 3 — The incident

| Step | Do | Expect | Say |
|---|---|---|---|
| 3.1 | RIGHT: **Incidents** nav → newest incident (D3) | header `Incident … · OPEN · proposed monitor/challenge · in force …`; sections: Narrative, Evidence (timeline + contribution bars + entity table), Audit trail, collapsed Client-asserted panel | "The full case. A generated summary — but the evidence below it is authoritative." |
| 3.2 | read the Narrative aloud | "Entity `ip_2` (ip) … distinct cards attempted against one BIN within 5 minutes, value 69 against threshold 20. Rules fired: attempts_per_ip_60s, distinct_cards_per_ip_5m, distinct_cards_per_bin_5m." | "Pseudonym, closed vocabulary. No raw identifier, no card hash — anywhere on this screen." |
| 3.3 | point at the Entities table | `ip_2 · ip · 198.51.100.xxx (truncated) · <count> · first/last seen` | "Entity-scoped. The IP, one `(ip, ua_class)`, or one card — never store-wide. The schema makes store-wide enforcement unrepresentable." |
| 3.4 | point at the in-force tier | `challenge` (auto), `confirmed_by: auto` | "The system did **not** block. `challenge` is the automatic ceiling — one extra check for the customer. `block` and `step_up` need an operator's confirmation. The system escalates on its own only as far as an inconvenience, never as a wall." |

**Backend evidence:** `GET /v1/incidents/{id}` returns the read model with
`entities / timeline / enforcement / contributions / client_evidence`; a scan of
the full JSON finds no PAN and no 64-hex card hash. Rehearsal #1 Pass B Step 4.

---

## Act 4 — Operator action & the CGNAT co-tenant

| Step | Do | Expect | Say |
|---|---|---|---|
| 4.1 | LEFT: back to the checkout; click **"Checkout as CGNAT co-tenant"** | routes to **"✓ Order confirmed"**; `?demo=1` readout shows `tier: allow · via co-tenant IP: 198.51.100.xxx` | "Now a legitimate shopper checks out from **the same carrier-grade NAT IP the attacker is on** — a real situation with mobile networks. The proxy stamps that IP; the scorer trusts it because the proxy is the declared edge." |
| 4.2 | RIGHT: ticker | the co-tenant's attempt: `ALLOW`, from `198.51.100.xxx` | "That customer got through. One clean attempt does not cross the rules floor, and the `challenge` ceiling guarantees they can never be blocked by the attacker's reputation. Nothing about that decision was special-cased — same entity resolution, same thresholds." |
| 4.3 | (optional) RIGHT: D3 → **"This was legitimate"** on the incident | incident → CLOSED; enforcement released; ceiling back to `challenge` | "And the operator can resolve it — closes the incident, releases every enforcement row, restores the default ceiling. Full audit trail." |

**Backend evidence:** `GET /v1/demo/cotenant-ip` → the enforced IP;
`POST /v1/score` with `x-tg-demo-xff: <that IP>` → `200 allow`, `auth_attempt.ip`
= that IP. Rehearsal #1 Pass B Step 5.

---

## Act 5 — Availability under stress (the two rungs)

### 5a. Fail-open rung (the one to show)

| Step | Do | Expect | Say |
|---|---|---|---|
| 5a.1 | RIGHT: DC strip DEMO group — click **Kill scorer** | D0 fail-open banner (monochrome) | "If the model or a dependency fails, the scorer does not 500 and does not block the merchant. It **fails open** — returns `allow`, marks the attempt `degraded_reason: fail_open`, and alerts once per window." |
| 5a.2 | LEFT: run a checkout | **"✓ Order confirmed"**, `tier: fail_open`, latency ~5 ms | "The customer is served. The console tells the truth about why." |
| 5a.3 | RIGHT: click **Kill scorer** again to clear | banner clears; next checkout `tier: allow`, `degraded_reason: null` | "Recovered, no restart." |

### 5b. Rules-only / shed rung (show, with the caveat)

| Step | Do | Expect | Say |
|---|---|---|---|
| 5b.1 | RIGHT: DC strip DEMO — click **Flood** | flood runs ~25 s; the flood status / scorer log shows `shed_responses` climbing | "A volumetric flood. The per-merchant token bucket drains and the scorer **sheds** — rules-only, no model, `X-Tollgate-Shed`. Here you can watch the flood's own requests being shed." |
| 5b.2 | click **Flood** again to stop | flood stops | — |

> **Known limitation (DEF-D9-004):** on this single-worker laptop scorer the shed
> is *intermittent* — the flood sheds ~1/3 of its own requests but does not
> reliably shed a single interactive checkout, and the D0 shed banner may not
> latch. **Do not** promise "watch my checkout get throttled." Frame it as "the
> flood is being shed" (visible in the flood counters / scorer log). On a
> multi-worker deployment this rung is crisp. The shed code path itself is
> proven by `test_admission_shed.py`.

---

## Act 6 — The metrics (and their limits)

| Step | Do | Say |
|---|---|---|
| 6.1 | RIGHT: **Metrics** nav (`#/metrics`) | "This renders from a committed evaluation artifact — zero live computation. Header shows the seed, the config hash, and whether the configs have changed since." |
| 6.2 | per-tier panel | "Model recall by tier: easy 0.00, medium 0.97, hard 0.73, evasive 0.39. The model is weaker than the B0 rules baseline on raw AP at **every** tier — and decisively better on `hard`, where B0's rules do not fire at all. We show both." |
| 6.3 | Tier E | "Tier E — the adaptive adversary — recall 0.39 model / 0.28 B0. The worst number in the deck, and its target-FPR point is **UNRESOLVABLE** (too few negatives). We say so on the screen." |
| 6.4 | discriminability audit | "Six features are excluded by the discriminability audit; the model runs on four live features." |
| 6.5 | cost curve | "Cost-optimal and F1-optimal thresholds; the rupee gap at steady-state prevalence is structural, not empirical (₹0), so the headline is the regime-switch saving." |

**Honesty requirements (all on screen, verified in rehearsal):** B0 beats the
model on AP at all four tiers; Tier E 0.39 / UNRESOLVABLE; 6 features excluded.
Say all of it.

---

## Reset / recovery (between runs)

```
RIGHT: DC strip → Reset      # -> REPLAY: IDLE, threat CALM, tiles clear, incidents cleared
```

For a **fully** clean restart (new run of the whole demo): `docker compose down -v
&& docker compose up --build`. A plain `Reset` is enough between takes of the same
demo.

---

## What NOT to do

- **Do not** open the browser dev console on screen.
- **Do not** click **Reset** mid-attack if you want the incident to persist for Act 3 — Reset closes open incidents.
- **Do not** promise the flood will throttle an interactive checkout (DEF-D9-004).
- **Do not** run `/v1/replay/start` with a tier other than the four in the dropdown (an unknown tier surfaces as a `failed` replay state — recoverable with Reset, but off-script — DEF-D9-005).
- **Do not** run `docker compose down` without `-v` and expect a clean state — the `tollgate_data` volume persists the DB.
- **Do not** describe the decline-rate feature as moving — it reads `0.0` on the pre-auth path.

## Contingency

| Symptom | Cause | Do |
|---|---|---|
| First checkout → `HTTP 401` in the readout | frontend booted before `bootstrap` wrote the key (should not happen post-DEF-D9-011 fix) | `docker compose up -d --force-recreate storefront dashboard`; retry |
| Threat band never leaves CALM | replay not actually running / wrong tier | check `REPLAY: RUNNING`; Reset and Launch again |
| `/v1/incidents` shows nothing after the attack | replay too short, or Reset was clicked | let `easy` run to `FINISHED`; do not Reset before Act 3 |
| Dashboard chip stuck `reconnecting` | SSE drop | it self-recovers via 5 s polling; or refresh the dashboard tab (state back-fills) |
| `verify_60x --gate throughput` cited as failing | it is — advisory on this machine (Decision 110), compute p99 = 12 ms | point at Act 6 / Decision 110 |
