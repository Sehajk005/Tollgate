"""
Source: Day-4 Plan (rev. 2) Step 6 -- Scorer protocol and the four B3
sanity scorers. `Scorer: (Sample) -> float in [0,1]`. `RandomScorer` uses
`SubStream` (seeded, deterministic), never `random.random()` -- consistent
with the simulator's determinism discipline even though this module is
outside `packages/simulator` and floats are fine here (Decision 30
constrains the simulator's serialized stream, not eval code).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Protocol, Tuple

from eval.dataset import Sample
from packages.simulator.rng import SubStream

if TYPE_CHECKING:  # pragma: no cover -- annotations only; no runtime import of eval.corpus
    from eval.corpus import FeatureRow


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


# ---------------------------------------------------------------------------
# Source: Day-5 Plan Step 8 -- the Layer-1 model scorer and the real B0
# (live-rules) scorer. Both satisfy the existing Scorer protocol
# ((Sample) -> float) unchanged -- no protocol widening, no evaluate() change.
# Both read the Day-5 feature corpus by (run_index, event_id); a sample with
# no corpus row RAISES rather than silently scoring 0.0.
# ---------------------------------------------------------------------------


class Layer1Scorer:
    """
    `l1-lgbm-v1`. Holds a duck-typed predictor (packages.detect.model.Layer1Model
    -- only `.margin(x)` is called here), a calibrator
    (packages.detect.calibrate.Calibrator), and the
    (run_index, event_id) -> FeatureRow map from eval.corpus.load_feature_corpus.
    Imports no lightgbm: it receives an already-constructed predictor.
    """

    def __init__(
        self, predictor, calibrator, features: "Dict[Tuple[int, str], FeatureRow]", *, pi_s: float,
    ) -> None:
        self._predictor = predictor
        self._calibrator = calibrator
        self._features = features
        self._pi_s = pi_s

    def __call__(self, sample: Sample) -> float:
        key = (sample.run_index, sample.event_id)
        row = self._features.get(key)
        if row is None:
            raise KeyError(f"Layer1Scorer: no feature-corpus row for {key}")
        margin = self._predictor.margin(row.x)
        return self._calibrator.apply(margin, self._pi_s)


class B0RulesScorer:
    """
    B0 -- the LIVE Day-1 rules layer (R1+R2+R3), pre-auth, outcome-independent.
    Returns `attempt_score.score_raw` exactly as it was logged at decision time
    (FeatureRow.rule_score_raw). Never recomputed offline (Eval Protocol §8,
    Decision 6) -- honest by construction because it reads the decision-time score.
    """

    def __init__(self, features: "Dict[Tuple[int, str], FeatureRow]") -> None:
        self._features = features

    def __call__(self, sample: Sample) -> float:
        key = (sample.run_index, sample.event_id)
        row = self._features.get(key)
        if row is None:
            raise KeyError(f"B0RulesScorer: no feature-corpus row for {key}")
        return row.rule_score_raw
