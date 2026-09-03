"""
Source: Backend Schema v2.1 §1 -- connection factory. `PRAGMA foreign_keys`
is per-connection in SQLite (not persisted in the database file), so it is
applied here on every connection, including read-only ones -- otherwise FK
enforcement would silently be off despite the schema declaring the
constraints.

Remediation plan FIX-010 (AUDIT-012). `journal_mode` is NOT per-connection:
WAL is a property recorded in the database file itself and survives every
reconnect. Re-issuing `PRAGMA journal_mode = WAL` on each new connection was
therefore pure cost -- and, at the drainer's 20 connections per second, it was
the pathological call the two recorded SIGSEGVs landed on. It is now set ONCE,
in `initialize_schema`. `synchronous` and `foreign_keys` genuinely are
per-connection and stay exactly where they were.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{Path(db_path).as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_schema(db_path: Path, schema_sql_path: Path) -> None:
    conn = connect(db_path)
    try:
        # Persisted in the database file -- set here, once, and every later
        # connection inherits it. Asserted by test_drainer_lifecycle.py.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(Path(schema_sql_path).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
