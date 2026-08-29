"""
Source: Day-5 Plan Step 4 -- the Layer-1 LightGBM detector wrapper (Impl Plan
Day 5 deliverable `detect/model.py -- LightGBM, pred_contrib=True`).

Placement note (Day-5 Plan §11/R3, Decision 28's precedent): `pyproject.toml`
installs only `packages*`/`services*`/`scripts*`/`eval*`, so a bare top-level
`detect/` package is not importable. This lives at `packages/detect/`.

`lightgbm` is imported LAZILY inside `load()` / `save()`, never at module
import, so `import packages.detect.model` never forces a compiled dependency
and `packages/detect/__init__.py` stays empty -- `rules.py`'s import closure
never sees lightgbm. This module imports NO ground-truth-label source
(the label table, `eval.dataset`, `eval.load`) -- enforced by
`tests/acceptance/test_detect_label_isolation.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence, Tuple

from packages.features.compute import FEATURE_NAMES

# Source: Day-5 Plan Step 4 -- one feature definition. The model orders its
# input by exactly the 24-name FEATURE_NAMES contract; it never keeps a second
# list.
FEATURE_ORDER: Tuple[str, ...] = tuple(FEATURE_NAMES)


@dataclass(frozen=True)
class ModelArtifact:
    model_version: str                       # "l1-lgbm-v1" -- must match eval/provenance.py:45
    feature_names: Tuple[str, ...]           # == FEATURE_ORDER
    params: Dict[str, object]                # LightGBM params VERBATIM, incl. scale_pos_weight + num_boost_round + defaults
    pi_t: float                              # training (calibration-slice) prevalence -- Eval Protocol §3.2
    best_iteration: int
    n_train: int
    n_train_pos: int
    excluded_features: Tuple[str, ...]       # from the discriminability audit, remedy (a)
    corpus: Dict[str, object]                # seed, config_hash, build_hash, n_runs, feature_set_version

    def to_dict(self) -> dict:
        return {
            "model_version": self.model_version,
            "feature_names": list(self.feature_names),
            "params": self.params,
            "pi_t": self.pi_t,
            "best_iteration": self.best_iteration,
            "n_train": self.n_train,
            "n_train_pos": self.n_train_pos,
            "excluded_features": list(self.excluded_features),
            "corpus": self.corpus,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ModelArtifact":
        return cls(
            model_version=raw["model_version"],
            feature_names=tuple(raw["feature_names"]),
            params=dict(raw["params"]),
            pi_t=float(raw["pi_t"]),
            best_iteration=int(raw["best_iteration"]),
            n_train=int(raw["n_train"]),
            n_train_pos=int(raw["n_train_pos"]),
            excluded_features=tuple(raw["excluded_features"]),
            corpus=dict(raw["corpus"]),
        )


class Layer1Model:
    """
    Serving wrapper around a trained LightGBM Booster + its ModelArtifact.
    `x` is always the 24 FEATURE_NAMES floats in order; excluded features are
    ZEROED on input (never dropped) so the vector width and pred_contrib's
    bias term stay aligned.
    """

    def __init__(self, booster, artifact: ModelArtifact) -> None:
        self._booster = booster
        self._artifact = artifact
        self._excluded = set(artifact.excluded_features)
        self._num_threads = int(artifact.params.get("num_threads", 1))
        # Serve exactly the trees the artifact records (train_l1 keeps all
        # num_boost_round trees when early stopping's metric is unresolvable).
        self._num_iteration = int(artifact.best_iteration) if artifact.best_iteration else None

    # -- identity ---------------------------------------------------------

    @property
    def artifact(self) -> ModelArtifact:
        return self._artifact

    @property
    def model_version(self) -> str:
        return self._artifact.model_version

    @property
    def feature_names(self) -> Tuple[str, ...]:
        return self._artifact.feature_names

    @property
    def excluded_features(self) -> Tuple[str, ...]:
        return self._artifact.excluded_features

    # -- projection -----------------------------------------------------

    def _project(self, x: Sequence[float]) -> list:
        if len(x) != len(FEATURE_ORDER):
            raise ValueError(
                f"Layer1Model expects {len(FEATURE_ORDER)} features in FEATURE_NAMES order, got {len(x)}"
            )
        return [
            0.0 if name in self._excluded else float(v)
            for name, v in zip(FEATURE_ORDER, x)
        ]

    # -- prediction ---------------------------------------------------

    def margin(self, x: Sequence[float]) -> float:
        """Booster.predict(raw_score=True) -- the logit, before Platt."""
        row = self._project(x)
        out = self._booster.predict(
            [row], raw_score=True, num_iteration=self._num_iteration, num_threads=self._num_threads
        )
        return float(out[0])

    def contributions(self, x: Sequence[float]) -> Tuple[float, ...]:
        """Booster.predict(pred_contrib=True) -- len 25 (24 features + bias),
        summing to the raw margin."""
        row = self._project(x)
        out = self._booster.predict(
            [row], pred_contrib=True, num_iteration=self._num_iteration, num_threads=self._num_threads
        )
        return tuple(float(v) for v in out[0])

    def score_one(self, x: Sequence[float]) -> Tuple[float, Tuple[float, ...]]:
        """The serving entry point: (margin, contributions)."""
        return self.margin(x), self.contributions(x)

    # -- persistence ------------------------------------------------

    def save(self, model_dir: Path) -> None:
        import lightgbm  # noqa: F401  -- lazy; a Booster instance implies it is importable

        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        self._booster.save_model(str(model_dir / f"{self._artifact.model_version}.txt"))
        (model_dir / f"{self._artifact.model_version}.json").write_text(
            json.dumps(self._artifact.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, model_dir: Path) -> "Layer1Model":
        import lightgbm as lgb  # lazy -- never at module import

        model_dir = Path(model_dir)
        candidates = sorted(model_dir.glob("l1-lgbm-v*.json"))
        if not candidates:
            raise FileNotFoundError(f"no l1-lgbm-v*.json model artifact under {model_dir}")
        artifact = ModelArtifact.from_dict(json.loads(candidates[-1].read_text(encoding="utf-8")))
        booster_path = model_dir / f"{artifact.model_version}.txt"
        if not booster_path.exists():
            raise FileNotFoundError(f"model artifact {candidates[-1].name} has no booster at {booster_path}")
        booster = lgb.Booster(model_file=str(booster_path))
        return cls(booster, artifact)


def artifact_exists(model_dir: Path) -> bool:
    """True iff `model_dir` holds a loadable l1-lgbm booster+artifact pair.
    Used by services/scorer/deps.py's guarded load."""
    model_dir = Path(model_dir)
    for js in model_dir.glob("l1-lgbm-v*.json"):
        try:
            version = json.loads(js.read_text(encoding="utf-8"))["model_version"]
        except Exception:  # noqa: BLE001
            continue
        if (model_dir / f"{version}.txt").exists():
            return True
    return False
