"""
Source: TRD v2 §6.3 -- Day 3's Redis backend must perform
write -> trim -> read vector -> CUSUM increment inside ONE Lua script (one
round trip per score call). This protocol is shaped as a single call for
exactly that reason: a split add()/read() protocol would force a redesign of
every caller on Day 3.

Day-3 Plan Step 1 -- `record_and_read()` and `WindowRequest`/`WindowSnapshot`
are untouched (Day-1 callers, `DayOneRules.evaluate()`, and every locked
Day-1 acceptance test keep working unmodified). The batched one-round-trip
score path is added alongside on the same `WindowStore` protocol as
`score_path()` -- additive, not a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, Tuple


@dataclass(frozen=True)
class WindowRequest:
    merchant_id: str
    space: str
    key: str
    metric: str
    member: str
    ingest_ms: int
    window_ms: int
    # Source: Day-3 Plan Step 1 -- BIN-structure features (bin_hhi_5m,
    # bin_entropy_5m) need the member distribution, not just the
    # cardinality. Defaults to "count" so every existing WindowRequest
    # construction (Day-1 rules, tests) is unaffected.
    read: Literal["count", "members"] = "count"


@dataclass(frozen=True)
class WindowSnapshot:
    count: int


@dataclass(frozen=True)
class ScorePathRequest:
    """
    Source: TRD §6.3 -- one atomic call: idempotency SET NX -> ZADD every
    window -> trim every window -> read back the full raw vector ->
    increment the CUSUM bucket counter. Day-3 Plan Step 1.

    `idem_digest` and `payload_digest` are deliberately different values
    (Threat Model §3 point 2): `idem_digest` = sha256(merchant_id ||
    event_id || payload_digest) keys the SET-NX idempotency guard, so a
    genuine retry of the same request reproduces it exactly while a
    distinct attempt against the same card (different event_id, same
    M-class fields -- ordinary card-testing traffic) does not collide.
    `payload_digest` alone (M-class fields only, no event_id) is the eidr
    set member: "event_id seen with >=2 distinct payload digests" is
    exactly how event_id reuse is detected (Threat Model §3 point 4).
    """

    merchant_id: str
    ingest_ms: int
    idem_digest: str
    payload_digest: str
    attempt_uid: str
    idem_ttl_ms: int
    event_id: str
    card_hash: str
    card24_ttl_ms: int
    windows: Tuple[WindowRequest, ...]
    cusum_bucket_s: int
    window_ttl_slack_ms: int
    # Source: remediation plan FIX-004 (AUDIT-005) -- the RUN scope for the
    # idempotency key, and only for the key. `""` is storefront traffic, whose
    # key stays byte-identical to what shipped and whose 24-hour retry contract
    # (Threat Model §3) is therefore untouched; a replay passes `r{run_id}:` so
    # the second run of a tier cannot be swallowed as a replay of the first.
    #
    # Deliberately NOT folded into `idem_digest`: that value is observed by the
    # determinism tests, the golden fixtures and the in-process decision cache,
    # so varying it per run would break "two fresh runs agree". Varying only the
    # KEY isolates runs while leaving every asserted value identical.
    idem_namespace: str = ""


@dataclass(frozen=True)
class ScorePathSnapshot:
    """
    Source: TRD §6.3 -- everything the Lua script returns to Python in one
    round trip. `counts`/`members` are positionally aligned with the
    `windows` tuple on the originating ScorePathRequest.
    """

    idempotent_replay: bool
    stored_attempt_uid: Optional[str]
    counts: Tuple[int, ...]
    members: Tuple[Optional[Tuple[str, ...]], ...]
    event_id_reuse_count: int
    card_seen_24h: int
    cusum_bucket_index: int
    cusum_bucket_count: int
    # Source: Day-3 Plan Step 4 -- distinguishes Redis maxmemory eviction
    # (undercounts silently) from ordinary TTL expiry (correct by design).
    # False means "do not trust these counts"; rules still evaluate, but
    # the feature vector and its downstream decision are marked degraded.
    trusted: bool
    degraded_reason: Optional[str]


class WindowStore(Protocol):
    def record_and_read(self, request: WindowRequest) -> WindowSnapshot: ...

    def score_path(self, request: ScorePathRequest) -> ScorePathSnapshot: ...

    # Source: Day-7 Plan §4 Step 3 -- the rules-only shed rung. Increments the
    # merchant-scoped shed counter `tg:{m}:shed:{ip}` and returns the new
    # value; the counter expires `ttl_ms` after its first increment. Additive,
    # exactly like `score_path()` was on Day 3. `now_ms` comes from the
    # injected clock (the in-memory backend needs it for TTL expiry; the Redis
    # backend lets PEXPIRE handle it). This runs OUTSIDE the atomic score path
    # -- shed structurally precludes `compute_features` / model / Layer 2.
    def shed_incr(self, merchant_id: str, ip: str, now_ms: int, ttl_ms: int) -> int: ...

    # Source: remediation plan FIX-003 (AUDIT-001) -- `ReplayDriver.reset()` has
    # called `window_store.clear()` since Day 2, but the method existed only on
    # the in-memory backend and was never on this protocol. Under the DOCUMENTED
    # Redis configuration it therefore threw `AttributeError` on the first line
    # of reset, which took out all five clears with it and returned HTTP 500.
    #
    # Contract: remove ONLY Tollgate-owned state, scoped to `merchant_id` when
    # given, and return how many keys were removed so the reset route can report
    # a real per-layer result. `merchant_id=None` clears every `tg:*` key this
    # store owns. NEVER `FLUSHDB` -- unrelated data in the same logical Redis DB
    # must survive (asserted by test_window_store_clear.py).
    def clear(self, merchant_id: Optional[str] = None) -> int: ...
