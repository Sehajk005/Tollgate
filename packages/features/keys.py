"""
Source: Backend Schema v2 §4 -- tg:{m}:w:{space}:{key}:{metric}. Shared by
every WindowStore backend (in-memory today, Redis on Day 3) so the
merchant-scoping test (^tg:[^:]+:, fixing F16) applies from Day 1 onward.
"""

from __future__ import annotations

import re

MERCHANT_SCOPED_KEY_RE = re.compile(r"^tg:[^:]+:")


def window_key(merchant_id: str, space: str, key: str, metric: str) -> str:
    return f"tg:{merchant_id}:w:{space}:{key}:{metric}"
