"""
Source: Backend Schema v2.1 section 1 -- spool-always (decisions.md, decision 7).

Every accepted attempt is appended here with a single write() before the
response returns -- always, not only after a flush failure. Durability
boundary is process death, not power loss (decision 9): flush() hands the
bytes to the OS, which is enough to survive a hard kill, but no fsync is
performed and none is required.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class SpooledAttempt:
    attempt_uid: str
    payload: dict


class Spool:
    def __init__(self, directory: Path, segment_name: str = "attempts-active.jsonl") -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path = self._directory / segment_name
        self._lock = threading.Lock()
        self._fh = open(self._path, "a", encoding="utf-8", newline="\n")

    @property
    def path(self) -> Path:
        return self._path

    def append(self, attempt_uid: str, payload: dict) -> None:
        line = json.dumps({"attempt_uid": attempt_uid, "payload": payload})
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()


def read_all(path: Path) -> List[SpooledAttempt]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(SpooledAttempt(attempt_uid=data["attempt_uid"], payload=data["payload"]))
    return records
