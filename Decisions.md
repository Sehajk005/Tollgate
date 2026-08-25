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

---

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

---

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

---

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

---

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

---

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

---

## Gate C: Day 2 — "A Launchable Attack" (24 August 2026)

Decisions 25–38 were made during Day-2 planning and confirmed against the actual
implementation (not just proposed) while writing `packages/simulator/*`,
`services/scorer/{scoring,replay,routes_replay}.py`, `packages/detect/threat_state.py`, and
the Day-2 dashboard. Four (25, 29, 33, 35) were resolved by the user before implementation
began; the rest were proposed in the Day-2 plan and confirmed correct by the working code
and its test suite (`tests/acceptance/test_simulator_*.py`, `test_attack_tiers.py`,
`test_simulator_safety.py`, `test_fixture_integrity.py`, `test_replay_virtual_time.py`,
`test_day2_e2e.py` — A1–A16, all green).

## Decision 25: Replay executes in-process against the scoring core, driven by HTTP

### Context
Day 2 needs a demo-triggerable, virtual-time-driven replay of a synthetic attack through the
real Day-1 scoring path. An external HTTP-based replay driver would score each event through
`POST /v1/score`, which reads `state.clock` — always `SystemClock` on that path — reintroducing
finding F6 (wall-clock coupling breaks the 60x compression claim).

### Decision
**Resolved by the user.** `services/scorer/replay.py::ReplayDriver` runs in-process inside the
scorer, calling `services/scorer/scoring.py::score_attempt()` directly with its own
`VirtualClock`, never going back out over HTTP per event. `POST /v1/replay/start|stop|reset`
(TRD v2 §5, already listed "demo only") triggers it; `GET /v1/replay/status` and every SSE
event's `replay` key expose its progress.

### Alternatives considered
An external harness that POSTs to `/v1/score` per event — rejected outright per Context above.
A separate demo-only scorer process — rejected as unnecessary complexity; the real scorer
process already has everything the driver needs (`ScorerState`, the window store, the event
bus).

### Reasoning
In-process is the only way to inject a `VirtualClock` into the exact code path the storefront
uses, which is what makes A13 (speed=0 vs speed=60 produce byte-identical decision sequences)
and A14 (`ingest_time - epoch_ms == event.t_ms`) provable rather than approximately true.

### Trade-off
The replay driver and the storefront share one `ScorerState` (one `InMemoryWindowStore`, one
event bus) — a running replay and live storefront traffic contend for the same rule windows.
Acceptable for a single-merchant Day-2 demo; not a concern for Day 3+ multi-tenant work.

### Specification impact
None — TRD v2 §5 already named these endpoints as demo-only.

### Implementation impact
`services/scorer/replay.py` (`ReplayDriver`, `ReplayRequest`, `ReplayStatus`),
`services/scorer/routes_replay.py` (the four endpoints), `services/scorer/deps.py`
(`ScorerState.replay_driver`/`replay_task`, constructed in `build_default()`),
`services/scorer/app.py` (router registration; the lifespan cancels any running replay task
on shutdown).

---

## Decision 26: The scoring core is extracted into `services/scorer/scoring.py::score_attempt()`

### Context
Both `/v1/score` (SystemClock) and the replay driver (VirtualClock) need to run the identical
sequence: mint `ingest_ms`/`attempt_uid`, evaluate rules, apply the auto-ceiling, build
`AttemptRecord`/`ScoreRecord`, spool, and publish. Day 1 had this inlined in
`routes_score.py`.

### Decision
`services/scorer/scoring.py::score_attempt(state, *, merchant_id, ip, body, clock=None,
ulid=None, stopwatch=None, user_agent="")` is a pure extraction of Day-1 steps 5–11.
`routes_score.py` now does auth + `resolve_client_ip` + `Stopwatch()` and delegates. `clock`
and `ulid` both default to `state.clock`/`state.ulid`, so the storefront path is byte-for-byte
Day 1's control flow.

### Alternatives considered
Duplicating the scoring logic in the replay driver — rejected; two copies of "mint id,
evaluate rules, build records, spool, publish" would drift the moment either changed, and the
55 Day-1 tests could not prove the replay path was equivalent to the storefront path.

### Reasoning
The 55 Day-1 tests, run unedited before and after the extraction, are the proof of zero
behaviour change — this is what makes it a *refactor*, not a rewrite.

### Trade-off
`score_attempt` grew two parameters (`ulid`, `stopwatch`) beyond the plan's stated
`clock`-only signature, so replay can also make `attempt_uid` minting deterministic (see
Decision 27) and so `Stopwatch()` can still start at the true top of the HTTP handler (before
auth), preserving Day-1's exact `latency_ms` semantics.

### Specification impact
None — the wire contract, DB schema, and SSE payload's Day-1 keys are all unchanged.

### Implementation impact
`services/scorer/scoring.py` (new), `services/scorer/routes_score.py` (auth + IP + delegate).
Verified: `uv run pytest -q` → 55 Day-1 tests green with zero edits to any of them.

---

## Decision 27: Replay speed is a property of the replay driver, never of `VirtualClock`

### Context
TRD v2 §4.1 describes `VirtualClock(speed=60, epoch=t0)` returning `t0 + wall_elapsed × 60`.
Decision 20 already shipped `VirtualClock` as a pure counter with no `speed` parameter and no
wall-clock reads at all.

### Decision
Speed lives entirely in `services/scorer/replay.py::ReplayDriver.run()`: virtual time comes
from the event stream's own `t_ms` (`vclock.set_ms(epoch_ms + ev.t_ms)`), and `speed` only
scales the wall-clock `asyncio.sleep()` between sends. `speed=0` means no sleep at all.
**Supersedes TRD v2 §4.1's `VirtualClock(speed=...)`; Decision 20 stands unmodified.**

### Alternatives considered
Adding `speed` back onto `VirtualClock` — rejected; it would let virtual time depend on wall
time again, exactly the coupling Decision 20 eliminated, and would make A13 untestable in
principle rather than merely something to verify.

### Reasoning
Because virtual time is read from `ev.t_ms` and speed only changes wall-clock sleeps, `speed=0`
and `speed=60` are provably byte-identical in every value the scorer computes — this is
metamorphic relation M6 by construction, not by hope. `tests/acceptance/
test_replay_virtual_time.py::TestA13SpeedInvarianceOfDecisions` asserts the identical sequence
(including `attempt_uid`, via Decision 30's deterministic replay ULID) and, separately, that
`speed=1` takes measurably longer in wall time than `speed=0` — closing the "make both speeds
sleep zero" gaming move named in the Day-2 plan's test-gaming review.

### Trade-off
None functionally; it does mean TRD v2 §4.1's code sketch is now wrong and needs the
reconciliation noted below.

### Specification impact
**Requires a TRD v2 §4.1 update** (recorded in this same documentation pass): remove
`speed=`/`epoch=` from the `VirtualClock` constructor sketch and describe pacing as a replay-
driver parameter instead.

### Implementation impact
`services/scorer/replay.py::ReplayDriver.run()`'s loop.
`tests/acceptance/test_replay_virtual_time.py` (A13, A14) and `tests/acceptance/
test_day2_e2e.py` (A16) are the tests that would fail if this drifted.

---

## Decision 28: The simulator package is `packages/simulator/`; distillation lives in `scripts/`

### Context
The Day-2 brief's own documents disagreed: Impl Plan said `simulator/baseline.py`, the
brief's own safety test said `packages/simulator`, Schema §9 said
`python -m simulator.generate`, and `pyproject.toml` only installs `packages*`/`services*`/
`scripts*` — so a bare top-level `simulator/` package would not even be importable as built.

### Decision
`packages/simulator/{__init__,rng,profile,identity,baseline,attack,stream,generate}.py`;
entry point `python -m packages.simulator.generate`. The dev-only, pandas-dependent
distillation step is `scripts/distill_baseline.py`, deliberately *outside* `packages/simulator`
so `packages.simulator`'s transitive import closure — the thing A11's safety test statically
walks — stays small and never has a reason to import pandas/openpyxl.

### Alternatives considered
A top-level `simulator/` package (matches the Impl Plan's literal text) — rejected; not
installed by `pyproject.toml`'s package-discovery config, and would need either an unwanted
`pyproject.toml` structural change or would simply fail to import under `pytest`/`uv run`.
Putting distillation inside `packages/simulator/` — rejected per Context: it would put pandas
on the safety-tested import closure for no runtime benefit.

### Reasoning
`packages/simulator/` matches the *only* one of the three conflicting documents that is also
consistent with `pyproject.toml`'s actual `[tool.setuptools.packages.find]` config, so it is
the only choice that does not additionally require an undiscussed build-config change.

### Trade-off
None — this made the Impl Plan and Backend Schema wrong in two places, reconciled in this same
documentation pass.

### Specification impact
**Requires updates** to `07-IMPLEMENTATION-PLAN-v2.md` (deliverable paths) and
`04-BACKEND-SCHEMA-v2.md` §9 (bootstrap step 4's command).

### Implementation impact
The whole `packages/simulator/` tree and `scripts/distill_baseline.py` as built; confirmed via
`uv run pytest -q -m safety` (A11, 5/5 green) that the import-closure and text scans find
nothing, including a runtime pass with `socket.socket` monkeypatched to raise.

---

## Decision 29: Baseline grounding is a committed derived artifact, not the raw dataset

### Context
Day 2 needs the baseline traffic model to be grounded in something real, not hand-authored
numbers, while keeping the repository small and the simulator's runtime dependency-free.

### Decision
**Resolved by the user.** UCI Online Retail II (Chen, D., 2012; CC BY 4.0; verified this
session: 1,067,371 line-item rows across two sheets, 43.5 MB xlsx,
doi:10.24432/C5CG6D). The raw xlsx is downloaded once, gitignored
(`data/baseline/*.xlsx`), and never committed. `scripts/distill_baseline.py` (pandas +
openpyxl, dev-only) aggregates it into `data/baseline/online_retail_ii.profile.json` (~12 KB,
integers and strings only: `source`, `rows_aggregated`, `orders`,
`mean_order_value_gbp_minor`, 168 `hour_of_week_weights`, 1001-point
`order_value_quantiles_minor_gbp`) plus its `.sha256`, both committed with attribution.

### Alternatives considered
Committing the raw xlsx — rejected: 43.5 MB in git for a demo dataset, and CC BY 4.0 does not
require redistributing the raw file, only attributing derived use. A fully synthetic
(log-normal/Poisson) baseline with no real grounding — rejected by the user; the generative
fallback is kept behind the same interface but is not the default (Impl Plan's 20:00 cut
trigger stays executable if ever needed).

### Reasoning
CC BY 4.0 permits redistributing a derived, aggregated artifact with attribution; the derived
profile is small, integer-only (Decision 30), and is the exact determinism boundary the
simulator's runtime never crosses back over into pandas territory.

### Trade-off
The profile is generated once and hand-verified rather than continuously re-derived — an
edited profile without a regenerated `.sha256` is caught by `packages/simulator/profile.py`'s
load-time SHA check, which raises rather than silently loading stale data.

### Specification impact
**Requires updates** to `05-EVAL-PROTOCOL-v2.md` §4/V1 (dataset, licence, distillation method,
rescale formula), `02-PRD-v2.md` §6/§9 (attribution), `00-CHANGELOG-v1-to-v2.md` (judgement
call #2 marked resolved), and a new `README.md` (previously 0 bytes) with the CC BY 4.0
attribution the licence requires.

### Implementation impact
`scripts/distill_baseline.py`, `data/baseline/online_retail_ii.profile.json` + `.sha256` +
`README.md`, `packages/simulator/profile.py::load_baseline_profile()`. `pyproject.toml` gained
a `data` optional-dependency group (`pandas`, `openpyxl`); `.gitignore` gained
`data/baseline/*.xlsx`.

---

## Decision 30: Determinism via getrandbits-only sampling; canonical JSON serialization

### Context
The Day-2 gates require byte-identical output across two fresh subprocesses (A1), across
CPython 3.12 and 3.13 (A3), and across `speed=0`/`speed=60` replay runs (A13) — none of which
hold if any float repr, `dict` iteration order, or unseeded RNG call leaks in anywhere.

### Decision
`packages/simulator/rng.py::SubStream` wraps one `random.Random(derived_seed)` per
`(seed, label)` pair and exposes only `getrandbits()`-derived operations (`below()` via
rejection sampling, `pick_index()` via integer inverse-CDF over prefix sums) — no
`random.random()`, `choice()`, `shuffle()`, `sample()`, no numpy, anywhere in
`packages/simulator`. Every JSONL line is
`json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=True) + "\n"`, files
opened `newline="\n"`.

### Alternatives considered
`numpy.random.Generator` — rejected; adds a runtime dependency to `packages/simulator`
(violating Decision 28's "stdlib + pyyaml only") purely for sampling stdlib's `random` already
does deterministically. Floating-point amount rescaling — rejected; `packages/simulator/
profile.py::rescale_to_store_aov()` uses integer round-half-up (`(num + den//2) // den`)
specifically so no platform's float rounding can disagree.

### Reasoning
`random.Random`'s seeding and `getrandbits()` output are part of CPython's documented,
version-stable behaviour for `int`/`str` seeds — this is *why* A3 (cross-interpreter SHA
match) is provable rather than merely likely. Verified this session:
`test_simulator_determinism.py::TestA3` passes comparing a real CPython 3.12.6 subprocess
against a real 3.13.3 subprocess (`uv python list` confirmed both installed), run under
`uv run --isolated` so the nested interpreter selection cannot corrupt the outer project
environment.

### Trade-off
None inherent; one real operational hazard was found and fixed during implementation (see the
environment-stability note in this session's work): running `uv run --python <other>` from
*inside* an already-running `uv run pytest` process, without `--isolated`, causes `uv` to
rebuild the shared project `.venv` in place, racing and corrupting the outer process. Fixed by
adding `--isolated` to A3's nested interpreter calls.

### Specification impact
None new beyond what Decision 30 was already going to require; TRD v2 §7's "stdlib-only at
runtime" constraint is confirmed, not changed.

### Implementation impact
`packages/simulator/rng.py`, `packages/simulator/stream.py::canonical_line()`,
`packages/simulator/profile.py::rescale_to_store_aov()`. Verified via
`test_simulator_determinism.py` (A1–A4, all green) including the cross-interpreter check.

---

## Decision 31: Baseline and attack draw from disjoint, independently seeded RNG sub-streams

### Context
Eval Protocol v2 §4 requires "the attack half stays authored" — changing an attack parameter
(or even which tier is generated) must not perturb the baseline traffic's content or timing.

### Decision
Every `SubStream` is labelled by a fixed string never parameterized by tier for the baseline
side (`"baseline:arrivals"`, `"baseline:amount"`, `"baseline:customer"`, `"baseline:ip"`,
`"baseline:decline"`, `"baseline:session"`, `"baseline:guarantee"`) and by
`f"attack:{tier}:*"` for the attack side. Because each label hashes to an independent
`random.Random` seed (Decision 30), the two halves cannot influence each other's draws.

### Alternatives considered
One shared `random.Random` instance for the whole run — rejected outright; it is exactly the
coupling this decision exists to prevent, and would make A4 fail by construction.

### Reasoning
A4 (`tests/acceptance/test_simulator_determinism.py::TestA4BaselineIndependentOfTier`)
generates `tier=easy` and `tier=hard` at the same seed and asserts the baseline events' content
(minus `event_id`/`seq`, which encode merged-stream position and legitimately differ — see
Decision 32) is byte-identical between the two runs. This originally failed: the "guaranteed
baseline coverage inside the episode window" mechanism (added for A7) used the tier's actual
episode end time as its sampling bound, so the two tiers' differing episode durations (300s vs
900s) desynchronized the shared `"baseline:guarantee"` sub-stream's RNG consumption. Fixed by
anchoring that guarantee window to a fixed 60s span from `episode_start_ms` — tier-independent,
and still a subset of both tiers' actual episode window, so A7 keeps holding too.

### Trade-off
None — this is a correctness fix, not a compromise.

### Specification impact
None.

### Implementation impact
`packages/simulator/generate.py::GUARANTEE_WINDOW_MS` (60,000, fixed) replaces what would have
been the tier's own `ended_at_ms` in the call to `generate_baseline_events(...,
episode_windows=...)`. Verified: A4 and A7 both green simultaneously.

---

## Decision 32: Episode truth ships as filesystem artifacts on Day 2, not SQLite rows

### Context
`attempt_label.attempt_uid` foreign-keys `auth_attempt`, which only the async `Drainer`
populates — writing labels synchronously during replay would race the drainer and could
violate the FK constraint before the corresponding row exists.

### Decision
`packages/simulator/generate.py::build_stream()` returns `SimulatorOutput(events, labels,
episodes)` as in-memory dataclasses; the CLI writes them to `events.jsonl`/`labels.jsonl`/
`episodes.jsonl`. Loading into `episode_truth`/`attempt_label` remains Day 4's eval-loading
concern, not Day 2's.

### Alternatives considered
Writing labels to SQLite synchronously inside the replay loop — rejected per Context: would
require either blocking on the drainer's async insert or accepting real FK-violation risk.

### Reasoning
`event_id`/`seq` are assigned strictly sequentially across the *merged* stream, never from a
per-source counter, so no identifier's numeric range alone reveals whether it came from the
baseline or attack model (Day-2 Plan §F anti-leakage checklist) — this is also why A4's
baseline-content comparison must exclude `event_id`/`seq` and compare the remaining fields in
merged order instead.

### Trade-off
None for Day 2; Day 4 must still write a loader from these JSONL files into the DB tables.

### Specification impact
**Requires a Backend Schema v2 §9 update**: the JSONL record shapes for
`events`/`labels`/`episodes` were unspecified anywhere before this session; now specified.

### Implementation impact
`packages/simulator/stream.py` (`Event`, `Label`, `Episode`, `RawItem`, `merge_and_number()`).
Verified via A5 (episode counts match an independent recount from labels), A6 (events↔labels
bijection on `event_id`), A7 (baseline traffic inside every episode window).

---

## Decision 33: The threat band is server-computed and carried on the SSE event

### Context
The Day-2 dashboard needs a threat-state indicator that is honest — driven by what the rules
actually observed, not invented client-side — while Day 6's real incident detector does not
exist yet.

### Decision
**Resolved by the user.** `packages/detect/threat_state.py::ThreatRollup` is a stateful,
event-time-windowed rollup on `ScorerState.threat`: any R1 fire (or `throttle`) →
`elevated`; any R2/R3 fire (or `challenge`/`step_up`/`block`) → `under_attack`; no fire in a
rolling 5-minute (event-time) window → decays through `resolved` (30s event-time
auto-dismiss, per UIUX v2 §2.1) back to `calm`. `services/scorer/scoring.py` calls
`state.threat.observe(...)` and publishes the result as `threat_state` on every SSE event;
`services/dashboard/src/App.jsx` renders it verbatim, never deriving it locally.

### Alternatives considered
Deriving the band in the dashboard from raw `rules_fired`/`decision` fields — rejected by the
user and by the Day-2 plan's own test-gaming review: a frontend-derived band cannot be proven
honest by a server-side test, and `test_day2_e2e.py`'s threat-state assertions would be
meaningless.

### Reasoning
Rolling on `ingest_ms` (event time) exclusively — never wall time — is what keeps this
testable under A13: `tests/acceptance/test_clock_discipline.py`'s existing repo-wide AST scan
already covers `packages/detect/threat_state.py` with no changes to that Day-1 test, since it
recursively scans all of `packages/services/scripts`.

### Trade-off
This is explicitly a Day-2 stand-in, not real incident detection — no CUSUM, no drift
statistics, no entity resolution. Day 6 replaces it; the interface (`observe()` returning a
`threat_state` string) is designed to be swappable.

### Specification impact
None new; already anticipated as a Day-6 replacement point.

### Implementation impact
`packages/detect/threat_state.py` (new), `services/scorer/deps.py`
(`ScorerState.threat: Optional[ThreatRollup]`), `services/scorer/scoring.py` (calls
`observe()`, publishes `threat_state`), `services/scorer/replay.py::ReplayDriver.reset()`
(also clears the rollup). Verified via `test_day2_e2e.py`: a real easy-tier replay observed on
screen and via the API transitions `calm -> under_attack`, confirmed both automatically (A16)
and manually in a live browser session against the running dashboard.

---

## Decision 34: The SSE event gains `rules_fired`, `feature_snapshot`, `threat_state`, `replay`; `card_hash` never appears

### Context
The D1 dashboard needs enough per-event detail to render a live ticker with rule names and a
"cards per IP" tile, but `/v1/stream` remains unauthenticated (Day 1, unchanged on Day 2).

### Decision
`services/scorer/scoring.py`'s published event grew from Day 1's five keys
(`attempt_uid`, `decision`, `ip`, `bin`, `ingest_time`) to also carry `rules_fired`
(`evaluation.fired_names`), `feature_snapshot` (`evaluation.feature_snapshot`),
`threat_state` (Decision 33), `regime` (`"in_control"`, constant), and `replay` (a mirror of
`ReplayStatus.to_dict()`, or an idle placeholder when no `ReplayDriver` is attached).
`card_hash` is never added.

### Alternatives considered
Also publishing `card_hash` (would simplify a hypothetical future "cards per IP, actual list"
tile) — rejected; PRD v2 §9 treats disclosing threshold-proximity/identity detail on an
unauthenticated stream as evasion-assisting, and nothing on Day 2 needs it.

### Reasoning
Publishing `feature_snapshot` (raw rule counts) on an unauthenticated stream does disclose how
close an entity is to a threshold — a real, if Day-2-accepted, information leak. Mitigation
today is topological (the demo binds loopback only); stream auth is explicitly Day 7 hardening,
not addressed here.

### Trade-off
Accepted disclosure risk on the unauthenticated stream, scoped to loopback-only demo binding.

### Specification impact
**Requires a Threat Model v2 addendum** (this documentation pass): the SSE stream now carries
`rules_fired`/`feature_snapshot` while unauthenticated; disclosure accepted for the Day-2 demo,
stream auth deferred to Day 7. Also records that `TRUSTED_EDGE_HOSTS`' `X-Forwarded-For`
handling (Day 1, `services/scorer/net.py`) is now load-bearing for the replay-driven demo's
IP-per-event realism.

### Implementation impact
`services/scorer/scoring.py`'s `event` dict construction. Verified via `test_day2_e2e.py`: the
SSE payload's `rules_fired` is asserted non-empty and intersects {R1, R2, R3} names during a
real easy-tier replay; `threat_state` is asserted to transition `calm -> under_attack`.

---

## Decision 35: The four D1 tiles render in their specified shape with honest empty states

### Context
UIUX v2 specifies four D1 tiles, but two of their real data sources (`/v1/outcome` for decline
rate, the Day-6 blast-radius cap for enforcement) do not exist on Day 2.

### Decision
**Resolved by the user.** `ATTEMPTS · 5 MIN` is live (counted client-side from buffered SSE
events within 5 minutes of the latest event's own `ingest_time` — event time, not wall time,
so it reads correctly under 60x replay). `CARDS PER IP · TOP` is a live raw count
(`max(feature_snapshot.distinct_cards_per_ip_5m)` over the buffered window), captioned
"store-relative quantile · Day 5" since the quantile treatment isn't built yet.
`DECLINE RATE` and `ENFORCEMENT` render `—` and `— / 10` respectively, with their real captions
naming the day they light up. No tile ever renders a bare `0` for a metric with no data source.

### Alternatives considered
Inventing placeholder numbers for decline rate/enforcement — rejected by the user and by the
Day-2 plan's own failure-mode list ("rendering `0` in a tile that has no data source" is named
explicitly as a thing not to do).

### Reasoning
`ATTEMPTS · 5 MIN`'s window uses the *event-time* axis specifically because a wall-clock 5-
minute window would show almost nothing during a 60x-compressed replay (300 real seconds of
observation covering 5 virtual hours) — confirmed visually in a live browser session: the tile
climbed from 0 to 100 (its 100-event client buffer cap) within seconds of Launch at `speed=60`.

### Trade-off
None.

### Specification impact
**Requires a UIUX v2 §6.2 update**: the Day-2 empty-state rule for tiles without a data source.

### Implementation impact
`services/dashboard/src/App.jsx`'s `Tile` component and the `attemptsIn5Min`/`cardsPerIpTop`
derivations. Verified in a live browser session (this documentation pass): initial state shows
`CALM`, `0`, `—`, `—`, `— / 10` exactly as specified; after Launch, the live tiles climbed and
the fixed tiles stayed at their honest placeholders throughout.

---

## Decision 36: Day-2 DC strip is a documented subset; Reset is required, not convenient

### Context
UIUX v2's full DC strip includes controls (negative-control selector, flood toggle,
kill-scorer toggle) that presuppose Day 4/Day 7 features. Separately, `VirtualClock` cannot
move backwards (Decision 20) and `InMemoryWindowStore`/`ThreatRollup` both accumulate state
across a run.

### Decision
The Day-2 DC strip is exactly: tier selector (`easy`/`hard` enabled; `medium`/`evasive` shown
disabled with a "Day 4"/"Day 7" label, not hidden), Launch, Stop, Reset, a speed selector
(`0`/`1`/`60`), and the permanent chip. Negative-control selector and flood/kill-scorer
toggles are *omitted*, not stubbed. **Reset clears both `InMemoryWindowStore` and
`ThreatRollup`** (`ReplayDriver.reset()`) — without it, a second `Launch` in the same process
would inherit stale window/threat state and could not reproduce the same on-screen sequence.

### Alternatives considered
Stubbing the omitted controls as visibly-disabled buttons anyway — rejected; the Day-2 plan
explicitly distinguishes "omitted" from "stubbed," and there is no Day-2 behaviour for a
stubbed flood/kill-scorer button to even gesture at.

### Reasoning
Verified in the live browser session: a full `speed=0` replay ran to completion
(821/821 events); a subsequent `Reset` + `Launch` (`speed=60`) cycle correctly restarted from
`CALM` with an empty window store and produced the same `calm -> under_attack` progression —
confirming Reset is load-bearing, not cosmetic.

### Trade-off
None.

### Specification impact
**Requires a UIUX v2 §6.12 update**: the Day-2 DC subset, documented explicitly.

### Implementation impact
`services/dashboard/src/App.jsx` (tier/speed selectors, Launch/Stop/Reset buttons, the
permanent chip). `packages/features/memory_store.py::InMemoryWindowStore.clear()` (new,
additive, not exercised by any Day-1 code path). `services/scorer/replay.py::
ReplayDriver.reset()`.

---

## Decision 37: `golden.jsonl` is generated by an explicit command and is characterization-only for content

### Context
A fixture-reproduction test that regenerates its own expected answer and then asserts against
it proves nothing — the Day-2 plan's own test-gaming review names this exact move.

### Decision
`tests/fixtures/golden.{jsonl,labels.jsonl,episodes.jsonl}` are generated once by an explicit,
separate command (`python -m packages.simulator.generate --seed 42 --tier easy --hours 3
--epoch-ms 0 --out ... --labels ... --episodes ...`; the easy tier's `episode_duration_s` was
tuned from 300s to 600s specifically to land the fixture at 821 events, inside the committed
600–1200 target) and committed alongside a `sha256sum`-format `golden.sha256`. Regeneration-
reproduces-itself is `tests/characterization/test_golden_reproduction.py`, marked
`characterization` — informational, never a gate. The only *gating* fixture test
(`test_fixture_integrity.py`, A12) recomputes each file's SHA-256 from its committed bytes and
compares to `golden.sha256` — never to a literal hash in the test source, and never
regenerating the fixture itself.

### Alternatives considered
Making the reproduction test a gate — rejected per Context.

### Reasoning
The determinism gates that *are* gates (A1–A4) compare two fresh runs to each other, never to
a committed answer — this is what stops "generate golden.jsonl from the implementation, then
test that the implementation reproduces it," a structurally circular test.

### Trade-off
A silent, un-regenerated drift between the fixture and the current generator is possible in
principle (caught only by the advisory characterization test, not a gate) — accepted, per
Impl Plan v2.1 §1.2's characterization-test philosophy.

### Specification impact
None new — this is Decision 37/Changelog T4 as already named in the Day-2 plan, now
implemented.

### Implementation impact
`tests/fixtures/golden.jsonl` (821 events, 171,577 bytes), `.labels.jsonl`, `.episodes.jsonl`,
`.sha256` (generated with `sha256sum --text` for the two-space text-mode separator, not the
`*`-prefixed binary-mode default some `sha256sum` builds use). `tests/characterization/
test_golden_reproduction.py` (new). `config/attack_tiers.yaml`'s `easy.episode_duration_s`
(300 → 600).

---

## Decision 38: Every `attack_tiers.yaml` parameter is `{value, unit, source}`, checked structurally

### Context
A gameable anti-circularity test ("cite a real-looking source for one parameter, copy it
everywhere") would defeat the purpose of requiring citations at all.

### Decision
`config/attack_tiers.yaml`: every populated leaf (any dict containing a `value` key, skipping
leaves marked `pending`) has `value`, `unit`, `source`. `tests/acceptance/
test_attack_tiers.py::TestA10` checks each `source`: ≥12 characters, not matching a banned-
vocabulary regex (`synthetic|made-up|arbitrary|placeholder|guess(ed)?|n/a|unknown|tbd|todo`),
matching a citation-shape regex (a `§`+digit, a `Decision N`, a `doi:10.`, or a versioned
document name followed later by `§`), and requires ≥4 *distinct* source strings across the
whole file (11 achieved: Threat Model v2 §6/§7b, Eval Protocol v2 §4/V2/§5, PRD v2 §2, Impl
Plan v2.1 §Day 2). `medium`/`evasive` carry a `pending: "Day 4"`/`"Day 7"` marker and are
exempt.

### Alternatives considered
A single blanket citation for the whole file — rejected structurally by the distinct-source-
count check. Trusting human review alone — rejected as insufficient per the Day-2 plan's own
test-gaming review, though review remains the backstop for citation *authenticity* (the
mechanism cannot verify a citation is true, only that it is shaped like one and not obviously
fabricated).

### Reasoning
Every `source` string in the committed file is a real citation to a document already in this
repository (Threat Model v2, Eval Protocol v2, PRD v2, Impl Plan v2.1), verified by reading
those sections directly while authoring the values, not invented alongside them.

### Trade-off
Explicitly, per the Day-2 plan's test-gaming review: "a determined faker can write a
plausible-looking citation" — this mechanism is structural, not a proof of intent, and is
backstopped by human review, not a replacement for it.

### Specification impact
None new — Decision 38 as already named in the Day-2 plan, now implemented.

### Implementation impact
`config/attack_tiers.yaml` (11 real, distinct citations across `easy`/`hard`'s 9 populated
parameters each). `tests/acceptance/test_attack_tiers.py::TestA10AttackTiersAntiCircularity`.

---

## Decision 39: Day-3 environment — `docker-compose.yml` (two Redis services), `redis`/`pandas` moved into `dev`

### Context
Day 3 requires a real Redis backend and a differential test against `tests/oracles/
pandas_windows.py`. Neither `redis-server`, the `redis` Python package, nor a
`docker-compose.yml` existed on this machine; TRD §3's repository layout already names
`docker-compose.yml` at the repo root.

### Decision
`docker-compose.yml` defines two services: `redis` (the real backend, port 6379) and
`redis-small` (`--maxmemory 2mb --maxmemory-policy allkeys-lru`, port 6380), the latter used
**only** by `tests/acceptance/test_redis_eviction.py`, never by the application.
`pyproject.toml`'s `dev` extra gains `redis>=5.0` and `pandas>=2.2` (pandas was previously
only under `data`, which the differential-test suite does not install); a `redis` pytest
marker is registered for tests that skip when `TOLLGATE_REDIS_URL` is unreachable.

### Alternatives considered
A single Redis instance with `CONFIG SET maxmemory` toggled mid-test — rejected: mutating a
shared instance's memory ceiling introduces test-order dependence and risks leaving the
application's own instance degraded if a test fails mid-run.

### Reasoning
A dedicated, tiny, always-degradable instance keeps the eviction test's blast radius to
itself and makes "the app never sees `redis-small`" a structural fact, not a discipline.

### Trade-off
Two containers instead of one; accepted, since Docker Compose already exists for exactly
this.

### Specification impact
None — TRD §3 already named `docker-compose.yml`; this implements it.

### Implementation impact
`docker-compose.yml`, `pyproject.toml`.

---

## Decision 40: `window_key()` includes `window_ms` — a correctness fix, not a style choice

### Context
Backend Schema §4's documented Redis key pattern, `tg:{m}:w:{space}:{key}:{metric}`, omits
window width entirely. Day 1/2 never exposed this because R1-R3 each query exactly one
window width per `(space, metric)` pair. Day 3's `compute.py` queries `attempts_per_ip_60s`
**and** `attempts_per_ip_5m` — same space, same key, same metric, different `window_ms` — so
two logical windows would share one physical sorted set under the documented pattern.

### Decision
`window_key()` now takes `window_ms` as a required fifth argument:
`tg:{m}:w:{space}:{key}:{metric}:{window_ms}`. Verified before changing it that no test pins
the previous un-suffixed string (grep across `tests/`, `packages/`, `services/`).

### Alternatives considered
Leaving the pattern as documented and accepting the collision — rejected: two windows
destructively co-trimming each other (whichever `ZREMRANGEBYSCORE` runs first silently
discards entries the other window still needed) is a correctness bug, not a documentation
gap.

### Reasoning
This is the "repository differs from specification" case the Day-3 brief calls out
explicitly: identify the discrepancy, determine the correct action from the existing
mechanism's own stated purpose (a correct sliding window per declared width), don't silently
redesign anything else.

### Trade-off
None identified — purely additive to an unspecified format detail, verified unpinned.

### Specification impact
Backend Schema §4's key pattern should be read as illustrative, not literal, once multiple
window widths per metric are in play. No document edit made; this decision is the record.

### Implementation impact
`packages/features/keys.py`, `packages/features/memory_store.py` (both `window_key()` call
sites updated), `packages/features/redis_store.py` (Redis key construction uses the same
helper, so both backends stay byte-identical in key naming by construction).

---

## Decision 41: The idempotency key is `sha256(merchant_id ‖ event_id ‖ payload_digest)`, never `payload_digest` alone

### Context
Discovered via `tests/acceptance/test_score_api.py`'s existing R1 test, which sends 20
attempts with **constant** `card_hash`/`bin`/`amount_minor`/`currency` and only a varying
`event_id` — the realistic shape of card-testing traffic (same card, many attempts). The
first implementation keyed the Lua script's `SET NX` idempotency guard on `payload_digest`
alone (M-class fields only, deliberately excluding `event_id`). Since `payload_digest` was
therefore identical across all 20 calls, every call after the first was misclassified as an
idempotent replay: windows stopped accumulating, and R1 never fired (`throttle` expected,
`allow` observed).

### Decision
Threat Model §3 point 2 already specifies the correct formula and had simply not been
re-read carefully enough during the first pass: `idem_digest = sha256(merchant_id ||
event_id || payload_digest)`. `event_id`'s one stated permitted use (Threat Model §2's trust
boundary table) is exactly "idempotency correlation" — it belongs in the idem key, and
`payload_digest` alone must not stand in for it. `ScorePathRequest` now carries both
`idem_digest` (used only to build the `SET NX` key) and `payload_digest` (used only as the
`eidr` set member, per Threat Model §3 point 4's "distinct payload digests seen per
event_id").

### Alternatives considered
Keying solely on `payload_digest` — this was the bug; ruled out once the regression was
traced. Keying solely on `event_id` — rejected: a resubmitted `event_id` with a mutated
payload must NOT be treated as idempotent (that is precisely the `event_id_reuse_count`
signal, Threat Model §3 point 4), so `event_id` alone is also wrong.

### Reasoning
The specification already had this right; the bug was an implementation deviation caught by
running the existing locked Day-1 acceptance test against the new code, exactly as the
Day-3 brief's "fix failures at their source" instruction intends.

### Trade-off
None — this is a straight correctness fix with no design trade-off.

### Specification impact
None — Threat Model §3 point 2 already specified this; the fix conforms to it.

### Implementation impact
`packages/features/store.py` (`ScorePathRequest.idem_digest` field added),
`packages/features/memory_store.py`, `packages/features/redis_store.py` (idem key
construction), `packages/features/compute.py` (`idem_digest` computed and passed).

---

## Decision 42: `metric="ip"` extends TRD §6.1's `metric ∈ ev·card·bin·amt` enum

### Context
TRD §6.8 requires `distinct_ips_per_bin_5m` (R3's inverse-geometry sibling, tracking IPs
seen per BIN), whose sorted-set member is an IP address. §6.1's stated enum (`ev·card·bin·
amt`) has no member type for "IP as the tracked value."

### Decision
`metric="ip"` is added as a fifth value. §6.1's own phrasing ("`metric = bin`, `metric =
amt` likewise") already treats the list as illustrative extension-by-example, not closed.

### Alternatives considered
Reusing `metric="card"` with IP addresses as members — rejected: it would collide, in
principle, with a genuine `metric="card"` window over the same `(space, key)` if one were
ever added, and mislabels the physical key's contents.

### Reasoning
Minimal, additive, consistent with how `metric="bin"` and `metric="card"` are already used
for non-`ev` distinct-value tracking.

### Specification impact
None — extends an already-illustrative enum.

### Implementation impact
`packages/features/compute.py` (`distinct_ips_per_bin_5m` window request).

---

## Decision 43: Feature-vector neutral+coverage contract; raw counts kept separate from quantile-suffixed model features

### Context
TRD §6.8 lists 24 features (v2.1-corrected count). Several depend on inputs that do not
exist before Day 4 (`store_baseline`), Day 7 (`/v1/outcome`), or ever without a wire change
(`clock_skew_s` needs a client `ts` field `ScoreRequest` does not carry). Separately, R1-R3's
rule floors (Decision 17) must read absolute counts, independent of any learned baseline,
while the model-facing feature list uses quantile-suffixed names (`distinct_cards_per_ip_
5m_q`) for the same underlying statistic.

### Decision
Every `compute_features()` call always returns all 24 named keys; un-fed slots emit a
defined neutral (`0.0`) plus an explicit coverage indicator (`baseline_coverage`,
`outcome_coverage_ratio` — the latter already one of the 24), each carrying a `# Source:`
comment naming the blocking dependency. `FeatureVector.distinct_cards_per_ip_5m_raw` carries
R2's absolute count outside the 24 (its only canonical sibling is quantile-suffixed);
`attempts_per_ip_60s` and `distinct_cards_per_bin_5m` are both the raw statistic and a
canonical feature simultaneously, needing no separate field. `DayOneRules.
evaluate_from_features()` reads exactly these three raw values and is verified (`tests/
unit/test_rules_feature_parity.py`) to produce byte-identical `RulesEvaluation` output to the
locked `evaluate()`/`record_and_read()` path.

### Alternatives considered
Emitting `None`/`NaN` for un-fed slots — rejected: reintroduces exactly the NaN handling the
Day-3 "no NaN or infinity, ever" gate exists to forbid. Computing only the currently-feedable
subset — rejected: `feature_snapshot`'s shape would change again on Days 4/5/7, and Day 5's
time-travel test needs a stable vector shape across the whole training corpus.

### Reasoning
Keeps the 24-key `FEATURE_NAMES` contract exactly as TRD §6.8 states it while not silently
breaking R1-R3 (which must stay absolute-count-based per Decision 17) or the locked Day-1
rule tests.

### Trade-off
`feature_snapshot` values for un-fed slots are honest placeholders, not predictions —
correct today, but a reader must know Day 4/7 change these from `0.0` to real numbers.

### Specification impact
None new — implements TRD §6.8 and Decision 17 together.

### Implementation impact
`packages/features/compute.py`, `packages/detect/rules.py`
(`evaluate_from_features`), `services/scorer/scoring.py` (merges the canonical snapshot with
the rule-level snapshot so `distinct_cards_per_ip_5m` — the raw, un-suffixed key
`services/dashboard/src/App.jsx` already reads — survives on the wire).

---

## Decision 44: Redis `maxmemory` eviction is distinguished from TTL expiry via a separate polling connection on `INFO stats:evicted_keys`

### Context
Day-3 Plan §5 test 5 requires eviction and TTL expiry to fail differently: eviction must
degrade the feature vector to explicitly untrusted, never to silently-wrong counts, while
ordinary TTL-driven key expiry (memory hygiene, TRD §6.1) must not trip any degrade signal.

### Decision
`RedisWindowStore` opens a second connection (via the same connection pool's kwargs, not
reused from the main client) and polls `INFO stats` on a background daemon thread. A rise in
`evicted_keys` **latches** `trusted=False, degraded_reason="redis_eviction"` permanently for
that store instance — it does not reset, since past window counts may already be wrong by
the time eviction is detected. Verified directly against live Redis: a 20,000-write flood
into a 2MB-capped instance latches `trusted=False`; a 1-second TTL allowed to lapse
naturally leaves `trusted=True`.

### Alternatives considered
Checking `evicted_keys` on the main score-path connection before/after each call — rejected:
would add a second command to the steady-state score path, breaking the one-round-trip
invariant (TRD §6.3).

### Reasoning
`evicted_keys` only increments on `maxmemory` eviction, never on TTL expiry — it is the one
Redis-native signal that actually distinguishes the two failure modes the plan requires
distinguished.

### Trade-off
Detection is polled, not synchronous with the write that first got evicted — a small window
exists where an eviction has happened but not yet been noticed. Accepted: correctness of the
*eventual* degrade signal matters more than sub-second detection latency here.

### Specification impact
None — TRD §6.1/§6.3 name TTL as hygiene-only and never specify an eviction-detection
mechanism; this is the Day-3 implementation choice for a requirement the plan stated but did
not mechanize.

### Implementation impact
`packages/features/redis_store.py` (`_poll_eviction`, `_make_health_client`).

---

## Decision 45: CUSUM bucket counter is built raw; `τ_flag`-gated counting is explicitly deferred to Day 6

### Context
TRD §6.3 step 5 increments the CUSUM bucket counter *inside* the atomic script — i.e.
before scoring has produced `p_calibrated`. TRD §6.5 defines the statistic the CUSUM
actually needs, `n_t`, as attempts with `p_calibrated ≥ τ_flag`, which cannot be known at
the point §6.3 step 5 runs.

### Decision
Day 3 builds exactly the mechanism §6.3 names: `windows.lua` increments a raw per-bucket
attempt counter (`HINCRBY` on `tg:{m}:cusum`, rolling over on a new `floor(ingest_ms /
bucket_ms)`), returned as `cusum_bucket_index`/`cusum_bucket_count`. No `S_t` arithmetic, no
`τ_flag` gating, is implemented today — this is flagged as an open question for Day 6 rather
than silently resolved either way.

### Alternatives considered
Gating the counter on the rules-only `rule_score()` threshold as a Day-3 stand-in for
`p_calibrated` — rejected: inventing a substitute threshold not named anywhere in the spec
would let a Day-6 reader mistake it for a real decision rather than a Day-3 placeholder.

### Reasoning
Building the named mechanism without inventing the unspecified part keeps Day 3's scope to
what TRD §6.3 actually asks for, and leaves an honest, explicit question for the day that
owns the answer.

### Trade-off
The bucket counter's value is not yet the true `n_t` CUSUM will need; Day 6 must decide the
gating threshold before wiring `S_t`.

### Specification impact
None — explicitly named as an open question, not resolved.

### Implementation impact
`packages/features/windows.lua` (step 6), `packages/features/store.py`
(`cusum_bucket_index`/`cusum_bucket_count` on `ScorePathSnapshot`).

---

## Decision 46: Day-3 exit gate — Redis differential test green; `InMemoryWindowStore` fallback verified but not triggered

### Context
The pre-committed Day-3 fallback (Impl Plan §Day 3: "if the differential test is not green
by 20:00, cut Redis — ship `InMemoryWindowStore` behind the same protocol") is a trigger
condition, not a default.

### Decision
`tests/acceptance/test_window_differential.py` is parametrised over both backends. Both
passed: all 821 golden-fixture events, across 8 window statistics, match `tests/oracles/
pandas_windows.py`'s independent brute-force oracle exactly, on both `RedisWindowStore` and
`InMemoryWindowStore`. The fallback trigger was **not** hit; `ScorerState.build_default()`
selects Redis when `TOLLGATE_REDIS_URL` is set and reachable (verified end-to-end: R1 fires
`throttle` at the 20th attempt through the real Lua script over live Redis) and falls back to
`InMemoryWindowStore` — logged, not silent — when it is unset or unreachable (both cases
verified directly).

### Alternatives considered
N/A — this records an outcome, not a design choice between alternatives.

### Reasoning
Parametrising the one differential test over both backends means the fallback path is
*verified*, not merely assumed to work, regardless of which backend is actually live
tonight.

### Trade-off
None.

### Specification impact
None — this is the exit-gate outcome the plan's own trigger condition anticipated.

### Implementation impact
`services/scorer/deps.py` (`ScorerState._build_window_store()`),
`tests/acceptance/test_window_differential.py`.
