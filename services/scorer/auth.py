"""
Source: Implementation Plan v2.1 Day 1 -- API-key authentication.
X-Tollgate-Key -> merchant_id via a stored hash lookup (Backend Schema v2
merchant.api_key_hash).
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from services.scorer.deps import ScorerState


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def resolve_merchant_id(conn: sqlite3.Connection, raw_key: Optional[str]) -> Optional[str]:
    if not raw_key:
        return None
    key_hash = hash_api_key(raw_key)
    row = conn.execute(
        "SELECT merchant_id FROM merchant WHERE api_key_hash = ?", (key_hash,)
    ).fetchone()
    return row["merchant_id"] if row else None


class AuthBackendUnavailable(Exception):
    """Source: Day-7 Plan §4 Step 4 -- the merchant-lookup DB is unavailable
    (e.g. `sqlite3.OperationalError: database is locked`) AND the key hash is
    not in the warm cache. The route turns this into 503. Authentication NEVER
    fails open: allowing an unauthenticated request would be a larger hole
    than the one fail-open closes (Decision 89 / §12 trap 8)."""


def resolve_merchant_id_cached(state: "ScorerState", raw_key: Optional[str]) -> Optional[str]:
    """
    Source: Day-7 Plan §4 Step 4 -- API-key resolution with an in-process
    `{api_key_hash: merchant_id}` cache on `ScorerState`. A warm cache lets a
    locked DB still authenticate (so the request can then fail open,
    merchant-scoped); a COLD cache plus an unavailable DB raises
    `AuthBackendUnavailable` -> 503, never a bypass.
    """
    if not raw_key:
        return None
    key_hash = hash_api_key(raw_key)
    cached = state.api_key_cache.get(key_hash)
    if cached is not None:
        return cached
    try:
        conn = state.db_read_conn()
        try:
            row = conn.execute(
                "SELECT merchant_id FROM merchant WHERE api_key_hash = ?", (key_hash,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:  # locked / unavailable + cold cache
        raise AuthBackendUnavailable(str(exc)) from exc
    if row is None:
        return None
    merchant_id = row["merchant_id"]
    state.api_key_cache[key_hash] = merchant_id
    return merchant_id
