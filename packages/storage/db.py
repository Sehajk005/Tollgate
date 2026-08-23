"""
Source: Backend Schema v2.1 §1 -- connection factory. `PRAGMA foreign_keys`
is per-connection in SQLite (not persisted in the database file), so it is
applied here on every connection, including read-only ones -- otherwise FK
enforcement would silently be off despite the schema declaring the
constraints.
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
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_schema(db_path: Path, schema_sql_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(Path(schema_sql_path).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
