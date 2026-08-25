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
