# Day 9 — Phase 6: Security QA

**Executed:** 2026-09-03 (Session 2)
**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 6. **Stop condition S-5 armed**
(any client-asserted data reaching a feature / model input / enforcement decision
→ P0, stop everything).

**S-5 verdict: NOT triggered.** Every trust-boundary probe passed.

Harness: `evidence/day-9/phase-6-security-harness.py` → `phase-6-security-results.json`
(35 checks). Acceptance subset: `pytest -k "trust_boundary or no_pan or outcome_hmac
or replay_auth or narrator_injection or narrator_startup or simulator_safety or
admission or fail_open"` → **48 passed**.

---

## 1. Client-asserted data cannot reach a feature / model / decision / identity (S-5)

One `POST /v1/score` carrying a maximally-hostile body — `ip`, `merchant_id`,
`attempts_per_ip_60s=999999`, `score_calibrated=0.999`, `score_raw=0.999`,
`decision="block"`, `rules_fired=["R1","R2","R3"]`, `control_arm=true`, `shed=true`,
`pan="4111111111111111"`, `cvv="123"`, `top_contributors=[…]` — plus a marker in
`card_hash`. Then the persisted `auth_attempt ⋈ attempt_score` row was inspected.

| Probe | Result |
|---|---|
| response `decision` | `allow` — the injected `"block"` was **not** echoed or applied |
| persisted `merchant_id` | `merchant_demo` — derived **only** from `X-Tollgate-Key` (body said `attacker-merchant`) |
| `feature_snapshot.attempts_per_ip_60s` | `1` — server-computed from the window store (body said `999999`) |
| persisted `score_calibrated` | `9.57e-05` — the real model output (body said `0.999`) |
| persisted `attempt_uid` | `01M1KK11…` — server-minted ULID, no marker bytes |
| persisted `rules_fired` | `[]` — server rule evaluation (body said `["R1","R2","R3"]`) |
| PAN / `cvv` key in the joined row | **absent** — `ScoreRequest` has no `pan`/`cvv` field; `extra="ignore"` drops them |
| `card_hash` | stored verbatim as the client's opaque identifier — **never** a model or feature input (Decision 34; the model runs on 4 live features, none a card hash) |

**No client-asserted value reached a feature, the model, the decision, merchant
identity, or `attempt_uid`.** `test_trust_boundary.py` (green) is the static/unit
counterpart.

---

## 2. Source IP — server-observed, trusted-edge boundary not widened

| Probe | Result |
|---|---|
| `X-Forwarded-For: 203.0.113.111` from the **redis** container (`172.28.0.20`, a peer **not** in `TOLLGATE_TRUSTED_EDGE_HOSTS = 172.28.0.11,172.28.0.12`) | **XFF ignored** — persisted `ip = 172.28.0.20` (the peer's own bridge IP) |
| `X-Forwarded-For: 198.51.100.77` through the **storefront Vite proxy** (`172.28.0.11`, the declared edge) | **XFF honoured** — persisted `ip = 198.51.100.77` (intended, Threat Model K8; the enabler for J6 step 6) |

`TOLLGATE_TRUSTED_EDGE_HOSTS` unset → the trust set is exactly the built-in
`{127.0.0.1, ::1, testclient}` (`net.py`). It **adds** the two Vite containers
under Compose; it does not widen the default. `test_trust_boundary.py` covers the
env-unset case.

---

## 3. No PAN / CVV / card-hash leakage

| Surface | Result |
|---|---|
| `attempt_score` / `auth_attempt` rows | no PAN, no `cvv` key (§1) |
| `/v1/stream/recent` (200 events scanned) | **no `card_hash` key** on any event (Decision 34 — SSE carries `bin`, never the hash); marker string absent |
| `docker compose logs scorer` (5 min) | injected PAN `4111…` **absent**; `card_hash` marker **absent** |
| `test_no_pan.py` | green (static + generation-run scan) |

---

## 4. Hostile strings → 200 / 422, never 5xx

`POST /v1/score` with, in turn: a 10 KB Devanagari `event_id`; a `session_id`
containing an RTL override + NUL + BEL + ANSI escape; a prompt-injection-shaped
`session_id`; a CRLF-bearing `event_id`. **All → 200**, no 5xx, no hang. The bytes
are stored as opaque evidence (`auth_attempt.client_evidence`) and have no path to
the narrator prompt (§6).

---

## 5. `POST /v1/outcome` — full HMAC lifecycle, live

Signed with the compose `TOLLGATE_OUTCOME_SECRET`, canonical body =
`json.dumps(model_dump(), sort_keys=True, separators=(",",":"))` (incl. the `None`
optionals), signing string `merchant_id\nts_ms\nnonce\nsha256(canonical)`.

| Case | Result |
|---|---|
| valid HMAC, real scored `event_id`, fresh nonce, fresh ts | **200 `{"status":"recorded"}`** — `auth_outcome` row persisted, `sig_verified=1` |
| same nonce replayed | **409 `{"detail":"replayed nonce"}`** (`outcome_nonce` PK) |
| unknown `event_id` | **404 `{"detail":"unknown event_id"}`** |
| stale timestamp (`ts=1`) | **401 `{"detail":"stale"}`** |
| tampered body (sign A, send B) | **401 `{"detail":"bad signature"}`** — via `test_outcome_hmac.py` (the live harness's own "tamper" case signed the tampered body, so it round-tripped; the acceptance test does the real sign-A-send-B) |
| unsigned (no HMAC headers) | **401 `{"detail":"unsigned"}`** |
| secret unset | **503** — `test_outcome_hmac.py` (compose secret is set, so not re-probed live) |

---

## 6. Narrator isolation

- `packages/narrator/bundle.py::build_bundle` — the single admission point. Signature
  takes `entity_type, pseudonym, decision, evaluation` only: **no `user_agent`, no
  raw identifier, no free text.** `EvidenceBundle` is a `@dataclass(frozen=True)`
  whose `__post_init__` **raises `ValueError`** for any `entity_type` / `decision` /
  `rules_fired` / `primary_rule` outside a code-defined closed vocabulary; numeric
  slots are floats. Pseudonyms only (`ip_1`, `bin_A`).
- `packages/narrator/prompt.py::assemble_prompt` — `CHARSET_RE.match` gate, **raises
  `PromptGateError`** if the prompt is not charset-clean; caller falls back to
  `template.py`.
- A hostile UA is retained in `auth_attempt.client_evidence` as evidence and has
  **no path** to the prompt.
- `test_narrator_injection.py`, `test_narrator_startup_validation.py` — green.
- Live (Phase 5): 2 incidents narrated, `narrative_source='template'`, no attacker
  string echoed.

**The narrator cannot influence enforcement** — it runs out-of-band, after the
terminal SSE publish (Decision 98), writing only `narrator_call` / the incident
`narrative` column.

---

## 7. Operator-action authentication

| Route | No key | Bad key | Well-formed body + no key |
|---|---|---|---|
| `POST /v1/replay/start` | 401 | 401 | 401 |
| `POST /v1/replay/stop` | 401 | 401 | 401 |
| `POST /v1/replay/reset` | 401 | 401 | 401 |
| `GET /v1/replay/status` | **200 (open — Decision 107)** | 200 | — |
| `GET /v1/incidents` | 401 | 401 | 401 |
| `GET /v1/incidents/{id}` | 401 | 401 | 401 |
| `POST /v1/incidents/{id}/confirm` | 401 | 401 | **401** (well-formed body) |
| `POST /v1/incidents/{id}/resolve` | 401 | 401 | **401** (well-formed body) |
| SQLi-shaped key `' OR '1'='1` | 401 | — | — |
| 64 KB key | 401 | — | — |

`test_replay_auth.py` (green) additionally asserts a **rejected** call changes no
state, and `503` (never a bypass) on a cold key cache + unavailable auth DB.

### Observation (not a numbered defect) — 422-before-401 on a malformed unauthenticated body

`POST /v1/incidents/{id}/{confirm,resolve}` (and `/v1/score`, `/v1/replay/start`)
with **no key AND a body that fails validation** → **422**, because FastAPI
validates the pydantic body parameter before the endpoint runs its `_auth()` call.
This is:
- **consistent** across every body-bearing route;
- **not an auth bypass** — a **well-formed** unauthenticated request always → 401
  *before* any DB read or state change (verified: `POST /v1/incidents/nonexistent/
  confirm` with a valid body, no key → `401 {"detail":"invalid or missing API
  key"}`, not 404);
- standard framework error-precedence. Classified as **by-design framework
  behaviour / known limitation**, not a product defect.

---

## 8. Demo controls inert by default

A throwaway scorer started on `:8099` **without** `TOLLGATE_DEMO_CONTROLS`:

```
GET  /v1/demo/cotenant-ip -> 404
POST /v1/demo/flood       -> 404
POST /v1/demo/fault       -> 404
```

`_require_demo()` raises `404` before auth, so the surface is **invisible** (not
merely forbidden) in production. The `/v1/score` fault hook requires **both**
`state.demo_fault` **and** `demo_controls_enabled()` (`test_demo_fault.py::…flag_
alone…`, green). The `x-tg-demo-xff` proxy promotion in `storefront/vite.config.js`
is likewise gated and inert off the demo path.

---

## 9. R-5 known limitations — reconfirmed, not defects

- **`/v1/stream` + `/v1/stream/recent` unauthenticated** (Decision 94; Plan §2 out
  of scope). Loopback / bridge-bound for the demo. Confirmed open in Phases 4 & 6.
  **Documented limitation.**
- **Outcome-derived features read `0.0`** (`decline_rate_per_ip_5m`,
  `invalid_cvv_share_ip_5m`, `outcome_coverage_ratio`) — block 3's "14 constant
  un-fed"; zeroed on model input regardless of any client `/v1/outcome` payload.
  Here a **security strength**: client-reported outcomes cannot move the model.

---

## 10. Hardening notes (not P0/P1)

- **No request-body size cap.** ~4 MB body → 200 (Phase 4). Volume mitigation is
  the per-merchant token bucket (`rate_per_s 50 / burst 200` → shed rung). A
  `Content-Length` limit at the edge would be defence-in-depth. Not on the demo path.

---

## 11. Verdict

**Phase 6 COMPLETE. S-5 NOT triggered.** No P0. No P1. No P2. No new numbered
defect — one by-design observation (422-before-401 error precedence). Every
plan-required boundary verified against the **running** application:
client-asserted data cannot reach features / model / decisions / identity; IP is
server-observed and the trusted edge is not widened by default; no PAN / CVV /
card-hash leaks to SSE or logs; the narrator has a single closed-vocabulary
admission point and cannot influence enforcement; operator actions are
authenticated (well-formed → 401 before any effect); `/v1/outcome` enforces
HMAC + staleness + single-use nonce (200 / 401 / 404 / 409 / 503); demo controls
are 404-invisible without `TOLLGATE_DEMO_CONTROLS=1`.
