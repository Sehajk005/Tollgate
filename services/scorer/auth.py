"""
Source: Implementation Plan v2.1 Day 1 -- API-key authentication.
X-Tollgate-Key -> merchant_id via a stored hash lookup (Backend Schema v2
merchant.api_key_hash).
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Optional


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
