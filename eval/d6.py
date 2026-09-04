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

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from eval.cost import load_cost_model

# Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §8 / §26.1 -- v1 -> v2 is
# ADDITIVE. Every schema_version 1 key survives unchanged; v2 only adds fields
# (per-tier split + eval_prevalence, theta_challenge, ece_raw, separability,
# the Block 2/6 model rows, provenance completeness). `SCHEMA_VERSION` is bumped
# to 2 once every v2 field below is emitted; `eval.d6_schema.validate_or_raise`
# in `write_artifact` is the completeness gate that enforces it.
SCHEMA_VERSION = 2
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

    ribbon_curves = {pi: _curve(hull_points, cost_model, pi) for pi in RIBBON_PIS}
    ribbon = [{"pi": pi, "curve": ribbon_curves[pi]} for pi in RIBBON_PIS]

    # Source: plan FIX-M-005 -- a TRUE per-x envelope across all ribbon pi
    # values. All ribbon curves share the hull x-coordinates, so per-index
    # min/max is well defined and hi_i >= lo_i BY CONSTRUCTION -- the polygon
    # cannot self-intersect (the current lo-forward + hi-reversed path crosses
    # at FPR ~= 0.30). Emitted so the frontend does zero envelope arithmetic.
    ribbon_envelope = []
    for i, (fpr, _tpr) in enumerate(hull_points):
        costs_at_i = [ribbon_curves[pi][i][2] for pi in RIBBON_PIS]
        ribbon_envelope.append([fpr, min(costs_at_i), max(costs_at_i)])

    # Source: plan FIX-M-004 / FIX-M-039 -- state the coincidence as a Python
    # fact, not a frontend pixel comparison. At pi0 = 0.001 precision collapses
    # away from FPR = 0, so F1-argmax and cost-argmin land on the SAME hull
    # vertex almost by construction; the resulting rupee_gap of 0 is structural,
    # not an empirical finding about this model.
    optima_coincident = (f1_fpr, f1_tpr) == (co_fpr, co_tpr)
    f1_next = None
    for fpr, tpr, _c in curve_pi0:
        if (fpr, tpr) != (f1_fpr, f1_tpr):
            f1_next = _f1(fpr, tpr, pi0)
            break
    rupee_gap_note = (
        "At a steady-state prevalence of {pi0:g}, precision collapses away from FPR = 0 "
        "(F1 falls from {f1_here:.4f} at the optimum to {f1_next} at the next hull vertex), "
        "so the F1-optimal and cost-optimal operating points coincide. The rupee gap is a "
        "structural consequence of that prevalence, not a coincidence of this model."
    ).format(
        pi0=pi0, f1_here=f1_val,
        f1_next=f"{f1_next:.4f}" if f1_next is not None else "n/a",
    )

    # Source: plan FIX-M-003 / §14.2 -- the Panel-A focus bound. The decision
    # region contains both optima (FPR 0) plus the first hull vertex that leaves
    # it, with 50% headroom; the frontend draws x in [0, this] on a log-y panel.
    beyond = sorted(fpr for fpr, _tpr, _c in curve_pi0 if fpr > co_fpr)
    decision_region_fpr_max = beyond[0] * 1.5 if beyond else 0.01

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
        "ribbon_envelope": ribbon_envelope,
        "f1_optimal": {"fpr": f1_fpr, "tpr": f1_tpr, "f1": f1_val, "cost_pi0": f1_cost0},
        "cost_optimal": {"fpr": co_fpr, "tpr": co_tpr, "cost_pi0": co_cost0},
        "cost_optimal_pi1": {"fpr": c1_fpr, "tpr": c1_tpr, "cost_pi1": c1_cost1},
        "optima_coincident": optima_coincident,
        "rupee_gap_minor": rupee_gap_minor,
        "rupee_gap_is_structural": optima_coincident,
        "rupee_gap_note": rupee_gap_note,
        "regime_switch_saving_minor": regime_switch_saving_minor,
        "decision_region_fpr_max": decision_region_fpr_max,
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


def _tm_with_context(tm, *, split: Optional[str], eval_prevalence: float) -> Optional[dict]:
    """`_tm_json` + the per-tier split identity (M-016) and echoed pi_eval
    (M-001). easy/medium/hard come from `temporal_test`; evasive from the
    dedicated `tier_e` split -- the UI must label which."""
    d = _tm_json(tm)
    if d is None:
        return None
    d["split"] = split
    d["eval_prevalence"] = eval_prevalence
    return d


def _block1_per_tier(run) -> dict:
    reports = _temporal_reports(run)
    tier_e = _tier_e_reports(run)
    eval_prevalence = load_cost_model().eval_prevalence
    out: Dict[str, dict] = {}
    for mv in _MODEL_ROW_VERSIONS:
        report = reports.get(mv)
        if report is None:
            continue
        te = tier_e.get(mv)
        te_split = te.split_name if te is not None else None
        out[mv] = {
            "easy": _tm_with_context(report.tier_breakdown.get("easy"),
                                     split=report.split_name, eval_prevalence=eval_prevalence),
            "medium": _tm_with_context(report.tier_breakdown.get("medium"),
                                       split=report.split_name, eval_prevalence=eval_prevalence),
            "hard": _tm_with_context(report.tier_breakdown.get("hard"),
                                     split=report.split_name, eval_prevalence=eval_prevalence),
            "evasive": _tm_with_context(te.tier_breakdown.get("evasive"),
                                        split=te_split, eval_prevalence=eval_prevalence)
            if te is not None else None,
        }
    return out


def _theta_challenge() -> float:
    """The Block-2 episode/attempt-FP threshold, derived (never rounded) from the
    cost model. Single-sourced via `eval.report.theta_challenge` so the value
    lives in exactly one place (plan FIX-BE-01 / RC-2)."""
    from eval.report import theta_challenge

    return theta_challenge()


_DENOMINATOR_BASIS = "legitimate_attempts_only"


def _episode_flagged(episode_fp: Optional[int]) -> Optional[bool]:
    """Block 2's `episodes` is structurally 1 per negative-control scenario
    (`eval/corpus.py::build_runs` -> one run, one episode). It is a boolean
    observation, not a rate -- re-typed here (plan §1(B) / M-017). `None` only
    when the row itself is an Unavailable envelope."""
    if episode_fp is None:
        return None
    return episode_fp > 0


def _block2_negative_controls(run) -> dict:
    from eval.report import _episode_and_attempt_fp
    from eval.scorers import (
        AlwaysPositiveScorer,
        InvertedScorer,
        PerfectScorer,
        RandomScorer,
    )

    theta = _theta_challenge()

    # Model + B0 first (the product's own FP behaviour), then the four sanity
    # scorers as the harness floor (plan FIX-BE-02 -- 6 rows/scenario). The
    # model scorers are the SAME instances `run_all` built (via
    # `run.model_scorers`), never reconstructed here, so `pi_s` cannot drift.
    model_rows: List[Tuple[str, object]] = [
        (mv, scorer) for _key, (mv, scorer) in getattr(run, "model_scorers", {}).items()
    ]
    # Bare sanity-scorer names, unchanged from schema v1 (`perfect` etc.), so
    # the existing frontend label map keeps working. Model rows carry their real
    # model_version (`l1-lgbm-v1` / `rules-only-v0`).
    sanity_rows: List[Tuple[str, object]] = [
        ("perfect", PerfectScorer()),
        ("random", RandomScorer(seed=run.seed)),
        ("inverted", InvertedScorer()),
        ("always_positive", AlwaysPositiveScorer()),
    ]

    out: Dict[str, list] = {}
    for scenario in run.negative_scenario_names:
        split = run.negative_splits.get(scenario)
        rows: List[dict] = []
        if split is not None and split.n:
            if not model_rows:
                # No model bundle in this run -> explicit Unavailable envelopes
                # for the two model rows. Never omitted, never zeroed (M-007).
                for mv in ("l1-lgbm-v1", "rules-only-v0"):
                    rows.append({
                        "scorer": mv, "episode_fp": None, "episodes": None,
                        "attempt_fp": None, "attempts": None,
                        "episode_flagged": None, "denominator_basis": _DENOMINATOR_BASIS,
                        "available": False,
                        "reason": "harness run without --model-dir; model scorer unavailable",
                    })
            for scorer_name, scorer in model_rows + sanity_rows:
                scores = [scorer(s) for s in split.samples]
                n_ep_fp, n_ep, n_att_fp, n_att = _episode_and_attempt_fp(
                    split.samples, scores, theta
                )
                rows.append({
                    "scorer": scorer_name, "episode_fp": n_ep_fp, "episodes": n_ep,
                    "attempt_fp": n_att_fp, "attempts": n_att,
                    "episode_flagged": _episode_flagged(n_ep_fp),
                    "denominator_basis": _DENOMINATOR_BASIS,
                    "available": True,
                    "reason": None,
                })
        out[scenario] = rows
    return out


def _baseline_row_json(report) -> Optional[dict]:
    """B0/model overall row -- same shape for both (plan FIX-BE-03 / M-008)."""
    if report is None:
        return None
    from eval.load import _recall_json

    return {
        "split": report.split_name,
        "n": report.n,
        "prevalence": report.prevalence,
        "roc_auc": report.roc_auc_value,
        "ap_raw": report.ap_raw,
        "recall_at_target_fpr": _recall_json(report.recall_at_target_fpr),
    }


_SANITY_FLOOR_REASON = (
    "unreachable: a constant scorer (always_positive) has <=2 distinct ROC points, "
    "so its recall at a matched FPR is undefined -- not a measured 0"
)


def _sanity_floor_envelope(sanity_recall: Dict[str, Optional[float]]) -> Dict[str, dict]:
    """Re-home `sanity_recall_at_b*_fpr` into per-scorer Unavailable envelopes so
    the `always_positive: null` finally carries its reason (plan FIX-BE-03 /
    M-038). Every entry normalised to `{value, available, reason}`."""
    out: Dict[str, dict] = {}
    for name, value in sanity_recall.items():
        if value is None:
            out[name] = {"value": None, "available": False, "reason": _SANITY_FLOOR_REASON}
        else:
            out[name] = {"value": value, "available": True, "reason": None}
    return out


def _block6_baselines(run) -> dict:
    bs = run.baseline_summary
    reports = _temporal_reports(run)

    per_tier: Dict[str, dict] = {}
    for tier, row in getattr(bs, "per_tier", {}).items():
        per_tier[tier] = {
            "model": _op_json(row.get("model")),
            "b0": _op_json(row.get("b0")),
            "b1": _op_json(row.get("b1")),
            "b2": _op_json(row.get("b2")),
        }

    return {
        # Source: plan FIX-BE-03 / M-008 -- the section finally has a subject.
        "model": _baseline_row_json(reports.get("l1-lgbm-v1")),
        "b0": _baseline_row_json(reports.get("rules-only-v0")),
        "b1": _op_json(bs.b1_operating_point),
        "b2": _op_json(bs.b2_operating_point),
        "sanity_recall_at_b1_fpr": dict(bs.sanity_recall_at_b1_fpr),
        "sanity_recall_at_b2_fpr": dict(bs.sanity_recall_at_b2_fpr),
        "b1_sanity_floor": _sanity_floor_envelope(bs.sanity_recall_at_b1_fpr),
        "b2_sanity_floor": _sanity_floor_envelope(bs.sanity_recall_at_b2_fpr),
        "per_tier": per_tier,
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
# block 3 -- two-sided discriminability, DERIVED (no retrain, no mutation)
# --------------------------------------------------------------------------


def _augment_audit_block(audit_block: dict) -> dict:
    """Derive two-sided discriminability from the authoritative univariate AUCs
    already in `block3_audit` -- NEVER a retrain, NEVER a mutation of
    `models/audit.json` (that file is byte-identical before and after; this
    function deep-copies its input). Adds, per feature: `separability =
    abs(auc - 0.5)`, `direction`, `flagged_two_sided`; and, block-level, the
    correctly-named `univariate_auc_threshold` twin plus the real
    `observed_max_univariate_auc` (M-011, M-013).

    `flagged_two_sided` uses `>=` at the boundary (a feature exactly at the
    threshold IS flagged), matching the UI's long-standing boundary-inclusive
    reading and `config/features.yaml`'s "flag threshold" wording. Pinned by a
    test at exactly 0.95 (plan FIX-BE-05). The frontend consumes THIS flag and
    performs no comparison of its own (M-012).
    """
    if not audit_block:
        return {}
    out = json.loads(json.dumps(audit_block))  # deep copy -- never mutate input
    threshold = out.get("max_univariate_auc")
    feats = out.get("features", {})
    observed_max: Optional[float] = None
    for _name, f in feats.items():
        auc = f.get("univariate_auc")
        constant = bool(f.get("constant"))
        if auc is None:
            f["separability"] = None
            f["direction"] = None
            f["flagged_two_sided"] = False
            continue
        sep = abs(auc - 0.5)
        f["separability"] = sep
        f["direction"] = None if constant else ("inverted" if auc < 0.5 else "positive")
        f["flagged_two_sided"] = bool(
            (not constant) and threshold is not None and sep >= (threshold - 0.5)
        )
        if not constant:
            observed_max = auc if observed_max is None else max(observed_max, auc)
    out["univariate_auc_threshold"] = threshold
    out["observed_max_univariate_auc"] = observed_max
    return out


# --------------------------------------------------------------------------
# provenance + top-level assembly
# --------------------------------------------------------------------------


def _sha256_file(path: Path) -> Optional[str]:
    """Streamed SHA-256 of one file, or None if it is absent/unreadable. Used
    for corpus + model identity in provenance (plan §17.2) -- `eval/provenance.py`
    has `_sha_file_first_token` only, which reads a `.sha256` sidecar, not a
    binary; this hashes the file itself. `hashlib` is already the module's tool."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _model_files_sha256(model_dir: Optional[Path]) -> Dict[str, str]:
    """{filename: sha256} over `models/*.json` and `*.txt` -- model identity for
    the freshness model (plan §8.3 row 5). Empty when no `--model-dir` was given."""
    if model_dir is None:
        return {}
    out: Dict[str, str] = {}
    for path in sorted(Path(model_dir).glob("*")):
        if path.suffix in (".json", ".txt") and path.is_file():
            digest = _sha256_file(path)
            if digest is not None:
                out[path.name] = digest
    return out


def _provenance(
    run, *, seeds_used: int, base_seed: int,
    corpus_db: Optional[Path] = None, model_dir: Optional[Path] = None,
) -> dict:
    from eval.provenance import _git_head_and_dirty, build_hash

    REPO_ROOT = Path(__file__).resolve().parents[1]

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

    head, dirty = _git_head_and_dirty(REPO_ROOT)

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
        # Source: plan §8.3 rows 2-7 / §17.2 -- provenance completeness (M-029).
        # The freshness model is configuration + corpus + model identity +
        # generation metadata; build_hash divergence ALONE is NOT staleness.
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generation_command": " ".join(sys.argv),
        "head_at_generation": head,
        "tree_dirty_at_generation": bool(dirty),
        "corpus_db_sha256": _sha256_file(Path(corpus_db)) if corpus_db is not None else None,
        "model_files_sha256": _model_files_sha256(model_dir),
    }


def build_artifact(
    runs, *, seeds_used: int = 1, base_seed: int = 42,
    corpus_db=None, model_dir=None,
) -> dict:
    """Serialise the first HarnessRun into the committed D6 artifact dict.

    `corpus_db` / `model_dir` are the harness's own `--corpus-db` / `--model-dir`
    paths, threaded through only so provenance can record corpus + model
    identity (plan §17.2). Absent on a model-less run -> those provenance
    fields degrade to null / {} (never fabricated)."""
    run = runs[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": _provenance(
            run, seeds_used=seeds_used, base_seed=base_seed,
            corpus_db=corpus_db, model_dir=model_dir,
        ),
        "block1_per_tier": _block1_per_tier(run),
        "block2_negative_controls": _block2_negative_controls(run),
        "block2_theta_challenge": _theta_challenge(),
        "block3_audit": _augment_audit_block(run.audit_block or {}),
        "block4_cost": _block4_cost(run),
        "block5_calibration": run.calibration_block or {},
        "block6_baselines": _block6_baselines(run),
        "tier_e": _tier_e_block(run),
    }


def write_artifact(
    runs, out_path, *, seeds_used: int = 1, base_seed: int = 42,
    corpus_db=None, model_dir=None,
) -> Path:
    from eval.d6_schema import validate_or_raise

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact(
        runs, seeds_used=seeds_used, base_seed=base_seed,
        corpus_db=corpus_db, model_dir=model_dir,
    )
    # Source: plan §18.3 -- the generation boundary. An invalid artifact never
    # reaches disk; the full violation list is raised, not the first error only.
    validate_or_raise(artifact)
    out_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out_path
