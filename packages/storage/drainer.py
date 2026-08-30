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
"""

from __future__ import annotations

import json
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


class Drainer:
    def __init__(self, db_path: Path, spool_path: Path, poll_interval_s: float = 0.05) -> None:
        self._db_path = Path(db_path)
        self._spool_path = Path(spool_path)
        self._poll_interval_s = poll_interval_s
        self._offset = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def drain_once(self) -> int:
        if not self._spool_path.exists():
            return 0
        conn = connect(self._db_path)
        try:
            count = 0
            with open(self._spool_path, "r", encoding="utf-8", newline="\n") as fh:
                fh.seek(self._offset)
                while True:
                    raw_line = fh.readline()
                    if not raw_line:
                        break  # EOF
                    if not raw_line.endswith("\n"):
                        # Partial write in progress (writer mid-flush). Stop
                        # here and retry this same offset on the next poll --
                        # do NOT advance past an incomplete line.
                        break
                    line = raw_line.strip()
                    if line:
                        data = json.loads(line)
                        payload = data["payload"]
                        # Day-8 Plan Step 9 -- `attempt` / `score` are guarded
                        # so an out-of-band narrator payload (just a
                        # `narrator_call` row, no attempt) drains cleanly.
                        if "attempt" in payload:
                            insert_attempt(conn, AttemptRecord(**payload["attempt"]))
                        # Day-6 Plan §3.4 -- the incident row (and its
                        # entities) must land before attempt_score, whose
                        # incident_id is an FK onto incident.
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
                        # including failures. call_id is a PK (INSERT OR IGNORE)
                        # so byte-0 re-drain stays idempotent.
                        for call_row in payload.get("narrator_call", []):
                            insert_narrator_call(conn, call_row)
                        count += 1
                    self._offset = fh.tell()
            conn.commit()
        finally:
            conn.close()
        return count

    def drain_from_start(self) -> int:
        """
        Full drain from byte 0 -- called on service startup, before accepting
        traffic, so a crash that lost the in-memory offset still recovers
        everything. INSERT OR IGNORE makes this safe even when some rows
        were already committed before the process died.
        """
        self._offset = 0
        return self.drain_once()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.drain_once()
            time.sleep(self._poll_interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
