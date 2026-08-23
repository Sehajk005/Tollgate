"""Builder-authored, advisory only (Impl Plan v2.1 section 1.8) -- not an
acceptance gate."""

from __future__ import annotations

import random

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator


def test_ulid_is_deterministic_given_seeded_rng_and_virtual_clock():
    clock = VirtualClock(epoch_ms=1000)
    gen = UlidGenerator(clock=clock, rng=random.Random(42))
    a = gen.new()

    clock2 = VirtualClock(epoch_ms=1000)
    gen2 = UlidGenerator(clock=clock2, rng=random.Random(42))
    b = gen2.new()

    assert a == b


def test_ulid_length_is_26_chars():
    gen = UlidGenerator(clock=VirtualClock(epoch_ms=0))
    assert len(gen.new()) == 26
