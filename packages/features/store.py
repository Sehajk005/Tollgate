"""
Source: TRD v2 §6.3 -- Day 3's Redis backend must perform
write -> trim -> read vector -> CUSUM increment inside ONE Lua script (one
round trip per score call). This protocol is shaped as a single call for
exactly that reason: a split add()/read() protocol would force a redesign of
every caller on Day 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WindowRequest:
    merchant_id: str
    space: str
    key: str
    metric: str
    member: str
    ingest_ms: int
    window_ms: int


@dataclass(frozen=True)
class WindowSnapshot:
    count: int


class WindowStore(Protocol):
    def record_and_read(self, request: WindowRequest) -> WindowSnapshot: ...
