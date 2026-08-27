"""
Source: Day-4 Plan (rev. 2) Step 6 -- Scorer protocol and the four B3
sanity scorers. `Scorer: (Sample) -> float in [0,1]`. `RandomScorer` uses
`SubStream` (seeded, deterministic), never `random.random()` -- consistent
with the simulator's determinism discipline even though this module is
outside `packages/simulator` and floats are fine here (Decision 30
constrains the simulator's serialized stream, not eval code).
"""

from __future__ import annotations

from typing import Protocol

from eval.dataset import Sample
from packages.simulator.rng import SubStream


class Scorer(Protocol):
    def __call__(self, sample: Sample) -> float: ...


class PerfectScorer:
    """Scores exactly the truth label -- the analytic AUC=1.0/AP=1.0 sanity gate."""

    def __call__(self, sample: Sample) -> float:
        return 1.0 if sample.is_attack else 0.0


class RandomScorer:
    """Independent uniform score per call, seeded via SubStream -- the AUC~0.5/AP~pi sanity gate."""

    def __init__(self, seed: int):
        self._rng = SubStream(seed, "eval:scorers:random")

    def __call__(self, sample: Sample) -> float:
        return self._rng.getrandbits(32) / (2**32 - 1)


class InvertedScorer:
    """Scores the OPPOSITE of the truth label -- the only sign-error test (AUC=0.0)."""

    def __call__(self, sample: Sample) -> float:
        return 0.0 if sample.is_attack else 1.0


class AlwaysPositiveScorer:
    """Constant 1.0 regardless of input -- two operating points only, recall@FPR is unreachable."""

    def __call__(self, sample: Sample) -> float:
        return 1.0
