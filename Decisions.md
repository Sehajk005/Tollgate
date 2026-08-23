# Tollgate — Engineering Decision Log

The single decision log for this project. No competing log file exists: the empty
placeholder that previously sat at the project root (`Design.md`) is no longer present —
this file (`Decisions.md`) is its replacement and the sole decision log going forward.

Entries are numbered in the order they were decided, not alphabetically. Each entry:
Context / Decision / Alternatives considered / Reasoning / Trade-off / Specification impact /
Implementation impact.

---

## Decision 1: Day 1 hard rules — R1 velocity, R2 card fan-out, R3 BIN concentration

### Context
No specification document ever enumerated the "three hard rules" Impl Plan Day 1 calls for.
Eval Protocol §8 names two baseline rules, but both depend on decline data from
`/v1/outcome`, which does not exist until later — so nothing decline-dependent is
computable on Day 1 from attempts alone.

### Decision
```
R1  attempts_per_ip_60s        >= 20   ->  minimum tier: throttle    [rate]
R2  distinct_cards_per_ip_5m   >= 15   ->  minimum tier: challenge   [source fan-out]
R3  distinct_cards_per_bin_5m  >= 20   ->  minimum tier: challenge   [issuer fan-out]
```
Rules set a **floor** (`final_tier >= max(rule_minimums)`), never a ceiling, and never
exceed the existing `challenge` auto-ceiling.

### Alternatives considered
Adding an amount-floor rule (rejected — see decision 3); deferring rule selection to Day 2
once real simulated traffic exists (rejected — see decision 4).

### Reasoning
The three rules deliberately cover three different attack geometries — volume from one IP,
card fan-out from one IP, and card concentration within one issuer range — so that a
card-testing campaign shaped any of the three ways is caught by something on Day 1, without
needing a learned baseline, an ML model, or a BIN metadata join.

### Trade-off
Absolute thresholds are a cold-start approximation; they have no statistical justification
beyond "a number an engineer would pick as obviously anomalous," and must be replaced by
store-relative forms later (decision 16).

### Specification impact
New: TRD §6.10. Referenced: PRD §5.1, Impl Plan Day 1, Eval Protocol §8 (B0).

### Implementation impact
`packages/detect/rules.py` implements exactly these three checks against
`WindowStore.record_and_read()`. Thresholds are configuration-driven (decision 16's sibling —
seeded from `config/rules.yaml` into `policy_config.rules_config`).

---

## Decision 2: R3 means cards-per-BIN, not BINs-per-IP

### Context
The instruction was explicit that R3 must measure `distinct_cards_per_bin_5m` and must not
be implemented as `distinct_bins_per_ip_5m` — the inverse geometry.

### Decision
R3 is keyed by BIN (space `bin`, key `<bin>`, metric `card`), counting distinct card hashes
seen against that one issuer range in 5 minutes.

### Alternatives considered
`distinct_bins_per_ip_5m` — rejected outright; it measures issuer *diversity* from one
source, not issuer *concentration* of an attack, and does not detect BIN enumeration at all.

### Reasoning
The card-testing thesis is that an attacker enumerates cards within a small set of issuer
ranges (often to validate a stolen BIN list). `distinct_cards_per_bin` catches concentration
against one issuer regardless of how many source IPs the attacker spreads across — the
inverse statistic would miss a distributed attack entirely. Independently corroborated: the
shipped Eval Protocol §8 baseline B2 is already "distinct cards per BIN over 5m above a fixed
threshold" — the existing spec already used this exact geometry.

### Trade-off
None identified — the two statistics are not substitutes for each other; R2 already covers
the per-IP fan-out geometry, so R3 covering the per-BIN geometry is complementary, not
redundant.

### Specification impact
TRD §6.8 (feature added), §6.10 (new). Eval Protocol §8 (B2 corroboration).

### Implementation impact
`packages/detect/rules.py` R3 check reads `record_and_read(space="bin", key=bin, metric="card")`.
A geometry test (decision 1's sibling test) proves the implementation cannot be satisfied by
computing `distinct_bins_per_ip` instead — two constructed scenarios (concentration in one
BIN across many IPs vs. diversity of BINs from one IP) must fire R3 and R2 respectively, and
never the other.

---

## Decision 3: Amount-floor rejected as a Day 1 rule

### Context
Eval Protocol §4/V2 (the single-feature discriminability audit) already identifies
`amount_is_floor` as the feature *most likely* to be a simulator artifact — an attacker's
amounts being generated at a fixed floor while baseline amounts come from a distribution is
exactly the kind of trivially-separable signal the audit exists to catch and flag.

### Decision
Do not add amount-floor as a Day 1 rule. It remains a feature/evaluation concern, subject to
the Day 4 audit, and is not load-bearing detection logic before that audit runs.

### Alternatives considered
Adding it as a fourth rule (or as a substitute for R3) — considered and explicitly rejected
by the user, precisely because it risks becoming load-bearing before the audit that checks
whether it is real signal or generator leakage.

### Reasoning
Shipping a rule that the project's own evaluation protocol predicts will likely be flagged
as fake would be building detection on a foundation the spec itself doesn't trust yet.

### Trade-off
Day 1's rule set is one signal poorer than it could be if amount-floor turns out to be real
signal — but that determination can only be made after Day 4, not before.

### Specification impact
Eval Protocol §4/V2 (note added), TRD §6.10 (explicit exclusion stated).

### Implementation impact
`packages/detect/rules.py` contains exactly three rules; no amount-based check.

---

## Decision 4: Rules are not deferred to Day 2

### Context
Impl Plan Day 1's goal is "an event goes in one end and a decision comes out the other,
visibly, today" — but a scorer that only ever returns `allow` (no rules) technically
satisfies "a decision comes out" without demonstrating anything about detection.

### Decision
R1–R3 are part of Day 1's deliverables, not deferred. Day 1 must be able to produce a
meaningfully non-`allow` decision.

### Alternatives considered
Shipping one trivial placeholder rule on Day 1 to prove the pipe, deferring the real three
to Day 2 once the simulator provides realistic traffic shapes to tune against — considered
and explicitly rejected by the user.

### Reasoning
The walking-skeleton principle (Impl Plan §0) is that Day 1 proves the *whole* pipe
end-to-end, including the part that makes a decision interesting. A skeleton that always
says "allow" doesn't exercise the tier-floor logic, the policy engine's ceiling clamp, or the
UI's non-allow rendering path — all of which Day 1's acceptance tests are meant to gate.

### Trade-off
Day 1 acceptance tests must include full threshold and geometry coverage for three rules
rather than one, adding test-writing time to the tightest day of the build.

### Specification impact
Impl Plan Day 1 (rewritten in v2.1).

### Implementation impact
`packages/detect/rules.py` and its full acceptance-test suite (thresholds + geometry) are
Day 1 deliverables, not deferred to Day 2's build order.

---

## Decision 5: `/v1/outcome` remains outside Day 1

### Context
The live Day 1 path is pre-authorization only: checkout → `/v1/score` → decision → gateway.
`/v1/outcome` is the post-authorization path that supplies actual gateway outcomes and
decline codes.

### Decision
Do not add `/v1/outcome` to Day 1. R1–R3 must not depend on outcome data, by construction.

### Alternatives considered
None seriously — this was already Impl Plan's stated Day 1 scope; the decision here is
confirming that R1–R3's design does not inadvertently require it (it doesn't: all three are
computable from `auth_attempt` alone).

### Reasoning
`/v1/outcome`'s signature verification, nonce table, and decline-composition features are
Day 7 work (HMAC hardening) and Day 3+ feature-pipeline work respectively. Introducing it
early would pull forward work with no Day 1 consumer.

### Trade-off
None — this is a pure scope confirmation, not a design compromise.

### Specification impact
Impl Plan Day 1 (confirmed, no change needed beyond the addendum note).

### Implementation impact
`services/scorer` implements `/v1/score` only on Day 1. No `/v1/outcome` route, no
`outcome_nonce` table population, no HMAC verification path.

---

## Decision 6: B0 (live rules) is a different object from B1/B2 (offline naive baselines)

### Context
TRD §6.9 originally said the Day 1 rules layer "is the naive baseline in the report" —
conflating a live, outcome-independent, install-minute-zero capability with an offline
evaluation baseline that assumes completed gateway outcomes already exist.

### Decision
- **B0** — the live Day 1 rules layer (R1+R2+R3). Pre-auth, outcome-independent, no learned
  baseline. Answers: *what can Tollgate do at install-minute-zero?*
- **B1** — the offline naive decline-velocity baseline ("N declines from one IP within M
  minutes"). Requires completed outcomes. Answers: *what could a competent engineer build in
  an afternoon if outcomes already existed?*
- **B2** — the BIN-concentration baseline, unchanged.

B0 and B1 are never reported as the same rule.

### Alternatives considered
Keeping the conflation and just renaming it — rejected; it would still credit the live
detector with information (completed outcomes) it never had at decision time, which is
exactly the kind of measurement-conditions error Eval Protocol §0 exists to prevent
("no metric is reported without the conditions under which it was measured").

### Reasoning
B0 and B1 differ in the one property that matters for an honest report: whether the
information used was available *at decision time*. Presenting them as one number would
misrepresent what the live system can actually do.

### Trade-off
The eval report must carry one more distinct baseline row than it otherwise would, and B2 is
now explicitly noted as a subset of B0's statistic (R3), which must be called out so B2
isn't double-counted as independent evidence.

### Specification impact
TRD §6.9 (rewritten), Eval Protocol §8 (rewritten to B0/B1/B2/B3), PRD §7 (baseline
comparison line rewritten).

### Implementation impact
`eval/harness.py` (Day 4) must implement B0, B1, B2, B3 as four distinct baseline
computations, not two.

---

## Decision 7: Spool-always replaces the in-memory-queue design

### Context
Backend Schema §1 originally described the buffered writer as an in-memory queue that spools
only after 3 flush failures. An in-memory queue cannot survive `SIGKILL` by definition —
whatever is sitting in memory at the moment of death is gone. Yet the same section (and Impl
Plan Day 1) asserted an acceptance test requiring zero attempts lost across a SIGKILL/restart
cycle. The two statements cannot both be true of the same mechanism.

### Decision
**Spool-always.** Every accepted attempt is appended to `spool/attempts-N.jsonl` with a
single `write()` *before* the response returns — always, not conditionally on failure. A
background drainer batches the spool into SQLite, one transaction per batch. Startup drains
any surviving segments before the service accepts traffic.

### Alternatives considered
Keeping the in-memory-queue design literally and reinterpreting "zero attempts lost" as "zero
*committed* attempts lost" (weakens the acceptance test's plain meaning); a fully synchronous
per-request `INSERT + COMMIT` into SQLite (trivially durable, but spends the p99 < 100 ms
latency budget on every request and contradicts Schema §5's "async: buffered insert").

### Reasoning
Ruled 23 August 2026: spool-always, explicitly not called a "write-ahead log" (the mechanism
is deliberately simpler than a WAL implies — no LSNs, no checkpoints, no recovery protocol).
Cost is one buffered `write()` per request (microseconds) against a 100 ms budget, and it
makes the stated acceptance test pass literally rather than requiring its wording to be
weakened.

### Trade-off
A `write()` per request, however cheap, is still I/O on every request that a pure in-memory
queue wouldn't need until batch-flush time. Accepted as negligible against the 100 ms budget.

### Specification impact
Backend Schema §1 (durability section fully rewritten), §0 (change table row added).

### Implementation impact
`packages/storage/spool.py` (append-only writer) and `packages/storage/drainer.py`
(background batcher with `INSERT OR IGNORE` on the ULID primary key) replace the originally
planned single `writer.py`.

---

## Decision 8: The durability invariant is tied to acknowledged 200 responses

### Context
"Zero attempts lost," stated in isolation, is ambiguous about what "lost" means relative to
what the caller was told. An attempt that never received a response carries no promise to
begin with.

### Decision
The invariant is: **every attempt that received a 200 response is present in SQLite exactly
once after restart.** Acknowledged attempts, not all attempts, are what durability is
measured against.

### Alternatives considered
Measuring against all attempts sent, regardless of whether a response was received —
rejected; it conflates client-side send failures (network drop before the request even
arrives) with a server-side durability defect, which are different failure classes.

### Reasoning
Ruled 23 August 2026, framed explicitly in terms of what was promised: an attempt is only a
durability failure if the system told the caller "this happened" and then failed to make it
true. This is also the only framing under which the acceptance test is actually checkable —
you can only assert against what you tracked as acknowledged.

### Trade-off
None — this is a clarification of what the test measures, not a weakening of the guarantee
for anything the system actually promised.

### Specification impact
Backend Schema §1, Impl Plan Day 1 acceptance tests.

### Implementation impact
The Day 1 crash-durability test collects acknowledged `attempt_uid`s client-side during the
send phase, then asserts `acknowledged == {rows in auth_attempt after restart}` with zero
duplicates — not a blind "count rows" assertion.

---

## Decision 9: Durability boundary is process death, not power loss

### Context
Without an explicit boundary, "durable" is ambiguous between surviving a killed process
(bytes already handed to the OS survive) and surviving a power failure (bytes not yet
`fsync`'d to physical media do not).

### Decision
The durability boundary is **process death**, not power loss. `SIGKILL` is the test;
machine crash and power loss are explicitly out of scope. No `fsync` is required or
performed. SQLite stays `journal_mode = WAL`, `synchronous = NORMAL`.

### Alternatives considered
Requiring `fsync` on every spool write to survive power loss too — rejected as scope beyond
what any specification actually requires, and a real latency cost against the 100 ms budget
for a guarantee nothing in the ten-day build's threat model calls for.

### Reasoning
Explicitly ruled: no `fsync` requirement should be invented unless an existing specification
requires power-loss durability. None does. Process-death durability (surviving a killed
service, which is the realistic Day 1 failure mode during development and demo rehearsal) is
the guarantee that's actually needed and actually cheap.

### Trade-off
A real power failure between the spool `write()` and the OS's own buffered write-back could
still lose data. Accepted and stated explicitly rather than silently assumed away.

### Specification impact
Backend Schema §1 ("Durability boundary: process death, not power loss" is now explicit
spec text, not an implicit assumption).

### Implementation impact
No `fsync()` call anywhere in `packages/storage/spool.py`. `synchronous = NORMAL` (not
`FULL`) in the SQLite connection factory.

---

## Decision 10: Two Vite + React 18 apps for Day 1 UI

### Context
Day 1 needs an ugly storefront checkout (S2) and a dashboard event ticker (D1) to
demonstrate the walking skeleton in a browser, within roughly a 2-hour UI budget on the
tightest day of the build.

### Decision
Two separate Vite + React 18 applications: `services/storefront` (`:5173`) and
`services/dashboard` (`:5174`) — matching TRD §2's stack choice and App Flow §1's port
assignment.

### Alternatives considered
Static HTML served directly from the FastAPI scorer (fastest to a working `curl → browser`
proof, but thrown away entirely on Day 2 when the threat band and demo-control strip need
real component structure, and it diverges from the two-app, two-port architecture every
later document assumes); building only the dashboard ticker on Day 1 and deferring the
storefront checkout to Day 2 (saves UI time on Day 1, but pushes storefront work onto Day 2,
which already carries the simulator).

### Reasoning
Building the real two-app architecture on Day 1 — even ugly — means Day 2 through Day 9 are
adding to working apps, not replacing throwaway ones. This mirrors the walking-skeleton
principle that governs the whole day: integrate the real shape early, when there's time to
recover if it's wrong.

### Trade-off
Roughly two npm scaffolds' worth of setup cost that a single-process static-HTML approach
would avoid — accepted as a one-time cost against six-plus days of building on top of it.

### Specification impact
Impl Plan Day 1 (UI stack specified), UIUX §10 (Day 1 row updated with the explicit
exclusion list).

### Implementation impact
`services/storefront/` and `services/dashboard/`, each a minimal Vite scaffold with one
`App.jsx`, no Tailwind, no router, no state-management library, no component library.

---

## Decision 11: Vite dev-server proxy, plus CORS middleware on the scorer

### Context
D6's stated rationale for the proxy configuration was that it "surfaces cross-origin/CORS/SSE
integration issues during Day 1 rather than hiding them through same-origin serving." On
inspection, a dev-server proxy makes the browser see same-origin requests — the cross-origin
hop happens server-side inside Vite's proxy — so it actually *removes* the CORS surface
rather than exposing it.

### Decision
Implement the proxy as instructed (browser → `:5173/v1/*` → proxied to `:8080`). Additionally
configure CORS middleware on the scorer for the two dev origins, so a direct cross-origin
call from the browser also works and the CORS surface remains genuinely testable.

### Alternatives considered
Proxy only, accepting that CORS is not actually exercised by the dev setup — considered, but
would leave the stated rationale (D6) technically incorrect about what the proxy achieves,
without gaining anything by leaving it uncorrected.

### Reasoning
The proxy is still valuable on its own merits — it genuinely does surface SSE-through-a-proxy
behavior (response buffering, `text/event-stream` passthrough, keep-alive handling), which
are real Day 1 integration risks distinct from CORS. Adding CORS middleware is nearly free
and closes the gap between the stated rationale and what the proxy alone actually tests.

### Trade-off
One additional small piece of scorer configuration (allowed-origins list) that wouldn't
otherwise be needed for the proxy path to work.

### Specification impact
Noted as an observation in the reconciliation; no document text asserts an incorrect claim
about the proxy (D6's instruction is followed as given), so no specification correction was
required — this is purely an implementation-completeness decision.

### Implementation impact
`services/scorer/app.py` includes CORS middleware allowing `http://localhost:5173` and
`http://localhost:5174` in addition to the Vite proxy configuration in each app's
`vite.config.js`.

---

## Decision 12: Acceptance-test authorship becomes a review-gate model

### Context
Impl Plan §1.8 stated that `tests/acceptance/**` is human-authored and off-limits to the
builder — the plan's stated anti-gaming mechanism, since a test derived from an
implementation that already exists proves nothing. The user's instructions for this session
directed the assistant to write these tests directly, which conflicts with §1.8's literal
rule.

### Decision
Replace the authorship rule with a review-gate model: the real protection is **temporal and
derivational independence** (tests must be written before, and derived from spec rather than
from implementation behavior), not literally who types them. Acceptance tests are written
first, carry a source-comment on every expectation naming its originating specification
section, and enter `tests/acceptance/**` only after human review and approval; once approved
they are locked (further changes require a `spec:`-prefixed commit and explicit sign-off).

### Alternatives considered
Writing tests first with no review gate (faster, but the §1.8 safeguard would be fully
suspended with nothing checking that the tests assert what was actually meant); honoring
§1.8 literally by having the user author `tests/acceptance/**` themselves (preserves the
safeguard completely, but blocks Day 1 on 2-3 hours of the user's own time).

### Reasoning
Ruled 23 August 2026, explicitly reframing what §1.8 actually protects against: the danger is
a test derived from code that already exists (self-consistent, passes by construction, and
proves nothing), not the literal identity of who typed the assertion. Source-tracing every
expectation to a spec line, writing tests before code, and gating entry to the protected
directory on human review preserves that protection under a different division of labor.

### Trade-off
The review-gate model requires an explicit pause for human sign-off before implementation
can begin against each batch of tests — slower than an ungated pass, but preserves the
safeguard's actual purpose rather than discarding it outright.

### Specification impact
Impl Plan §1.8 (authorship rule replaced).

### Implementation impact
Every file under `tests/acceptance/**` carries `# Source: <document> §<section> — <item>`
comments per expectation. A pre-commit hook (Day 1 deliverable, carried from the original
§1.8 mechanism) blocks changes to files under that directory without a `spec:`-prefixed
commit message.

---

## Decision 13: Approved acceptance tests are locked

### Context
Once tests exist and implementation begins against them, nothing stops silently editing a
test to make a failing implementation pass — the exact failure mode "never weaken or delete
a test simply to make the suite green" already warns against generally.

### Decision
Once an acceptance test is reviewed and approved, it is locked: any modification requires a
`spec:`-prefixed commit and explicit human sign-off, enforced by a pre-commit check.

### Alternatives considered
Relying on discipline alone without a mechanical enforcement — rejected, since the whole
point of Impl Plan §1.8's original design was a *mechanism* (the pre-commit check), not a
norm.

### Reasoning
A locked test that can only change via an explicit, differently-prefixed commit makes any
retroactive weakening visible in `git log --grep "spec:"` rather than blending into ordinary
implementation commits.

### Trade-off
Adds friction to legitimately fixing a genuinely wrong test — but that friction is the point;
it forces the fix to be deliberate and visible rather than silent.

### Specification impact
Impl Plan §1.8.

### Implementation impact
Pre-commit hook checks whether any file under `tests/acceptance/**` changed in the commit
and, if so, requires the commit message to start with `spec:`.

---

## Decision 14: `handmade_40.jsonl` is carved out of the review-gate model entirely

### Context
This fixture exists specifically to be an oracle that does not descend from any code the
builder wrote — forty events with feature values and an alert point computed by hand, on
paper. If the implementation agent generates both the fixture and its expected values, the
result is self-consistent by construction and has zero oracle value, regardless of how
carefully it's reviewed afterward.

### Decision
`handmade_40.jsonl` is excluded from the review-gate model described in decision 12 entirely.
It must not be generated, in whole or in part, by the implementation agent — not the events,
not the expected feature values, not the alert point.

### Alternatives considered
Applying the same review-gate model as other acceptance tests (write first, review, lock) —
rejected; review cannot detect this specific failure mode, because a reviewer checking "does
this fixture look plausible" cannot distinguish a genuinely independent hand computation from
one the same agent that will implement the detector also produced.

### Reasoning
The review-gate model (decision 12) fixes the *derivation-order* problem (tests before code).
It does not fix the *derivation-source* problem for this one fixture, where the entire value
is that the answer key comes from a source structurally incapable of also being the
implementation.

### Trade-off
This is 100% human labor with no possible delegation — roughly one hour, per the original
Impl Plan §6 estimate — that cannot be compressed by AI assistance at all, unlike every other
Day 1 deliverable.

### Specification impact
Impl Plan §1.8 (exception clause), §6 (carve-out strengthened), Backend Schema §7
(carve-out added).

### Implementation impact
`tests/fixtures/handmade_40.jsonl` and its expected-values companion are produced entirely
outside any agent-driven session, before Day 6 needs them as an oracle.

---

## Decision 15: Shed mode evaluates R1 only

### Context
Two contradictions existed simultaneously. First, Threat Model §4/P4 said shed-mode requests
"return `allow`" while TRD §5.1 and Threat Model §6 said shed mode runs a "rules-only fast
path" — directly opposed on whether rules run at all. Second, even granting that rules run,
the only shed-mode mechanism specified anywhere is `INCR tg:{m}:shed:{ip}` — a single integer
counter — which cannot supply the distinct-card-per-IP set R2 needs or the per-BIN key R3
needs.

### Decision
Shed mode evaluates **R1 only**. Threat Model §4/P4's "return `allow`" is corrected to match
the rules-only rung (§5.1/§6 win, since the entire point of the middle rung — fixing F5 — is
that a flood must not buy a completely unprotected checkout). R2 and R3 are explicitly
documented as not evaluated in shed mode, because the shed counter cannot compute them.

### Alternatives considered
Inventing a richer shed-mode data structure (e.g., a bounded set alongside the counter) so
R2/R3 could run too — explicitly rejected by instruction ("do not invent one" if no
mechanism exists in the specification); claiming R2/R3 run when they structurally cannot —
rejected as a false claim the acceptance tests would need to fake.

### Reasoning
Verified, not invented: all nine documents were searched for a shed-mode mechanism richer
than the one counter, and none exists. Documenting the true capability (R1 only, and even
that only approximately — see the accepted limitation below) is more honest than asserting a
capability that isn't there.

### Trade-off
**Accepted limitation, not fixed:** `INCR`+TTL is a tumbling window with arbitrary phase —
the same defect that removed HyperLogLog in TRD §6.1. Shed-mode R1 shares that defect. Making
it exact would need one sorted set on the shed path, which is a Day 7 design change and was
not made here.

### Specification impact
Threat Model §4/P4 (corrected), §6 (aligned); TRD §5.1 (corrected, with the tumbling-window
limitation documented explicitly).

### Implementation impact
The rules-only rung in `services/scorer` evaluates R1 against `tg:{m}:shed:{ip}` only; R2 and
R3 checks are skipped entirely in that code path, not silently approximated.

---

## Decision 16: R1–R3 have an explicit lifecycle; not all upgrade paths are specified

### Context
R1–R3's absolute thresholds exist only because no learned merchant baseline exists on Day 1.
Left undocumented, there was a real risk they would silently become the permanent detector
rather than being replaced once a baseline exists — the exact failure mode the instruction
warned against.

### Decision
Document the lifecycle explicitly. R2 has a **specified** upgrade path:
`store_baseline.cards_per_ip_quantiles` (already in Backend Schema §3.1) replaces the
absolute 15 with a store-relative quantile form, `distinct_cards_per_ip_5m_q` — this is the
existing CGNAT fix (F18), already designed for a different absolute rule. R1 and R3 have
**no specified upgrade path** — `store_baseline` has no cards-per-BIN quantile column, and
`attempts_per_ip_60s` carries no quantile-suffixed form anywhere in TRD §6.8. Both are marked
explicit future work, not invented here.

### Alternatives considered
Inventing a plausible quantile methodology for R1 and R3 so all three rules had a symmetric
upgrade story — explicitly rejected by instruction ("if the exact replacement semantics are
not yet specified, explicitly mark that as future work rather than inventing the
methodology").

### Reasoning
R2's upgrade path could be stated because it already exists in the shipped v2.0 schema for a
different reason (F18/CGNAT). Fabricating equivalent machinery for R1 and R3 would be adding
new product design under the guise of documentation reconciliation, which the instructions
explicitly prohibited ("do not make additional product or architecture decisions beyond what
is specified... without explicitly flagging them").

### Trade-off
R1 and R3 remain absolute-threshold rules indefinitely until a future decision specifies
their upgrade path — an acknowledged gap, not a silent one.

### Specification impact
TRD §6.10 (new), PRD §5.4 (rule lifecycle section added).

### Implementation impact
Rule threshold keys in `config/rules.yaml` / `policy_config.rules_config` are named
`*_absolute_coldstart` for all three rules, so a future swap (R2 first, since only it has a
specified target) is a visible, intentional edit rather than a silent reinterpretation.

---

## Decision 17: Cold-start rule floors are carved out of Threat Model §4/P3

### Context
Threat Model §4/P3 requires enforcement above `monitor` to be corroborated by evidence from
≥2 independent feature families across ≥2 CUSUM buckets. R2 alone firing (decision 1) floors
the tier at `challenge` with no corroboration at all. These are directly opposed once Layer 2
(CUSUM) exists from Day 6 onward.

### Decision
P3 governs Layer-2/CUSUM-driven enforcement only. It does not apply to the deterministic
rules R1–R3, whose tier floors hold without corroboration, permanently — on Day 1 and after
Day 6.

### Alternatives considered
Demoting rule floors to `monitor` from Day 6 onward once CUSUM exists, so P3's corroboration
requirement would apply uniformly to all enforcement sources (preserves P3's security claim
intact, at the cost of a mid-build behavior change that alters demo rehearsals recorded
before Day 6 versus after); recording the conflict as open and deciding at Day 6 (defers the
decision to when Layer 2 is actually planned, at the cost of carrying a known blocker into
that day's planning).

### Reasoning
Ruled 23 August 2026: carve out cold-start rules from P3 entirely, keeping R1–R3's behavior
identical from Day 1 through the rest of the build. Simpler, and avoids a demo-visible
behavior change partway through the project.

### Trade-off
**Accepted, explicitly:** a key-holder who forges a single fan-out pattern (e.g., replaying
distinct card hashes against one victim IP) can force a `challenge` on that entity without
any corroborating evidence — a narrower version of the enforcement-poisoning primitive P3
exists to bound. The residual is itself bounded by three unrelated mechanisms that remain
intact: P1 (auto-ceiling — `challenge` is the worst a forged rule floor can achieve, never
`block` or `step_up`), P2 (`K_max` blast-radius cap, so the poisoner cannot force `challenge`
on unlimited entities), and P4 (per-key token bucket, limiting how many forged attempts a
leaked key can submit at all). Recorded in the README's residual-risk paragraph, alongside
the existing P3 residual.

### Specification impact
Threat Model §4/P3 (carve-out and residual added), TRD §6.10 (cross-referenced).

### Implementation impact
`packages/detect/policy.py`'s tier-floor logic for R1–R3 is unconditional — it does not
gate on, or interact with, whatever corroboration logic Day 6's policy engine later adds for
CUSUM/drift-driven enforcement.

---

## Decision 18: `ClientOutcome` is derived client-side; the wire carries `decision` only

### Context
The instruction's acceptance test required `/v1/score` to "produce Decision and ClientOutcome"
and have "Decision and ClientOutcome returned." But App Flow §4 marks `shed` as
client-observed via the `X-Tollgate-Shed: 1` header, and TRD §5.2 states `fail_open` is
"never on the wire; the absence of a decision." A server cannot literally return a value
that only exists as the *absence* of a response.

### Decision
The `/v1/score` response body carries `decision` only. `ClientOutcome` — all eight values —
is produced by a single pure function, `resolve_client_outcome(status, headers, body,
error)`, living in `packages/contracts`, tested across all eight values including the header
path (`shed`) and the timeout/error path (`fail_open`).

### Alternatives considered
Adding a `client_outcome` field to the response body for the six decision cases — considered,
but rejected: that field could never legitimately hold `shed` or `fail_open`, making it a
field that structurally cannot express two of its own eight declared values. That is the
exact defect class Impl Plan finding T7 removed by splitting `Decision` and `ClientOutcome`
into two enums in the first place; reintroducing a single field that can't express its full
range would partially undo that fix.

### Reasoning
Ruled 23 August 2026: decision on the wire, `ClientOutcome` derived client-side. This
satisfies "both produced and tested" (the acceptance test exercises
`resolve_client_outcome` directly across all 8 values) while honoring TRD §5.2's "never on
the wire" constraint for `fail_open`, and App Flow §4's header-based signaling for `shed`.

### Trade-off
The acceptance test for "ClientOutcome returned" now tests a pure function's output rather
than a literal response-body field — a slightly less direct reading of the original
instruction's wording, but one that is actually satisfiable given the other constraints in
force.

### Specification impact
App Flow §4 (two corrections added: wire shape, Day 1 reachable subset), TRD §5.2
(unchanged; corroborated), Impl Plan Day 1 (contracts deliverable updated).

### Implementation impact
`packages/contracts/decision.py` (or a co-located module) implements
`resolve_client_outcome()`. The Day 1 contract test exercises it directly with synthetic
status/header/body/error combinations for all eight `ClientOutcome` values — it is not an
HTTP-level test of the response body, since two of the eight values can never appear there.

---

## Gate B implementation decisions (made during the build, 23 August 2026)

Decisions 1–18 above were made during Gate A (documentation reconciliation). The entries
below were made while writing and testing the actual Day 1 code (Gate B) and are recorded
per Impl Plan §7/§9 ("update decisions.md DURING implementation, not at the end").

## Decision 19: `WindowStore.record_and_read()` is a single call, both for counts and for distinct-counts

### Context
R1 needs a count of attempts per IP; R2/R3 need a count of *distinct* card hashes per
IP/BIN. A naive design would need two different store methods (`increment()` and
`count_distinct()`).

### Decision
One operation covers both: `record_and_read()` always does add-member-then-trim-then-
return-cardinality. When `member` is unique per event (R1's `metric="ev"`, member=
`attempt_uid`), cardinality equals the event count. When `member` is a shared entity value
(R2/R3's `metric="card"`, member=`card_hash`), re-adding the same member just updates its
timestamp, so cardinality equals the distinct-member count. Same code path, two statistics,
depending only on what the caller passes as `member`.

### Alternatives considered
Separate `increment_counter()` and `add_to_set()` methods — rejected; it would require
`DayOneRules` to know which method to call per rule, and would not carry over to Day 3's
single-Lua-script requirement (TRD §6.3) as cleanly.

### Reasoning
This is exactly the sorted-set mechanism TRD §6.1 describes for Redis (`ZADD` then
`ZREMRANGEBYSCORE` then `ZCARD`), reproduced faithfully in the in-memory backend so the
Day 3 backend swap changes nothing about the protocol or the callers.

### Trade-off
None identified — this is a direct translation of the spec's own described mechanism, not
a new design choice.

### Specification impact
None (TRD §6.1, §6.3 already specify this).

### Implementation impact
`packages/features/memory_store.py`'s `InMemoryWindowStore` is a dict of
`{window_key: {member: last_seen_ingest_ms}}`; `packages/detect/rules.py` calls
`record_and_read()` three times per attempt (once per rule) with different
`space`/`metric`/`member` arguments.

## Decision 20: `VirtualClock` never reads the wall clock at all

### Context
An earlier sketch of `VirtualClock` computed `now_ms()` as `epoch_ms + wall_elapsed_since_
construction * speed`, so it would still read real elapsed time (scaled by a speed
multiplier) between calls.

### Decision
`VirtualClock` is a pure counter: `now_ms()` returns a stored integer that only changes via
explicit `advance_ms()`/`set_ms()` calls. It never calls any wall-clock function internally.

### Alternatives considered
The wall-coupled design above — rejected, because it would make the acceptance test
"window expiry advances under VirtualClock with no wall time elapsed" only approximately
true (a few microseconds of real elapsed time would always leak in, scaled by whatever
speed factor Day 2's replay uses).

### Reasoning
A pure counter makes the test's claim exactly true rather than negligibly true, and removes
any wall-clock coupling that could threaten Day 2's byte-identical-stream-from-seed
determinism test or Day 6's metamorphic M1 (shift all ingest times by Δ → identical
results) later.

### Trade-off
Day 2's 60× replay driver will need to compute its own virtual-time increments per event
and call `advance_ms()` explicitly, rather than relying on `VirtualClock` to do wall-to-
virtual conversion itself. This is simple (one multiplication per tick) and was going to be
needed either way once events must map onto specific virtual timestamps rather than a
continuous scaled wall clock.

### Specification impact
None — TRD §4 specifies the `Clock` abstraction and `VirtualClock(speed=...)` conceptually;
this implementation detail (no wall coupling) is a stronger fulfillment of "deterministic
virtual time," not a deviation from it.

### Implementation impact
`packages/clock/clock.py`'s `VirtualClock` has no `speed` parameter and no internal
wall-clock read; `advance_ms(delta_ms)` and `set_ms(value_ms)` are the only ways its time
moves, and both reject moving backwards.

## Decision 21: Spool segment is never truncated or rotated on Day 1

### Context
The reconciled Backend Schema text describes the drainer "truncating/rotating the spool
segment... once that transaction commits." Implementing this literally means renaming or
clearing a file that the `Spool` writer may still hold open for appending.

### Decision
The Day 1 drainer never renames or truncates the active spool segment. It tracks a byte
offset (in memory) and only reads forward from that offset; recovery after a crash
re-drains the whole file from byte 0, relying on `INSERT OR IGNORE` (keyed on the ULID
primary key) to make that safe.

### Alternatives considered
Renaming the active segment aside once drained and creating a fresh one for the writer —
rejected for Day 1: renaming a file that another handle has open for writing has unreliable
semantics on Windows (no `FILE_SHARE_DELETE` by default on `open()`), which is a real risk
on this development environment, and getting it wrong would silently corrupt or lose
spooled data — a far worse outcome than an unbounded spool file at Day-1 test volumes.

### Reasoning
The durability *guarantee* (every acknowledged attempt lands in SQLite exactly once) does
not require segment rotation — `INSERT OR IGNORE` on a byte-0 re-drain already provides it.
Segment housekeeping is a disk-usage optimization, not a correctness requirement, so it was
deferred rather than risking a cross-platform file-handle bug to implement it on Day 1.

### Trade-off
The spool file grows without bound for the life of the process. At Day 1 scale (tens to
low-hundreds of attempts in dev/testing) this is negligible; it becomes a real concern only
at production volumes, which are explicitly out of scope for a walking skeleton.

### Specification impact
Backend Schema §1's drainer description is fulfilled in guarantee but not in literal
mechanism; `packages/storage/drainer.py`'s module docstring documents this explicitly so it
isn't mistaken for an oversight.

### Implementation impact
`packages/storage/drainer.py`'s `Drainer.drain_once()` reads via `fh.seek(self._offset)`
and stops at any line not yet terminated by `\n` (a torn write in progress), never
advancing the offset past a partial line. `drain_from_start()` resets the offset to 0 and
is called once at service startup, before the app accepts traffic.

## Decision 22: The SSE acceptance test runs against a real subprocess, not the in-process TestClient

### Context
The first implementation of `test_scored_event_reaches_sse_stream` used FastAPI's
`TestClient` with a background Python thread consuming `client.stream("GET", "/v1/stream")`
while the main thread called `client.post("/v1/score", ...)` on the same `TestClient`
instance. This hung indefinitely (confirmed by running the suite and observing no
completion after several minutes, then isolating the single test file with a shell-level
timeout).

### Decision
The SSE test spawns the real scorer as a subprocess (the same
`scripts/_run_scorer_for_test.py` harness built for the durability test) and talks to it
over a real TCP socket with `httpx`, from two independent threads.

### Alternatives considered
Two separate `TestClient` instances against the same in-process `app` object — not
attempted, given the suspected root cause (a single shared `anyio` portal thread inside
`TestClient`/`starlette.testclient` not reliably interleaving a long-lived streaming call
with a second concurrent call); an async test using `httpx.AsyncClient` + `ASGITransport`
with `asyncio.gather()` in one event loop — plausible and possibly more efficient, but
would have required adding `pytest-asyncio` as a new dependency and a different fixture
style for a single test, for uncertain benefit over the subprocess pattern already proven
to work reliably for durability.

### Reasoning
A real OS process on a real socket is not subject to any in-process portal serialization
concern, and is arguably a more faithful test of what an SSE consumer actually does in
production (a real HTTP client, not a test harness's internal transport). Reusing the exact
subprocess-spawning machinery already built and proven for the durability test kept the fix
small.

### Trade-off
This test is slower (~9s, dominated by subprocess startup) than an in-process version would
have been, and is marked `@pytest.mark.slow` alongside the durability test rather than
running in the fast loop.

### Specification impact
None — this is a test-implementation detail, not a behavior or contract change. The
acceptance criterion (a scored event reaches the SSE stream) is unchanged.

### Implementation impact
`tests/acceptance/test_sse.py` was rewritten to mirror
`tests/acceptance/test_durability.py`'s `_spawn`/`_wait_for_health`/`_seed_merchant` pattern
instead of using the `client`/`scorer_state` fixtures from `tests/conftest.py`.

## Decision 23: `on_event` replaced by `lifespan` in the FastAPI app factory

### Context
Running the test suite surfaced `DeprecationWarning`s: FastAPI's
`@app.on_event("startup"/"shutdown")` decorators are deprecated in favor of a `lifespan`
async context manager.

### Decision
`services/scorer/app.py` uses `@asynccontextmanager` + `lifespan=lifespan` passed to
`FastAPI(...)` instead of the two `on_event` decorators. Behavior is identical
(drain-then-start on entry, stop-then-close on exit via `try/finally` around `yield`).

### Alternatives considered
Leaving the deprecated decorators in place — rejected; the fix was a same-turn, zero-risk
cleanup (verified by rerunning the full suite immediately after) and there is no reason to
ship code that already emits warnings about an API the installed FastAPI version will
eventually remove.

### Reasoning
No behavior change, only an internal wiring change; the full test suite (55 tests) was
rerun immediately after and confirmed green with the warning gone.

### Trade-off
None.

### Specification impact
None.

### Implementation impact
`services/scorer/app.py`: `create_app()`'s two `@app.on_event(...)` handlers were replaced
by one `lifespan` async context manager.

## Decision 24: Two test-fixture bugs found and fixed by actually running the suite

### Context
Running the Day 1 acceptance suite for the first time (Impl Plan §9's required discipline
— "after every meaningful implementation step, run the most relevant tests") surfaced
three failures, all traced to the same root cause: `TestR1Velocity`'s and
`test_three_hard_rules_produce_meaningfully_non_allow_decision`'s test helpers varied
`card_hash` on every iteration while holding `ip` constant, intending to isolate R1
(attempt volume). Since R2 is keyed on `(ip, distinct card_hash)`, varying the card hash on
every request from the same IP *also* accumulated R2's distinct-card count, which crossed
R2's threshold (15) before R1's threshold (20) was reached — so the test observed
`challenge` (R2 firing) where it expected `throttle` (R1 firing).

### Decision
Both test helpers now hold `card_hash` (and, in `test_rules.py`, `bin`) constant across
every iteration, so only attempt volume varies and R1 is genuinely isolated.

### Alternatives considered
None — this was a bug in the test's own construction, not a specification ambiguity or an
implementation defect; `packages/detect/rules.py` was already computing R1/R2/R3 correctly
per their independent definitions.

### Reasoning
Per Impl Plan §9's debugging discipline: when a test fails, first determine whether the
implementation or the test is wrong. Here, `distinct_cards_per_ip_5m` climbing to 20 when
`card_hash` changes on every one of 20 requests from one IP is the *correct* behavior of R2
— the test's premise (that this sequence exercises R1 alone) was wrong, not the rule.

### Trade-off
None.

### Specification impact
None — no rule definition changed; only the tests' request sequences did.

### Implementation impact
`tests/acceptance/test_rules.py`'s `_fire_r1()` and
`tests/acceptance/test_score_api.py`'s
`test_three_hard_rules_produce_meaningfully_non_allow_decision` both updated to use a
constant `card_hash` (and `bin`, in the former) across their loop. Confirmed via the full
suite: `55 passed` after the fix.
