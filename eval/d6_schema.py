"""
Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §9 FIX-BE-06 / §18 -- a
stdlib-only structural schema for the committed D6 artifact
(`eval/outputs/d6.json`).

The artifact is the ENTIRE contract between the Python evaluation harness and
the React Metrics page, ~230 leaf fields, and until now had zero validation
anywhere. This module is that contract boundary: a declarative spec (nested
`Field` objects) plus a `validate(artifact) -> list[str]` walker that returns a
named, path-anchored error for every violation. `validate_or_raise` is wired
into `eval.d6.write_artifact` so an invalid artifact never reaches disk, and
`tests/acceptance/test_d6_schema.py` runs the same walker over the committed
file and over deliberately-malformed mutations of it.

No `jsonschema` dependency: `eval/` is deliberately dependency-clean
(`eval/metrics.py`: "pure stdlib metrics, no new dependencies"), and a ~200-line
declarative walker reads better in review than a JSON-Schema document for this.

Versioning (plan §8.1, §26.1): the schema is additive. Every `schema_version: 1`
leaf is still declared and still required at v2. A field introduced at v2 carries
`min_version=2`: it is REQUIRED when the artifact declares `schema_version >= 2`,
TOLERATED (never an error) at v1, and never "unknown". This lets the validator be
landed and proven against the committed v1 file before it can block anything.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

SUPPORTED_SCHEMA_VERSIONS: Tuple[int, ...] = (1, 2)
CURRENT_SCHEMA_VERSION = 2


class D6SchemaError(ValueError):
    """Raised by `validate_or_raise` with the full newline-joined error list."""


# ---------------------------------------------------------------------------
# Field spec
# ---------------------------------------------------------------------------


class Field:
    """One node of the schema.

    Exactly one structural role is set:
      * `py_types`  -- a scalar leaf (tuple of accepted Python types)
      * `shape`     -- an object with a fixed set of named keys (`dict[str, Field]`)
      * `item`      -- a list; every element validated against this `Field`
      * `values`    -- an open mapping; every value validated against this `Field`
                       (keys are free-form: model versions, tier names, scenarios)
    """

    __slots__ = (
        "py_types", "shape", "item", "values",
        "nullable", "required", "min_version", "enum", "min_items", "fixed_len",
    )

    def __init__(
        self,
        *,
        py_types: Optional[Tuple[type, ...]] = None,
        shape: Optional[Dict[str, "Field"]] = None,
        item: Optional["Field"] = None,
        values: Optional["Field"] = None,
        nullable: bool = False,
        required: bool = True,
        min_version: int = 1,
        enum: Optional[Sequence[Any]] = None,
        min_items: int = 0,
        fixed_len: Optional[int] = None,
    ) -> None:
        self.py_types = py_types
        self.shape = shape
        self.item = item
        self.values = values
        self.nullable = nullable
        self.required = required
        self.min_version = min_version
        self.enum = tuple(enum) if enum is not None else None
        self.min_items = min_items
        self.fixed_len = fixed_len


# scalar shorthands ---------------------------------------------------------

def NUM(**kw: Any) -> Field: return Field(py_types=(int, float), **kw)
def NUM_N(**kw: Any) -> Field: return Field(py_types=(int, float), nullable=True, **kw)
def INT(**kw: Any) -> Field: return Field(py_types=(int,), **kw)
def INT_N(**kw: Any) -> Field: return Field(py_types=(int,), nullable=True, **kw)
def BOOL(**kw: Any) -> Field: return Field(py_types=(bool,), **kw)
def BOOL_N(**kw: Any) -> Field: return Field(py_types=(bool,), nullable=True, **kw)
def STR(**kw: Any) -> Field: return Field(py_types=(str,), **kw)
def STR_N(**kw: Any) -> Field: return Field(py_types=(str,), nullable=True, **kw)


def OBJ(shape: Dict[str, Field], **kw: Any) -> Field:
    return Field(shape=shape, **kw)


def ARR(item: Field, **kw: Any) -> Field:
    return Field(item=item, **kw)


def MAP(values: Field, **kw: Any) -> Field:
    return Field(values=values, **kw)


# ---------------------------------------------------------------------------
# reusable sub-shapes
# ---------------------------------------------------------------------------

def _recall(**kw: Any) -> Field:
    # The existing rich recall object -- kept exactly (plan §8.2: best-designed
    # object in the artifact; re-typing it would churn a correct contract).
    return OBJ({
        "value": NUM_N(),
        "n_neg": INT(),
        "resolvable": BOOL(),
        "ci_low": NUM_N(),
        "ci_high": NUM_N(),
        # v2: correctly-named twins of ci_low/ci_high + the basis string (M-040).
        "fpr_ci_low": NUM_N(min_version=2),
        "fpr_ci_high": NUM_N(min_version=2),
        "ci_basis": STR(min_version=2),
    }, nullable=True, **kw)


def _unavailable(**kw: Any) -> Field:
    # The RC-3 "unknown" envelope, used by every NEW model-dependent field so a
    # component sees exactly one missing-value concept (plan §8.2).
    return OBJ({
        "value": NUM_N(),
        "available": BOOL(),
        "reason": STR_N(),
    }, **kw)


def _tier_metrics(**kw: Any) -> Field:
    return OBJ({
        "n": INT(),
        "prevalence": NUM_N(),
        "recall_at_target_fpr": _recall(),
        "ap_raw": NUM_N(),
        "ap_at_eval_prevalence": NUM_N(),
        # v2: per-tier split identity (M-016) + echoed pi_eval (M-001).
        "split": STR(min_version=2),
        "eval_prevalence": NUM(min_version=2),
    }, nullable=True, **kw)


def _operating_point(**kw: Any) -> Field:
    # `precision` is `tp/(tp+fp)` or None when nothing is predicted positive --
    # common on a per-tier subset where a baseline fires no rule (eval.metrics
    # OperatingPoint.precision is Optional[float]).
    return OBJ({
        "fpr": NUM(), "tpr": NUM(), "precision": NUM_N(), "recall": NUM(),
        "tp": INT(), "fp": INT(), "tn": INT(), "fn": INT(),
    }, nullable=True, **kw)


def _baseline_row(**kw: Any) -> Field:
    return OBJ({
        "split": STR(),
        "n": INT(),
        "prevalence": NUM(),
        "roc_auc": NUM_N(),
        "ap_raw": NUM_N(),
        "recall_at_target_fpr": _recall(),
    }, nullable=True, **kw)


RELIABILITY_BIN = OBJ({
    "lo": NUM(), "hi": NUM(), "weight": NUM(),
    "mean_predicted": NUM_N(), "observed_rate": NUM_N(),
})

REGIME = OBJ({
    "brier_raw": NUM(),
    "brier_platt": NUM(),
    "brier_platt_prior": NUM(),
    "ece_platt": NUM(),
    "ece_platt_prior": NUM(),
    "effective_n": NUM(),
    # v2: the missing raw-ECE (M-010) + the derived gap (Eval Protocol §3.4).
    "ece_raw": NUM(min_version=2),
    "ece_gap_platt_prior_vs_platt": NUM(min_version=2),
})

AUDIT_FEATURE = OBJ({
    "constant": BOOL(),
    "excluded": BOOL(),
    "flagged": BOOL(),
    "reason": STR_N(),
    "univariate_auc": NUM_N(),
    # v2: two-sided separability derivation (M-013), never a retrain.
    "separability": NUM_N(min_version=2),
    "direction": Field(py_types=(str,), nullable=True, enum=("positive", "inverted"),
                       min_version=2),
    "flagged_two_sided": BOOL(min_version=2),
})

CURVE = ARR(ARR(NUM(), fixed_len=3), min_items=1)

# ---------------------------------------------------------------------------
# the artifact root
# ---------------------------------------------------------------------------

ROOT = OBJ({
    "schema_version": INT(),

    "provenance": OBJ({
        "build_hash": STR(),
        "config_hash": STR(),
        "model_version": STR(),
        "calibrator_version": STR(),
        "policy_version": INT(),
        "eval_prevalence": NUM(),
        "fixture_sha256": STR(),
        "seed": INT(),
        "seeds_used": INT(),
        "base_seed": INT(),
        # v2 provenance completeness (M-029, §17.2).
        "generated_at": STR(min_version=2),
        "generation_command": STR(min_version=2),
        "head_at_generation": STR(min_version=2),
        "tree_dirty_at_generation": BOOL(min_version=2),
        "corpus_db_sha256": STR_N(min_version=2),
        "model_files_sha256": MAP(STR(), min_version=2),
    }),

    "block1_per_tier": MAP(MAP(_tier_metrics())),

    "block2_negative_controls": MAP(ARR(OBJ({
        "scorer": STR(),
        "episode_fp": INT_N(),
        "episodes": INT_N(),
        "attempt_fp": INT_N(),
        "attempts": INT_N(),
        # v2: boolean re-type of the structurally-forced episode count (M-017)
        # + the denominator-basis label + the Unavailable envelope for a
        # model-less run (M-007).
        "episode_flagged": BOOL_N(min_version=2),
        "denominator_basis": STR(min_version=2),
        "available": BOOL(min_version=2),
        "reason": STR_N(min_version=2),
    }))),
    "block2_theta_challenge": NUM(min_version=2),

    "block3_audit": OBJ({
        "features": MAP(AUDIT_FEATURE),
        "max_univariate_auc": NUM(),
        "statistic": STR(),
        "training_set": OBJ({
            "n": INT(), "n_positive": INT(), "prevalence": NUM(),
        }),
        # v2: the correctly-named threshold twin + the real observed maximum
        # (M-011).
        "univariate_auc_threshold": NUM(min_version=2),
        "observed_max_univariate_auc": NUM(min_version=2),
    }),

    "block4_cost": OBJ({
        "tier": STR(),
        "series": STR(),
        "series_substitution": STR_N(),
        "split": STR(),
        "pi0": NUM(),
        "pi1": NUM(),
        "curve_pi0": CURVE,
        "curve_pi1": CURVE,
        "ribbon": ARR(OBJ({"pi": NUM(), "curve": CURVE})),
        "ribbon_pis": ARR(NUM(), min_items=1),
        "f1_optimal": OBJ({"fpr": NUM(), "tpr": NUM(), "f1": NUM(), "cost_pi0": NUM()}),
        "cost_optimal": OBJ({"fpr": NUM(), "tpr": NUM(), "cost_pi0": NUM()}),
        "cost_optimal_pi1": OBJ({"fpr": NUM(), "tpr": NUM(), "cost_pi1": NUM()}),
        "rupee_gap_minor": NUM(),
        "regime_switch_saving_minor": NUM(),
        "inputs": OBJ({
            "c_fn_minor": NUM(),
            "c_fp_minor_challenge": NUM(),
            "pi0": NUM(),
            "pi1": NUM(),
            "f1_optimal_point": ARR(NUM(), fixed_len=2),
            "cost_optimal_point": ARR(NUM(), fixed_len=2),
        }),
        # v2: facts computed in Python instead of by a frontend float compare
        # (M-004, M-039) + a valid per-x ribbon envelope (M-005) + the
        # decision-region focus bound (M-003).
        "optima_coincident": BOOL(min_version=2),
        "rupee_gap_is_structural": BOOL(min_version=2),
        "rupee_gap_note": STR(min_version=2),
        "ribbon_envelope": ARR(ARR(NUM(), fixed_len=3), min_items=1, min_version=2),
        "decision_region_fpr_max": NUM(min_version=2),
    }),

    "block5_calibration": OBJ({
        "n": INT(),
        "n_bins": INT(),
        "pi_t": NUM(),
        "raw_prevalence": NUM(),
        "pi0": REGIME,
        "pi1": REGIME,
        "reliability_pi0": ARR(RELIABILITY_BIN, min_items=1),
        "reliability_pi1": ARR(RELIABILITY_BIN, min_items=1),
        # v2: Eval Protocol §3.4's own pass/fail test (M-010, M-036).
        "prior_correction_helped_at_pi1": BOOL(min_version=2),
    }),

    "block6_baselines": OBJ({
        "b0": _baseline_row(),
        "b1": _operating_point(),
        "b2": _operating_point(),
        "sanity_recall_at_b1_fpr": MAP(NUM_N()),
        "sanity_recall_at_b2_fpr": MAP(NUM_N()),
        # v2: the section finally gets a subject + a B3 floor with reasons +
        # a per-tier matrix (M-008, M-038). `b*_sanity_floor` maps each sanity
        # scorer name to an Unavailable envelope so `always_positive: null`
        # carries a reason.
        "model": _baseline_row(min_version=2),
        "b1_sanity_floor": MAP(_unavailable(), min_version=2),
        "b2_sanity_floor": MAP(_unavailable(), min_version=2),
        "per_tier": MAP(OBJ({
            "model": _operating_point(),
            "b0": _operating_point(),
            "b1": _operating_point(),
            "b2": _operating_point(),
        }), min_version=2),
    }),

    "tier_e": OBJ({
        "converged_params": OBJ({
            "attempts_per_hour": NUM_N(),
            "ip_pool_size": NUM_N(),
            "distinct_cards": NUM_N(),
            "bin_pool_size": NUM_N(),
            "amount_quantile_band": ARR(NUM_N(), fixed_len=2),
            "episode_duration_s": NUM_N(),
        }, nullable=True),
        "split_n": INT(),
        "prevalence": NUM_N(),
        "note": STR(required=False),
    }),
})


# ---------------------------------------------------------------------------
# the walker
# ---------------------------------------------------------------------------


def _type_ok(value: Any, py_types: Tuple[type, ...]) -> bool:
    """JSON-aware scalar type check. `bool` is a subclass of `int` in Python,
    so a bare bool is only acceptable where `bool` is explicitly declared;
    conversely an `int` satisfies a `float` slot (JSON has one number type)."""
    if isinstance(value, bool):
        return bool in py_types
    if isinstance(value, int) and float in py_types and int not in py_types:
        return True
    return isinstance(value, py_types)


def _walk(node: Any, spec: Field, path: str, version: int, errors: List[str]) -> None:
    if node is None:
        if not spec.nullable:
            errors.append(f"{path or '<root>'}: null is not permitted here")
        return

    if spec.shape is not None:
        if not isinstance(node, dict):
            errors.append(f"{path or '<root>'}: expected an object, got {type(node).__name__}")
            return
        for key, field in spec.shape.items():
            child = f"{path}.{key}" if path else key
            if key not in node:
                if field.required and field.min_version <= version:
                    errors.append(f"{child}: required field is missing")
                continue
            _walk(node[key], field, child, version, errors)
        known = set(spec.shape)
        for key in node:
            if key not in known:
                errors.append(
                    f"{path}.{key}: unknown key not declared in the D6 schema"
                    if path else f"{key}: unknown top-level key not declared in the D6 schema"
                )
        return

    if spec.item is not None:
        if not isinstance(node, list):
            errors.append(f"{path or '<root>'}: expected a list, got {type(node).__name__}")
            return
        if len(node) < spec.min_items:
            errors.append(f"{path}: expected at least {spec.min_items} element(s), got {len(node)}")
        if spec.fixed_len is not None and len(node) != spec.fixed_len:
            errors.append(f"{path}: expected exactly {spec.fixed_len} element(s), got {len(node)}")
        for i, element in enumerate(node):
            _walk(element, spec.item, f"{path}[{i}]", version, errors)
        return

    if spec.values is not None:
        if not isinstance(node, dict):
            errors.append(f"{path or '<root>'}: expected a mapping, got {type(node).__name__}")
            return
        for key, value in node.items():
            _walk(value, spec.values, f"{path}.{key}" if path else str(key), version, errors)
        return

    # scalar leaf
    assert spec.py_types is not None
    if not _type_ok(node, spec.py_types):
        want = "/".join(t.__name__ for t in spec.py_types)
        errors.append(f"{path or '<root>'}: expected {want}, got {type(node).__name__} ({node!r})")
        return
    if spec.enum is not None and node not in spec.enum:
        errors.append(f"{path or '<root>'}: {node!r} is not one of {list(spec.enum)}")


def validate(artifact: Any) -> List[str]:
    """Return a list of human-readable, path-anchored violations. Empty list ==
    the artifact conforms. Never raises."""
    errors: List[str] = []
    if not isinstance(artifact, dict):
        return [f"<root>: expected an object, got {type(artifact).__name__}"]

    version = artifact.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        errors.append(f"schema_version: expected int, got {version!r}")
        version = CURRENT_SCHEMA_VERSION  # keep walking with a best guess
    elif version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"schema_version: {version} is not supported "
            f"(this build understands {list(SUPPORTED_SCHEMA_VERSIONS)}); "
            f"regenerate with `python -m eval.harness --split all --seed 42 "
            f"--corpus-db data/corpus/tollgate.db --model-dir models`"
        )
        version = CURRENT_SCHEMA_VERSION

    _walk(artifact, ROOT, "", version, errors)
    return errors


def validate_or_raise(artifact: Any) -> None:
    """`validate`, then raise `D6SchemaError` with the full list on any failure.
    Wired into `eval.d6.write_artifact` so an invalid artifact never hits disk."""
    errors = validate(artifact)
    if errors:
        raise D6SchemaError(
            f"D6 artifact failed schema validation ({len(errors)} error(s)):\n  - "
            + "\n  - ".join(errors)
        )
