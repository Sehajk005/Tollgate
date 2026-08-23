"""
The one permitted site for wall-clock DURATION measurement outside Clock's own
internals (K10 in the Day 1 plan). Request latency must not be measured with
the injected Clock, because a VirtualClock running at 60x would report
wildly wrong latencies. time.perf_counter_ns() is monotonic and epoch-less --
not a wall-clock instant -- so it is not banned by the clock-discipline test,
but duration measurement is still centralized here by convention so there is
exactly one place to look.
"""

from __future__ import annotations

import time


class Stopwatch:
    def __init__(self) -> None:
        self._start_ns = time.perf_counter_ns()

    def elapsed_ms(self) -> int:
        return (time.perf_counter_ns() - self._start_ns) // 1_000_000
