"""
Source: Day-2 Plan §L Step 8 -- "a pure function over a rolling window of
rule fires", documented as a Day-2 stand-in for Day 6's incident detector:
"no fire in the window -> calm; any R1 fire (or any throttle) -> elevated;
any R2/R3 fire (or any challenge) -> under_attack; decay back through
resolved -> calm."

Rolls on ingest_ms (event time) exclusively -- Day-2 Plan §L Step 8 failure
mode: "Rolling on wall time instead of ingest_ms (breaks A13)". No call
here ever reads a wall clock, so this module is covered (and passes)
tests/acceptance/test_clock_discipline.py's existing repo-wide AST scan
without needing any change to that Day-1 test.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

WINDOW_MS = 5 * 60_000  # matches R2/R3's 5-minute window (packages/detect/rules.py)
RESOLVED_AUTO_DISMISS_MS = 30_000  # UIUX v2 §2.1 -- "RESOLVED ... auto-dismiss 30 s"

CALM = "calm"
ELEVATED = "elevated"
UNDER_ATTACK = "under_attack"
RESOLVED = "resolved"

_ELEVATED_RULES = frozenset({"attempts_per_ip_60s"})
_UNDER_ATTACK_RULES = frozenset({"distinct_cards_per_ip_5m", "distinct_cards_per_bin_5m"})
_ELEVATED_DECISIONS = frozenset({"throttle"})
_UNDER_ATTACK_DECISIONS = frozenset({"challenge", "step_up", "block"})


def _severity(rules_fired: list, decision: str) -> int:
    rules = set(rules_fired or [])
    if rules & _UNDER_ATTACK_RULES or decision in _UNDER_ATTACK_DECISIONS:
        return 2
    if rules & _ELEVATED_RULES or decision in _ELEVATED_DECISIONS:
        return 1
    return 0


class ThreatRollup:
    """
    Stateful, per-merchant rollup on ScorerState. Not independently
    thread-safe -- Day 2 runs a single demo replay at a time, unlike
    InMemoryWindowStore which Day 1 already hardened for concurrent
    storefront traffic.
    """

    def __init__(self, window_ms: int = WINDOW_MS, resolved_dismiss_ms: int = RESOLVED_AUTO_DISMISS_MS) -> None:
        self._window_ms = window_ms
        self._resolved_dismiss_ms = resolved_dismiss_ms
        self._events: Deque[Tuple[int, int]] = deque()  # (ingest_ms, severity)
        self._state = CALM
        self._resolved_at_ms: Optional[int] = None

    def observe(self, *, rules_fired: list, decision: str, ingest_ms: int) -> str:
        severity = _severity(rules_fired, decision)
        self._events.append((ingest_ms, severity))
        floor = ingest_ms - self._window_ms
        while self._events and self._events[0][0] <= floor:
            self._events.popleft()

        peak = max((s for _, s in self._events), default=0)

        if peak >= 2:
            self._state = UNDER_ATTACK
            self._resolved_at_ms = None
        elif peak == 1:
            self._state = ELEVATED
            self._resolved_at_ms = None
        elif self._state in (ELEVATED, UNDER_ATTACK):
            self._state = RESOLVED
            self._resolved_at_ms = ingest_ms
        elif self._state == RESOLVED:
            if self._resolved_at_ms is not None and ingest_ms - self._resolved_at_ms >= self._resolved_dismiss_ms:
                self._state = CALM
                self._resolved_at_ms = None
        else:
            self._state = CALM

        return self._state

    def clear(self) -> None:
        """Source: Day-2 Plan Decision 36 -- Reset also clears the threat rollup."""
        self._events.clear()
        self._state = CALM
        self._resolved_at_ms = None
