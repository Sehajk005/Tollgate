"""Builder-authored, advisory only (Impl Plan v2.1 section 1.8) -- not an
acceptance gate."""

from __future__ import annotations

import time

from packages.clock.stopwatch import Stopwatch


def test_elapsed_ms_increases():
    sw = Stopwatch()
    time.sleep(0.01)
    assert sw.elapsed_ms() >= 5
