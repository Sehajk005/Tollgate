"""
Source: TRD v2 §4 -- a Clock is injected everywhere. Nothing in the codebase
calls time.time() / datetime.now() directly outside this package (asserted by
tests/acceptance/test_clock_discipline.py).
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    """Wall-clock time. Used in production."""

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class VirtualClock:
    """
    Deterministic virtual clock. Advances only via advance_ms()/set_ms(); never
    reads the wall clock. This is what makes 60x replay (Impl Plan Day 2) and
    seeded fixture generation reproducible, and is why the acceptance test
    'window expiry advances under VirtualClock with no wall time elapsed' is
    trivially true rather than merely approximately true.
    """

    def __init__(self, epoch_ms: int = 0) -> None:
        self._now_ms = epoch_ms

    def now_ms(self) -> int:
        return self._now_ms

    def advance_ms(self, delta_ms: int) -> None:
        if delta_ms < 0:
            raise ValueError("virtual clock cannot move backwards")
        self._now_ms += delta_ms

    def set_ms(self, value_ms: int) -> None:
        if value_ms < self._now_ms:
            raise ValueError("virtual clock cannot move backwards")
        self._now_ms = value_ms
