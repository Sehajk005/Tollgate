"""
Source: Backend Schema v2.1 section 1 -- background drainer: spool -> SQLite,
one transaction per batch. Idempotent via INSERT OR IGNORE on the ULID
primary key, so restarting mid-drain and re-draining from byte 0 is always
safe.

Implementation note (decisions.md addendum): the spec text describes moving
the spool segment aside once a batch commits. This implementation
deliberately does NOT rename or clear the active segment while the writer
may still hold it open -- renaming an open file has unreliable semantics on
Windows (no FILE_SHARE_DELETE by default), and that step is not required for
the durability guarantee: INSERT OR IGNORE already makes re-draining from
byte 0 on every restart safe and correct, at the cost of an unbounded (but
Day-1-scale-trivial) spool file. Segment housekeeping is left as explicit
future work rather than taking on a real cross-platform file-handle risk for
a Day 1 walking skeleton.

Remediation plan FIX-010 (AUDIT-012, + F-F) -- CONNECTION LIFECYCLE AND
SUPERVISION. The audit recorded two hard crashes (SIGSEGV) in this thread. The
contributing design was that `_run` polled at 50 ms and `drain_once` opened a
BRAND NEW SQLite connection and re-issued `PRAGMA journal_mode = WAL` on it --
20 connections and 20 journal-mode switches per second, forever, whether or not
there was anything to drain. Three changes:

  * ONE long-lived connection, created inside `_run` and used only there, so
    sqlite3's `check_same_thread` guard is satisfied by construction;
  * `journal_mode` is set ONCE, at `initialize_schema` -- WAL is persisted in
    the database file, unlike `foreign_keys`/`synchronous`, which genuinely are
    per-connection and stay so;
  * the poll does nothing at all when the spool has not grown, and backs off
    from 50 ms to 250 ms when idle.

And F-F: `_run` had no `try/except`, so a single `sqlite3.OperationalError`
ended persistence silently for the life of the process -- the same shape of
silent failure as AUDIT-007, in a different thread. The loop body is now
wrapped, failures are logged with a traceback and counted, and `is_alive()`
lets `/healthz` report the thread's state instead of everyone assuming it.

HONEST LIMIT, stated here and in the plan: no unit test can prove the absence
of a SIGSEGV. The gate for that is statistical -- §17's repeated-run matrix,
executed both with and without `TOLLGATE_FAULTHANDLER`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.storage.db import connect
from packages.storage.repository import (
    insert_attempt,
    insert_enforcement_action,
    insert_narrator_call,
    insert_score,
    insert_tier_transition,
    upsert_incident,
    upsert_incident_entity,
)

logger = logging.getLogger("tollgate.storage.drainer")

# Hot after a productive drain, relaxed when the spool is quiet. The hot
# interval is Day 1's; the idle one removes ~80% of the wakeups at rest without
# moving the latency the durability tests measure.
POLL_HOT_S = 0.05
POLL_IDLE_S = 0.25
# Escalate from WARNING to ERROR once failures stop looking transient.
CONSECUTIVE_FAILURE_ALERT = 10
HEARTBEAT_INTERVAL_S = 10.0


class Drainer:
    def __init__(self, db_path: Path, spool_path: Path, poll_interval_s: float = POLL_HOT_S) -> None:
        self._db_path = Path(db_path)
        self._spool_path = Path(spool_path)
        self._poll_interval_s = poll_interval_s
        self._offset = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Observability the audit had none of.
        self.connect_calls = 0
        self.rows_drained = 0
        self.consecutive_failures = 0

    # -- connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.connect_calls += 1
        return connect(self._db_path)

    def _spool_has_grown(self) -> bool:
        """Source: remediation plan §12. When the spool has not grown there is
        nothing to do, and doing nothing must cost nothing: no `exists()`, no
        `open()`, and above all no new connection. The second recorded SIGSEGV
        landed in exactly the machinery this skips."""
        try:
            return self._spool_path.stat().st_size > self._offset
        except OSError:
            return False

    # -- draining --------------------------------------------------------

    def _drain_with(self, conn: sqlite3.Connection) -> int:
        """The parsing/insert loop, byte-for-byte Day 1's, against a connection
        the CALLER owns. Splitting ownership out is what allows one long-lived
        connection on the thread and a separate short-lived one on the main
        thread, without either guessing about the other."""
        count = 0
        with open(self._spool_path, "r", encoding="utf-8", newline="\n") as fh:
            fh.seek(self._offset)
            while True:
                raw_line = fh.readline()
                if not raw_line:
                    break  # EOF
                if not raw_line.endswith("\n"):
                    # Partial write in progress (writer mid-flush). Stop here
                    # and retry this same offset on the next poll -- do NOT
                    # advance past an incomplete line. This is also why a
                    # cancelled replay cannot corrupt the spool: Spool.append
                    # writes one locked line + flush, so a torn line is simply
                    # re-read next time.
                    break
                line = raw_line.strip()
                if line:
                    data = json.loads(line)
                    payload = data["payload"]
                    # Day-8 Plan Step 9 -- `attempt` / `score` are guarded so an
                    # out-of-band narrator payload (just a `narrator_call` row,
                    # no attempt) drains cleanly.
                    if "attempt" in payload:
                        insert_attempt(conn, AttemptRecord(**payload["attempt"]))
                    # Day-6 Plan §3.4 -- the incident row (and its entities)
                    # must land before attempt_score, whose incident_id is an FK
                    # onto incident.
                    if "incident" in payload:
                        upsert_incident(conn, payload["incident"])
                        for entity_row in payload.get("incident_entity", []):
                            upsert_incident_entity(conn, entity_row)
                    if "score" in payload:
                        insert_score(conn, ScoreRecord(**payload["score"]))
                    if "incident" in payload:
                        for transition_row in payload.get("tier_transition", []):
                            insert_tier_transition(conn, transition_row)
                        for action_row in payload.get("enforcement", []):
                            insert_enforcement_action(conn, action_row)
                    # Day-8 Plan Step 9 -- one row per narration attempt,
                    # including failures. call_id is a PK (INSERT OR IGNORE) so
                    # byte-0 re-drain stays idempotent.
                    for call_row in payload.get("narrator_call", []):
                        insert_narrator_call(conn, call_row)
                    count += 1
                self._offset = fh.tell()
        conn.commit()
        self.rows_drained += count
        return count

    def drain_once(self) -> int:
        """One drain against a connection of its own. Retained with its original
        signature for the main-thread callers (startup, shutdown, tests); the
        drainer THREAD uses `_drain_with` on its own long-lived connection."""
        if not self._spool_path.exists():
            return 0
        conn = self._connect()
        try:
            return self._drain_with(conn)
        finally:
            conn.close()

    def drain_from_start(self) -> int:
        """
        Full drain from byte 0 -- called on service startup, before accepting
        traffic, so a crash that lost the in-memory offset still recovers
        everything. INSERT OR IGNORE makes this safe even when some rows
        were already committed before the process died.
        """
        self._offset = 0
        return self.drain_once()

    # -- the thread ------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tollgate-drainer", daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        """So `/healthz` can report the truth instead of everyone assuming it.
        Before this, a dead drainer was indistinguishable from an idle one and
        persistence simply stopped (F-F)."""
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # Created HERE, inside the thread that uses it: sqlite3's default
        # check_same_thread=True is then satisfied by construction rather than
        # by convention (asserted by test_drainer_lifecycle.py).
        conn: Optional[sqlite3.Connection] = None
        last_heartbeat = time.monotonic()
        interval = POLL_HOT_S
        try:
            while not self._stop.is_set():
                try:
                    if self._spool_has_grown():
                        if conn is None:
                            conn = self._connect()
                        drained = self._drain_with(conn)
                        interval = POLL_HOT_S if drained else POLL_IDLE_S
                    else:
                        interval = POLL_IDLE_S
                    self.consecutive_failures = 0
                except Exception:  # noqa: BLE001 -- F-F: the thread must SURVIVE
                    self.consecutive_failures += 1
                    level = (
                        logging.ERROR
                        if self.consecutive_failures >= CONSECUTIVE_FAILURE_ALERT
                        else logging.WARNING
                    )
                    logger.log(
                        level,
                        "drainer: drain failed (%d consecutive); the thread stays alive "
                        "and will retry from offset %d",
                        self.consecutive_failures, self._offset, exc_info=True,
                    )
                    # A failed drain may have left the connection unusable.
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:  # noqa: BLE001
                            pass
                        conn = None
                    interval = POLL_IDLE_S

                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    last_heartbeat = now
                    logger.info(
                        "drainer heartbeat: %d rows drained, %d connect() calls, "
                        "%d consecutive failures, offset %d",
                        self.rows_drained, self.connect_calls,
                        self.consecutive_failures, self._offset,
                    )
                self._stop.wait(interval)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
