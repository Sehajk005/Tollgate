"""
Source: Day-2 Plan §F rng.py -- "seeded getrandbits + integer inverse-CDF
sampler; NO float, NO numpy" (Decision 30). Determinism is achieved by
eliminating floats from the serialized stream and using getrandbits only:
no random.random()/choice()/shuffle()/sample(), no numpy anywhere in this
module or its callers within packages.simulator.

SubStream derives an independent random.Random per (seed, label) pair, so
baseline and attack draw from disjoint sub-streams (Decision 31): changing
an attack parameter, or generating a different tier at the same seed, can
never perturb one byte of the baseline, because the baseline's sub-streams
are always labelled "baseline:*" -- never parameterized by tier.
"""

from __future__ import annotations

import bisect
import hashlib
import random


class SubStream:
    """A seeded, independently-derived random bit source for one (seed, label) pair."""

    def __init__(self, seed: int, label: str) -> None:
        digest = hashlib.sha256(f"{seed}:{label}".encode("ascii")).digest()
        derived_seed = int.from_bytes(digest[:8], "big")
        self._rng = random.Random(derived_seed)

    def getrandbits(self, k: int) -> int:
        return self._rng.getrandbits(k)

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) via rejection sampling over getrandbits."""
        if n <= 0:
            raise ValueError("n must be positive")
        if n == 1:
            return 0
        k = (n - 1).bit_length()
        while True:
            candidate = self._rng.getrandbits(k)
            if candidate < n:
                return candidate

    def pick_index(self, cumulative_weights: list) -> int:
        """
        Integer inverse-CDF sample. `cumulative_weights` is a non-decreasing
        list of positive ints (prefix sums); returns the smallest index i
        such that cumulative_weights[i] > r, for r uniform in
        [0, cumulative_weights[-1]).
        """
        total = cumulative_weights[-1]
        r = self.below(total)
        return bisect.bisect_right(cumulative_weights, r)


def cumulative_sum(weights: list) -> list:
    total = 0
    out = []
    for w in weights:
        total += w
        out.append(total)
    return out
