"""
Source: Backend Schema v2 §4 -- tg:{m}:w:{space}:{key}:{metric}. Shared by
every WindowStore backend (in-memory today, Redis on Day 3) so the
merchant-scoping test (^tg:[^:]+:, fixing F16) applies from Day 1 onward.

Day-3 Plan Step 5/discrepancy note -- the documented pattern above omits
window width entirely. Day 1/2 never exposed this because every (space,
metric) combination R1-R3 uses is queried at exactly one width (ip/ev only
at 60s, ip/card and bin/card only at 5m). Day 3's compute.py queries
attempts_per_ip both at 60s AND 5m -- same space, same key, same metric,
different window_ms. Two logical windows sharing one physical sorted set
would destructively co-trim each other (whichever window's
ZREMRANGEBYSCORE runs first silently discards entries the other window
still needed), which is a correctness bug, not a style choice. window_ms
is therefore now part of the key. No locked test pins the previous
un-suffixed string (grep-verified), so this is a safe, purely additive
extension of an unspecified format detail.
"""

from __future__ import annotations

import re

MERCHANT_SCOPED_KEY_RE = re.compile(r"^tg:[^:]+:")


def window_key(merchant_id: str, space: str, key: str, metric: str, window_ms: int) -> str:
    return f"tg:{merchant_id}:w:{space}:{key}:{metric}:{window_ms}"


# ---------------------------------------------------------------------------
# Source: remediation plan FIX-003 -- the non-window keys, in ONE place.
#
# `RedisWindowStore` built these as inline f-strings while `InMemoryWindowStore`
# used bare `digest` / `event_id` / `card_hash` dict keys with no merchant in
# them at all. Two backends of one protocol had two different key spaces, which
# is why `clear(merchant_id)` could not be written honestly for the in-memory
# backend and why its `card24` / `eidr` counters silently pooled across
# merchants. Both backends now build every key here, so `merchant_prefix()`
# provably covers everything either of them owns -- which is what makes the
# scoped SCAN + UNLINK in `RedisWindowStore.clear()` complete rather than
# hopeful, and `MERCHANT_SCOPED_KEY_RE` true of every key, not just windows.
# ---------------------------------------------------------------------------


def merchant_prefix(merchant_id: str) -> str:
    """Every key Tollgate owns for `merchant_id` starts with this, and no key
    it does not own does. The basis of scoped deletion -- never `FLUSHDB`."""
    return f"tg:{merchant_id}:"


def idem_key(merchant_id: str, idem_digest: str, namespace: str = "") -> str:
    """`namespace` is the run scope (FIX-004): "" for storefront traffic, which
    keeps the key byte-identical to what shipped, and `r{run_id}:` for a replay
    so two runs of the same tier cannot collide."""
    return f"tg:{merchant_id}:idem:{namespace}{idem_digest}"


def eidr_key(merchant_id: str, event_id: str) -> str:
    return f"tg:{merchant_id}:eidr:{event_id}"


def card24_key(merchant_id: str, card_hash: str) -> str:
    return f"tg:{merchant_id}:card24:{card_hash}"


def cusum_key(merchant_id: str) -> str:
    return f"tg:{merchant_id}:cusum"


def shed_key(merchant_id: str, ip: str) -> str:
    return f"tg:{merchant_id}:shed:{ip}"
