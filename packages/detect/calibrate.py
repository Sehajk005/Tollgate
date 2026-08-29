"""
Source: Day-5 Plan Step 5 -- Platt calibration + explicit serving-prior
correction (Impl Plan Day 5 deliverable `detect/calibrate.py -- Platt + prior
correction`; Eval Protocol §3).

Model-agnostic by construction: `Calibrator.apply(margin, pi_s)` takes a raw
margin (the logit of whatever produced it -- a LightGBM `raw_score` margin on
the real path, `logit(rule_score)` on the pre-committed rules-only fallback,
Day-5 Plan §10) and returns a calibrated posterior at serving prior `pi_s`.

numpy only -- no scikit-learn (its default L2 penalty is a hyperparameter no
spec section fixes), no scipy. Isotonic is present because Eval Protocol §3.1
requires the comparison to be published, but it is off by default
(`config/features.yaml: calibration.isotonic_enabled`).

This module is imported lazily by services/scorer/deps.py only when a
models/ artifact is present, so importing it -- and numpy -- is never forced
on the rules-only serving path.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

# Source: Day-5 Plan Step 5 -- inputs clamped to [EPS, 1-EPS] so logit() is
# finite and prior_correct()'s output lies strictly in (0, 1).
EPS = 1e-6


def _clip01(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


def logit(p: float) -> float:
    q = _clip01(p)
    return math.log(q / (1.0 - q))


def sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


# ---------------------------------------------------------------------------
# Platt
# ---------------------------------------------------------------------------


def fit_platt(
    margins: Sequence[float], labels: Sequence[bool], *, max_iter: int = 100, tol: float = 1e-12,
) -> Tuple[float, float]:
    """
    Two-parameter sigmoid MLE `p = sigmoid(a*margin + b)` -- the canonical
    Platt scaling of Lin, Lin & Weng (2007), "A Note on Platt's Probabilistic
    Outputs for SVMs": Newton with a damped line search, MLE on the
    Bayes-smoothed targets t_+ = (N_+ + 1)/(N_+ + 2), t_- = 1/(N_- + 2). The
    smoothing regularises the fit on a small held-out `calib` slice without
    an L2 penalty on (a, b) (which is what sklearn adds by default and which
    no spec section fixes). A non-positive or non-finite `a` fails the fit
    and raises rather than shipping an inverted calibrator (Day-5 Plan §5).
    """
    m = np.asarray(margins, dtype=np.float64)
    y = np.asarray([1.0 if v else 0.0 for v in labels], dtype=np.float64)
    if m.size == 0 or m.size != y.size:
        raise ValueError("fit_platt: margins and labels must be non-empty and equal length")
    if y.min() == y.max():
        raise ValueError("fit_platt: labels are single-class -- cannot fit a calibrator")

    n_pos = float(y.sum())
    n_neg = float(y.size - n_pos)
    hi = (n_pos + 1.0) / (n_pos + 2.0)
    lo = 1.0 / (n_neg + 2.0)
    t = np.where(y > 0.5, hi, lo)

    a, b = 0.0, math.log((n_neg + 1.0) / (n_pos + 1.0))  # Lin et al. initial guess

    def _nll(a_, b_):
        z = a_ * m + b_
        # -[t log sigma(z) + (1-t) log(1-sigma(z))] = log(1 + e^z) - t z, stable form
        log1pe = np.where(z >= 0, z + np.log1p(np.exp(-z)), np.log1p(np.exp(z)))
        return float(np.sum(log1pe - t * z))

    cur = _nll(a, b)
    for _ in range(max_iter):
        z = a * m + b
        p = np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))
        w = np.clip(p * (1.0 - p), 1e-12, None)
        d = p - t
        h11 = float(np.sum(m * m * w)) + 1e-12
        h22 = float(np.sum(w)) + 1e-12
        h21 = float(np.sum(m * w))
        g1 = float(np.sum(m * d))
        g2 = float(np.sum(d))
        det = h11 * h22 - h21 * h21
        if abs(det) < 1e-300:
            break
        da = -(h22 * g1 - h21 * g2) / det
        db = -(-h21 * g1 + h11 * g2) / det
        gd = g1 * da + g2 * db
        step = 1.0
        while step >= 1e-10:
            new = _nll(a + step * da, b + step * db)
            if new < cur + 1e-4 * step * gd:
                a, b, cur = a + step * da, b + step * db, new
                break
            step *= 0.5
        if abs(da) < tol and abs(db) < tol:
            break

    a, b = float(a), float(b)
    if not (math.isfinite(a) and math.isfinite(b)) or a <= 0.0:
        raise ValueError(
            f"fit_platt produced a non-monotone / non-finite calibrator (a={a}, b={b}); "
            "aborting rather than shipping an inverted calibrator"
        )
    return a, b


# ---------------------------------------------------------------------------
# Isotonic (PAV) -- published for comparison, off by default
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IsotonicStep:
    """A non-decreasing piecewise-constant map, PAV-fitted. `x` are the sorted
    predictor breakpoints, `y` the pooled non-decreasing values."""

    x: Tuple[float, ...]
    y: Tuple[float, ...]

    def predict(self, p: float) -> float:
        if not self.x:
            return _clip01(p)
        if p <= self.x[0]:
            return self.y[0]
        if p >= self.x[-1]:
            return self.y[-1]
        lo, hi = 0, len(self.x) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.x[mid] <= p:
                lo = mid
            else:
                hi = mid - 1
        return self.y[lo]


def fit_isotonic(p: Sequence[float], labels: Sequence[bool]) -> IsotonicStep:
    """Pool-adjacent-violators isotonic regression of `labels` on `p`."""
    pts = sorted(
        zip((float(v) for v in p), (1.0 if v else 0.0 for v in labels)), key=lambda t: t[0]
    )
    if not pts:
        return IsotonicStep(x=(), y=())
    xs = [t[0] for t in pts]
    ys = [t[1] for t in pts]
    blocks: List[List[float]] = []  # [weight, value]
    for v in ys:
        blocks.append([1.0, v])
        while len(blocks) >= 2 and blocks[-2][1] > blocks[-1][1]:
            w2, v2 = blocks.pop()
            w1, v1 = blocks.pop()
            w = w1 + w2
            blocks.append([w, (w1 * v1 + w2 * v2) / w])
    fitted: List[float] = []
    for w, v in blocks:
        fitted.extend([v] * int(w))
    return IsotonicStep(x=tuple(xs), y=tuple(fitted))


# ---------------------------------------------------------------------------
# Serving prior + prior correction (Eval Protocol §3.2, §3.3)
# ---------------------------------------------------------------------------


def prior_correct(p_train: float, pi_t: float, pi_s: float) -> float:
    """
    Eval Protocol §3.2, exactly:
        logit(p_serve) = logit(p_train) + ln(pi_s/(1-pi_s)) - ln(pi_t/(1-pi_t))
    Inputs clamped to [EPS, 1-EPS] so the output lies in (0, 1) by construction.
    """
    z = logit(p_train) + logit(pi_s) - logit(pi_t)
    return sigmoid(z)


def serving_prior(regime: str, cost_model, *, rate_ratio: Optional[float] = None) -> float:
    """
    Eval Protocol §3.3:
      in_control -> pi_0 (prior_steady_state) from config.
      alarm      -> the alarm's implied prevalence from its rate ratio, CLAMPED
                    to [pi_0, 0.95]. Day 5 only ever calls this with
                    "in_control" from the live path; the alarm branch is
                    implemented and unit-tested but UNWIRED -- CUSUM is Day 6
                    (Decision 45), which owns the exact rate_ratio -> prior map.
                    Day-5 placeholder: attack odds = rate_ratio x steady-state odds.
    """
    pi_0 = float(cost_model.prior_steady_state)
    if regime == "in_control":
        return pi_0
    if regime == "alarm":
        if rate_ratio is None:
            raise ValueError("serving_prior('alarm', ...) requires rate_ratio")
        odds_0 = pi_0 / (1.0 - pi_0)
        odds_s = max(rate_ratio, 0.0) * odds_0
        pi_s = odds_s / (1.0 + odds_s)
        return min(max(pi_s, pi_0), 0.95)
    raise ValueError(f"serving_prior: unknown regime {regime!r}")


# ---------------------------------------------------------------------------
# Calibrator artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Calibrator:
    calibrator_version: str        # "platt-v1"
    method: str                    # "platt"
    a: float
    b: float
    pi_t: float                    # prevalence of the slice Platt was fit on
    n_fit: int
    ece_bins: int

    def apply(self, margin: float, pi_s: float) -> float:
        """Platt, then prior correction (Eval Protocol §3.1 -> §3.2)."""
        p_train = sigmoid(self.a * float(margin) + self.b)
        return prior_correct(p_train, self.pi_t, pi_s)

    def to_dict(self) -> dict:
        return {
            "calibrator_version": self.calibrator_version, "method": self.method,
            "a": self.a, "b": self.b, "pi_t": self.pi_t, "n_fit": self.n_fit,
            "ece_bins": self.ece_bins,
        }

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "Calibrator":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            calibrator_version=raw["calibrator_version"], method=raw["method"],
            a=float(raw["a"]), b=float(raw["b"]), pi_t=float(raw["pi_t"]),
            n_fit=int(raw["n_fit"]), ece_bins=int(raw["ece_bins"]),
        )
