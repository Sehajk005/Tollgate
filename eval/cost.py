"""
Source: Day-4 Plan (rev. 2) Step 1 -- Eval Protocol v2 §1.2-1.4's cost
model: theta_T = C_FP(T) / (C_FP(T) + C_FN); C_FN = auth_fee_minor +
downstream_exposure_minor; C_FP(T) = aov_minor * margin_pct *
P(abandon|T). All money values are integer minor currency units (paise),
matching store_profile.yaml / Decision 30's "no floats in the serialized
stream" discipline extended to cost arithmetic wherever the inputs are
integers.

`roc_convex_hull` + `min_cost_operating_point` replace a theta-indexed cost
curve (rev. 1's F8/F9 bug): expected cost is piecewise-linear over
achievable (FPR, TPR) operating points, so its minimum sits at a convex-hull
vertex. Minimising over vertices is exact; a uniform theta grid is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COST_MODEL_PATH = REPO_ROOT / "config" / "cost_model.yaml"

# Source: Day-4 Plan Step 1 -- the four auto-ceiling-relevant tiers, in
# ladder order. Matches packages/contracts/decision.py's Decision enum
# order (ALLOW, MONITOR carry no configured abandonment cost and are not
# part of the cost ladder).
TIER_ORDER: Tuple[str, ...] = ("throttle", "challenge", "step_up", "block")


def _leaf_value(node) -> float:
    if isinstance(node, dict):
        return node["value"]
    return node


@dataclass(frozen=True)
class CostModel:
    auth_fee_minor: int
    downstream_exposure_minor: int
    aov_minor: int
    margin_pct: float
    abandonment_by_tier: Dict[str, float]
    prior_steady_state: float
    prior_under_attack: float
    eval_prevalence: float
    target_fpr: float

    def c_fn_minor(self) -> float:
        return self.auth_fee_minor + self.downstream_exposure_minor

    def c_fp_minor(self, tier: str) -> float:
        return self.aov_minor * self.margin_pct * self.abandonment_by_tier[tier]

    def tier_ladder(self) -> Dict[str, float]:
        """theta_T per tier, UNROUNDED -- callers round for display, never for comparison."""
        c_fn = self.c_fn_minor()
        return {
            tier: self.c_fp_minor(tier) / (self.c_fp_minor(tier) + c_fn)
            for tier in TIER_ORDER
        }

    def expected_cost_per_10k(self, tpr: float, fpr: float, pi: float, tier: str) -> float:
        """
        Source: Day-4 Plan Step 1 -- expected cost per 10,000 attempts at
        one (FPR, TPR) operating point, at declared prevalence `pi`, using
        tier `tier`'s abandonment-implied C_FP:
            10_000 * (pi * (1 - TPR) * C_FN + (1 - pi) * FPR * C_FP(tier))
        """
        c_fn = self.c_fn_minor()
        c_fp = self.c_fp_minor(tier)
        return 10_000 * (pi * (1 - tpr) * c_fn + (1 - pi) * fpr * c_fp)

    def min_cost_operating_point(
        self, hull: List[Tuple[float, float]], pi: float, tier: str
    ) -> Tuple[Optional[Tuple[float, float]], Optional[float]]:
        """
        Source: Day-4 Plan Step 1 -- expected cost is piecewise-linear over
        achievable operating points, so its minimum sits at a hull vertex.
        Returns ((fpr, tpr), cost) of the minimising vertex, or (None,
        None) for an empty hull.
        """
        best_point: Optional[Tuple[float, float]] = None
        best_cost: Optional[float] = None
        for fpr, tpr in hull:
            cost = self.expected_cost_per_10k(tpr, fpr, pi, tier)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_point = (fpr, tpr)
        return best_point, best_cost


def load_cost_model(path: Path = DEFAULT_COST_MODEL_PATH) -> CostModel:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    abandonment = {
        tier: _leaf_value(leaf) for tier, leaf in raw["abandonment_by_tier"].items()
    }
    return CostModel(
        auth_fee_minor=int(_leaf_value(raw["auth_fee_minor"])),
        downstream_exposure_minor=int(_leaf_value(raw["downstream_exposure_minor"])),
        aov_minor=int(_leaf_value(raw["aov_minor"])),
        margin_pct=float(_leaf_value(raw["margin_pct"])),
        abandonment_by_tier=abandonment,
        prior_steady_state=float(_leaf_value(raw["prior_steady_state"])),
        prior_under_attack=float(_leaf_value(raw["prior_under_attack"])),
        eval_prevalence=float(_leaf_value(raw["eval_prevalence"])),
        target_fpr=float(_leaf_value(raw["target_fpr"])),
    )


def _cross(o: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def roc_convex_hull(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Source: Day-4 Plan Step 1 -- the ROC convex hull's upper-left envelope:
    for each FPR, the maximum achievable TPR under linear interpolation
    between operating points (mixing two classifiers/thresholds via a
    randomized decision achieves any point on the segment between them).
    (0, 0) and (1, 1) are always achievable (the trivial always-negative /
    always-positive classifiers) and are added if absent. Returns the
    envelope as a list of (fpr, tpr) sorted ascending by fpr, deduplicated.

    Standard monotone-chain convex hull (Andrew's algorithm); the "upper"
    half (points visited right-to-left, reversed) is exactly the maximum-y
    boundary for each x, i.e. the ROC-dominant frontier.
    """
    pts = set(points)
    pts.add((0.0, 0.0))
    pts.add((1.0, 1.0))
    sorted_pts = sorted(pts)
    if len(sorted_pts) <= 2:
        return sorted_pts

    upper: List[Tuple[float, float]] = []
    for p in reversed(sorted_pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    upper.reverse()
    return upper
