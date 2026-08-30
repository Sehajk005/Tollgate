"""
Source: Day-8 Plan Step 4 (G10 / G11) -- the committed D6 evaluation
artifact. ONE machine-readable JSON file carrying all six D6 blocks plus
provenance, so `services/dashboard/src/screens/D6Metrics.jsx` does ZERO
runtime computation (App Flow v2 SS5 D6: "Static render. No live computation
on stage.").

This is a SERIALISER over the `HarnessRun` object `eval.harness.run_all()`
already returns -- the evaluation harness is NOT redesigned. Blocks 1, 2, 3,
5, 6 are already computed; this module reads them off the same objects
`eval/report.py` formats. The only genuinely new arithmetic is block 4's
three cost quantities (F1-optimal point, rupee gap, regime-switch saving),
built from `eval.cost` unchanged -- see `_block4_cost`.

The rupee-gap definition is pinned here and recorded in Decisions.md (Day 8):
    rupee_gap_minor = cost(F1-optimal, pi0) - cost(cost-optimal, pi0)
at pi0 (steady state), tier `challenge`, in integer minor units, with the
four inputs (`c_fn_minor`, `c_fp_minor("challenge")`, and both optimal
points' (fpr, tpr)) emitted alongside so the gap is hand-checkable from the
artifact alone (Eval Protocol v2 SS1.4 -- an undefined headline number is the
exact failure mode that section exists to prevent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from eval.cost import load_cost_model

SCHEMA_VERSION = 1
COST_TIER = "challenge"  # the auto-ceiling tier (matches eval.harness.COST_TIER)
RIBBON_PIS: Tuple[float, ...] = (1e-4, 1e-3, 1e-2)  # Eval Protocol v2 SS1.4

_MODEL_ROW_VERSIONS = ("l1-lgbm-v1", "rules-only-v0")


# --------------------------------------------------------------------------
# small serialisers
# --------------------------------------------------------------------------


def _tm_json(tm) -> Optional[dict]:
    """A TierMetrics -> dict, reusing eval.load's serialiser."""
    from eval.load import _tier_metrics_json

    return _tier_metrics_json(tm)


def _op_json(p) -> Optional[dict]:
    if p is None:
        return None
    return {
        "fpr": p.fpr, "tpr": p.tpr, "precision": p.precision, "recall": p.recall,
        "tp": p.tp, "fp": p.fp, "tn": p.tn, "fn": p.fn,
    }


def _temporal_reports(run) -> Dict[str, "object"]:
    """model_version -> Report on the temporal_test split."""
    name = next((n for n in run.eval_reports if n.startswith("temporal_test")), None)
    out: Dict[str, object] = {}
    if name is None:
        return out
    for report in run.eval_reports[name]:
        out[report.provenance.model_version] = report
    return out


def _tier_e_reports(run) -> Dict[str, "object"]:
    return {r.provenance.model_version: r for r in run.eval_reports.get("tier_e", [])}


# --------------------------------------------------------------------------
# block 4 -- the only new arithmetic
# --------------------------------------------------------------------------


def _precision(fpr: float, tpr: float, pi: float) -> float:
    denom = pi * tpr + (1.0 - pi) * fpr
    return (pi * tpr / denom) if denom > 0 else 0.0


def _f1(fpr: float, tpr: float, pi: float) -> float:
    p = _precision(fpr, tpr, pi)
    r = tpr
    return (2.0 * p * r / (p + r)) if (p + r) > 0 else 0.0


def _curve(hull_points: Sequence[Tuple[float, float]], cost_model, pi: float) -> List[list]:
    return [
        [fpr, tpr, cost_model.expected_cost_per_10k(tpr, fpr, pi, COST_TIER)]
        for fpr, tpr in hull_points
    ]


def _argmin_cost(curve_pi0: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    """First-wins argmin over a `[fpr, tpr, cost]` curve -- byte-identical to
    `CostModel.min_cost_operating_point`'s `cost < best_cost` scan over the
    same hull, and to the recompute in test_d6_cost_gap.py."""
    best_fpr = best_tpr = best_cost = None
    for fpr, tpr, cost in curve_pi0:
        if best_cost is None or cost < best_cost:
            best_fpr, best_tpr, best_cost = fpr, tpr, cost
    return best_fpr, best_tpr, best_cost


def _argmax_f1(curve_pi0: Sequence[Sequence[float]], pi0: float) -> Tuple[float, float, float]:
    """First-wins argmax of f1 over the same `[fpr, tpr, cost]` curve."""
    best_fpr = best_tpr = None
    best_f1 = None
    for fpr, tpr, _cost in curve_pi0:
        v = _f1(fpr, tpr, pi0)
        if best_f1 is None or v > best_f1:
            best_fpr, best_tpr, best_f1 = fpr, tpr, v
    return best_fpr, best_tpr, best_f1


def _block4_cost(run) -> dict:
    """Curves at both regimes, both optima, the sensitivity ribbon, the rupee
    gap and the regime-switch saving -- all from `eval.cost` unchanged, reusing
    the ROC convex hull `evaluate()` already put on the Report."""
    cost_model = load_cost_model()
    pi0 = cost_model.prior_steady_state
    pi1 = cost_model.prior_under_attack

    reports = _temporal_reports(run)
    series = None
    substitution = None
    for mv in ("l1-lgbm-v1", "rules-only-v0"):
        if mv in reports:
            series = mv
            if mv != "l1-lgbm-v1":
                substitution = (
                    "l1-lgbm-v1 report not available in this run; the B0 live-rules "
                    "series (rules-only-v0) is substituted and the curve reads B0's hull."
                )
            break
    if series is None:
        raise SystemExit(
            "eval/d6.py: no l1-lgbm-v1 or rules-only-v0 report on temporal_test -- "
            "run `python -m eval.harness --corpus-db <db> --model-dir <dir>`"
        )

    report = reports[series]
    # `report.cost_points_pi0` IS `[(fpr, tpr, cost) for (fpr,tpr) in roc_convex_hull(...)]`
    # -- exactly the hull evaluate() already built. Do not re-derive it.
    hull_points = [(fpr, tpr) for fpr, tpr, _cost in report.cost_points_pi0]
    curve_pi0 = [list(pt) for pt in report.cost_points_pi0]
    curve_pi1 = [list(pt) for pt in report.cost_points_pi1]

    co_fpr, co_tpr, co_cost0 = _argmin_cost(curve_pi0)
    f1_fpr, f1_tpr, f1_val = _argmax_f1(curve_pi0, pi0)
    f1_cost0 = cost_model.expected_cost_per_10k(f1_tpr, f1_fpr, pi0, COST_TIER)
    rupee_gap_minor = f1_cost0 - co_cost0  # >= 0 by construction (cost-optimal is the min)

    # regime-switch saving: the cost at pi1 of staying on the pi0-optimal point,
    # minus the cost at pi1 of moving to the pi1-optimal point.
    c1_fpr, c1_tpr, c1_cost1 = _argmin_cost(curve_pi1)
    stay_cost1 = cost_model.expected_cost_per_10k(co_tpr, co_fpr, pi1, COST_TIER)
    regime_switch_saving_minor = stay_cost1 - c1_cost1  # >= 0 (pi1-optimal is the min at pi1)

    ribbon = [
        {"pi": pi, "curve": _curve(hull_points, cost_model, pi)}
        for pi in RIBBON_PIS
    ]

    return {
        "tier": COST_TIER,
        "series": series,
        "series_substitution": substitution,
        "split": report.split_name,
        "pi0": pi0,
        "pi1": pi1,
        "curve_pi0": curve_pi0,
        "curve_pi1": curve_pi1,
        "ribbon": ribbon,
        "ribbon_pis": list(RIBBON_PIS),
        "f1_optimal": {"fpr": f1_fpr, "tpr": f1_tpr, "f1": f1_val, "cost_pi0": f1_cost0},
        "cost_optimal": {"fpr": co_fpr, "tpr": co_tpr, "cost_pi0": co_cost0},
        "cost_optimal_pi1": {"fpr": c1_fpr, "tpr": c1_tpr, "cost_pi1": c1_cost1},
        "rupee_gap_minor": rupee_gap_minor,
        "regime_switch_saving_minor": regime_switch_saving_minor,
        "inputs": {
            "c_fn_minor": cost_model.c_fn_minor(),
            "c_fp_minor_challenge": cost_model.c_fp_minor(COST_TIER),
            "pi0": pi0,
            "pi1": pi1,
            "f1_optimal_point": [f1_fpr, f1_tpr],
            "cost_optimal_point": [co_fpr, co_tpr],
        },
    }


# --------------------------------------------------------------------------
# the other five blocks -- pure serialisation of already-computed objects
# --------------------------------------------------------------------------


def _block1_per_tier(run) -> dict:
    reports = _temporal_reports(run)
    tier_e = _tier_e_reports(run)
    out: Dict[str, dict] = {}
    for mv in _MODEL_ROW_VERSIONS:
        report = reports.get(mv)
        if report is None:
            continue
        te = tier_e.get(mv)
        out[mv] = {
            "easy": _tm_json(report.tier_breakdown.get("easy")),
            "medium": _tm_json(report.tier_breakdown.get("medium")),
            "hard": _tm_json(report.tier_breakdown.get("hard")),
            "evasive": _tm_json(te.tier_breakdown.get("evasive")) if te is not None else None,
        }
    return out


def _block2_negative_controls(run) -> dict:
    from eval.report import THETA_CHALLENGE, _episode_and_attempt_fp
    from eval.scorers import (
        AlwaysPositiveScorer,
        InvertedScorer,
        PerfectScorer,
        RandomScorer,
    )

    scorers = [
        ("perfect", PerfectScorer()),
        ("random", RandomScorer(seed=run.seed)),
        ("inverted", InvertedScorer()),
        ("always_positive", AlwaysPositiveScorer()),
    ]
    out: Dict[str, list] = {}
    for scenario in run.negative_scenario_names:
        split = run.negative_splits.get(scenario)
        rows = []
        if split is not None and split.n:
            for name, scorer in scorers:
                scores = [scorer(s) for s in split.samples]
                n_ep_fp, n_ep, n_att_fp, n_att = _episode_and_attempt_fp(
                    split.samples, scores, THETA_CHALLENGE
                )
                rows.append({
                    "scorer": name, "episode_fp": n_ep_fp, "episodes": n_ep,
                    "attempt_fp": n_att_fp, "attempts": n_att,
                })
        out[scenario] = rows
    return out


def _block6_baselines(run) -> dict:
    bs = run.baseline_summary
    reports = _temporal_reports(run)
    b0_report = reports.get("rules-only-v0")
    from eval.load import _recall_json

    b0 = None
    if b0_report is not None:
        b0 = {
            "split": b0_report.split_name,
            "n": b0_report.n,
            "prevalence": b0_report.prevalence,
            "roc_auc": b0_report.roc_auc_value,
            "ap_raw": b0_report.ap_raw,
            "recall_at_target_fpr": _recall_json(b0_report.recall_at_target_fpr),
        }
    return {
        "b0": b0,
        "b1": _op_json(bs.b1_operating_point),
        "b2": _op_json(bs.b2_operating_point),
        "sanity_recall_at_b1_fpr": dict(bs.sanity_recall_at_b1_fpr),
        "sanity_recall_at_b2_fpr": dict(bs.sanity_recall_at_b2_fpr),
    }


def _tier_e_block(run) -> dict:
    te = run.eval_reports.get("tier_e")
    if not te:
        return {"converged_params": None, "split_n": 0, "prevalence": None,
                "note": "Tier E search was cut; the evasive block is unpopulated."}
    from pathlib import Path as _Path

    import yaml

    report = next(
        (r for r in te if r.provenance.model_version in _MODEL_ROW_VERSIONS), te[0]
    )
    converged = None
    try:
        cfg = yaml.safe_load(
            (_Path(__file__).resolve().parents[1] / "config" / "attack_tiers.yaml")
            .read_text(encoding="utf-8")
        )
        ev = cfg.get("evasive", {})

        def _v(node):
            return node.get("value") if isinstance(node, dict) else node

        band = ev.get("amount_quantile_band", {})
        converged = {
            "attempts_per_hour": _v(ev.get("attempts_per_hour")),
            "ip_pool_size": _v(ev.get("ip_pool_size")),
            "distinct_cards": _v(ev.get("distinct_cards")),
            "bin_pool_size": _v(ev.get("bin_pool_size")),
            "amount_quantile_band": [band.get("min"), band.get("max")],
            "episode_duration_s": _v(ev.get("episode_duration_s")),
        }
    except Exception:  # noqa: BLE001 -- best effort; the report still renders
        converged = None
    return {
        "converged_params": converged,
        "split_n": report.n,
        "prevalence": report.prevalence,
    }


# --------------------------------------------------------------------------
# provenance + top-level assembly
# --------------------------------------------------------------------------


def _provenance(run, *, seeds_used: int, base_seed: int) -> dict:
    from eval.provenance import build_hash

    reports = _temporal_reports(run)
    any_report = next(iter(reports.values()), None)
    cost_model = load_cost_model()

    config_hash = any_report.provenance.config_hash if any_report is not None else None
    policy_version = any_report.provenance.policy_version if any_report is not None else 1
    eval_prevalence = (
        any_report.provenance.eval_prevalence
        if any_report is not None else cost_model.eval_prevalence
    )

    fixture_sha = "missing"
    try:
        from eval.provenance import FIXTURE_SHA_PATH, _sha_file_first_token

        fixture_sha = _sha_file_first_token(FIXTURE_SHA_PATH)
    except Exception:  # noqa: BLE001
        pass

    return {
        "build_hash": build_hash(),
        "config_hash": config_hash,
        "model_version": run.model_version or "rules-only-v0",
        "calibrator_version": "platt-v1" if run.model_version else "identity",
        "policy_version": policy_version,
        "eval_prevalence": eval_prevalence,
        "fixture_sha256": fixture_sha,
        "seed": run.seed,
        "seeds_used": seeds_used,
        "base_seed": base_seed,
    }


def build_artifact(runs, *, seeds_used: int = 1, base_seed: int = 42) -> dict:
    """Serialise the first HarnessRun into the committed D6 artifact dict."""
    run = runs[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": _provenance(run, seeds_used=seeds_used, base_seed=base_seed),
        "block1_per_tier": _block1_per_tier(run),
        "block2_negative_controls": _block2_negative_controls(run),
        "block3_audit": run.audit_block or {},
        "block4_cost": _block4_cost(run),
        "block5_calibration": run.calibration_block or {},
        "block6_baselines": _block6_baselines(run),
        "tier_e": _tier_e_block(run),
    }


def write_artifact(runs, out_path, *, seeds_used: int = 1, base_seed: int = 42) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact(runs, seeds_used=seeds_used, base_seed=base_seed)
    out_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out_path
