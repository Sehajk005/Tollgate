"""
Source: v2.1 reconciliation, finding K11 -- attempt_uid is a server-minted
ULID-shaped identifier (Threat Model v2 §3) and must be minted from the
injected Clock, not wall time, or Day 2's byte-identical-stream-from-seed test
and Day 6's metamorphic M1 (shift all ingest times by delta -> identical
results) both break.
"""

from __future__ import annotations

import random

from packages.clock.clock import Clock

_ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32, no I L O U


def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ENCODING[rem])
    return "".join(reversed(chars))


class UlidGenerator:
    """
    Mints ULID-shaped identifiers (10 base32 chars of clock-derived timestamp +
    16 base32 chars of randomness) from an injected Clock rather than wall
    time, so identifiers -- and anything keyed by them -- are reproducible
    under VirtualClock-driven replay.
    """

    def __init__(self, clock: Clock, rng: "random.Random | None" = None) -> None:
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()

    def new(self) -> str:
        timestamp_ms = self._clock.now_ms()
        randomness = self._rng.getrandbits(80)
        return _encode_base32(timestamp_ms, 10) + _encode_base32(randomness, 16)
