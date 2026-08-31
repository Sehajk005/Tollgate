r"""
Source: Day-7 Plan §4 Step 7 / §6 -- Tier E, the adaptive adversary. A PURE,
import-safe, seeded config-space search over the SIX parameters
`generate_attack_episode` actually consumes, run against a FROZEN detector
supplied as a callback.

Safety boundary (Eval Protocol §5 / §12 trap 2): this module imports ONLY
`packages.simulator.rng` and the standard library -- never the scorer, never a
network-capable module. `tests/acceptance/test_simulator_safety.py`'s AST
transitive-import closure covers it for free; the driver that owns the
detector lives in `scripts/search_evasive.py`, outside the simulator package.

Determinism: every draw comes from `SubStream(seed, "evade:<field>")` (Decision
30 -- getrandbits only, no float RNG, no numpy). Termination: `budget`
evaluations OR `patience` consecutive non-improving candidates -- both hard
bounds, the search cannot fail to terminate. The same `(seed, budget)`
reproduces the same vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from packages.simulator.rng import SubStream

# Source: Day-7 Plan §6 "What is searched" -- reading
# packages/simulator/attack.py:54-72, these are the ONLY parameters the
# generator reads. `foreign_bin_share`, `amount_sampler`, `session_reuse` and
# `hour_of_day_placement` are declared in attack_tiers.yaml but never consumed;
# searching them would fabricate a finding, so they are carried at their
# hard-tier values by scripts/search_evasive.py and NOT part of this space.
SEARCH_FIELDS: Tuple[str, ...] = (
    "attempts_per_hour",
    "ip_pool_size",
    "distinct_cards",
    "bin_pool_size",
    "amount_band_min",
    "amount_band_max",
    "episode_duration_s",
)


@dataclass(frozen=True)
class SearchSpace:
    attempts_per_hour: Tuple[int, int] = (20, 1200)      # attack.py:56
    ip_pool_size: Tuple[int, int] = (1, 80)              # attack.py:59
    distinct_cards: Tuple[int, int] = (50, 400)          # attack.py:62
    bin_pool_size: Tuple[int, int] = (1, 24)             # attack.py:65
    amount_quantile_band: Tuple[int, int] = (0, 900)     # attack.py:68-70 (min < max)
    episode_duration_s: Tuple[int, int] = (600, 3600)    # attack.py:54


@dataclass(frozen=True)
class EpisodeOutcome:
    """What the detector callback returns for one candidate. `evaluate_fn`
    (scripts/search_evasive.py) produces this by replaying the candidate's
    stream through the frozen detector via the existing injected-stream seam."""

    mean_score_calibrated: float
    incident_opened: bool
    cards_validated_per_hour: float
    attempts_total: int
    cards_exposed_before_alert: Optional[int] = None


@dataclass(frozen=True)
class SearchResult:
    best_params: Optional[Dict]
    best_objective: float
    n_evaluated: int
    converged: bool
    stopped_reason: str            # "budget" | "patience"
    theta_challenge: float
    trace: List[Dict] = field(default_factory=list)


def _uniform_int(sub: SubStream, lo: int, hi: int) -> int:
    """Uniform integer in [lo, hi] (both inclusive) from a SubStream."""
    return lo + sub.below(hi - lo + 1)


def _sample_candidate(space: SearchSpace, streams: Dict[str, SubStream]) -> Dict:
    lo_raw = _uniform_int(streams["amount_band_min"], *space.amount_quantile_band)
    hi_raw = _uniform_int(streams["amount_band_max"], *space.amount_quantile_band)
    band_lo, band_hi = (lo_raw, hi_raw) if lo_raw < hi_raw else (hi_raw, lo_raw)
    if band_lo == band_hi:
        if band_hi < space.amount_quantile_band[1]:
            band_hi += 1
        else:
            band_lo -= 1
    return {
        "attempts_per_hour": _uniform_int(streams["attempts_per_hour"], *space.attempts_per_hour),
        "ip_pool_size": _uniform_int(streams["ip_pool_size"], *space.ip_pool_size),
        "distinct_cards": _uniform_int(streams["distinct_cards"], *space.distinct_cards),
        "bin_pool_size": _uniform_int(streams["bin_pool_size"], *space.bin_pool_size),
        "amount_quantile_band": {"min": band_lo, "max": band_hi},
        "episode_duration_s": _uniform_int(streams["episode_duration_s"], *space.episode_duration_s),
    }


def objective(outcome: EpisodeOutcome, theta_challenge: float) -> float:
    """Eval Protocol §5, verbatim:

        maximise    cards_validated_per_hour
        subject to  mean(score_calibrated) < theta_challenge
                    and no incident opened within the episode

    A candidate violating either constraint scores -inf and is discarded.
    """
    if outcome.incident_opened:
        return float("-inf")
    if outcome.mean_score_calibrated >= theta_challenge:
        return float("-inf")
    return outcome.cards_validated_per_hour


def search(
    *,
    seed: int,
    budget: int,
    patience: int,
    theta_challenge: float,
    evaluate_fn: Callable[[Dict], EpisodeOutcome],
    space: Optional[SearchSpace] = None,
) -> SearchResult:
    """Seeded random search. `theta_challenge` is DERIVED by the caller from
    the pinned policy_config -- never a literal here (Decision 70's discipline).
    `evaluate_fn(params) -> EpisodeOutcome` owns the frozen detector."""
    space = space or SearchSpace()
    streams = {name: SubStream(seed, f"evade:{name}") for name in SEARCH_FIELDS}

    best_params: Optional[Dict] = None
    best_obj = float("-inf")
    since_improve = 0
    stopped_reason = "budget"
    trace: List[Dict] = []

    for iteration in range(budget):
        params = _sample_candidate(space, streams)
        outcome = evaluate_fn(params)
        obj = objective(outcome, theta_challenge)

        if outcome.incident_opened:
            rejected: Optional[str] = "incident_opened"
        elif outcome.mean_score_calibrated >= theta_challenge:
            rejected = (
                f"mean_score_calibrated {outcome.mean_score_calibrated:.6f} "
                f">= theta_challenge {theta_challenge:.6f}"
            )
        else:
            rejected = None

        trace.append({
            "iteration": iteration,
            "params": params,
            "mean_score_calibrated": outcome.mean_score_calibrated,
            "incident_opened": outcome.incident_opened,
            "cards_validated_per_hour": outcome.cards_validated_per_hour,
            "attempts_total": outcome.attempts_total,
            "objective": None if obj == float("-inf") else obj,
            "rejected_reason": rejected,
        })

        if obj > best_obj:
            best_obj = obj
            best_params = params
            since_improve = 0
        else:
            since_improve += 1

        if since_improve >= patience:
            stopped_reason = "patience"
            break

    return SearchResult(
        best_params=best_params,
        best_objective=best_obj,
        n_evaluated=len(trace),
        converged=best_params is not None,
        stopped_reason=stopped_reason,
        theta_challenge=theta_challenge,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# YAML-leaf writer -- the `evasive:` block for config/attack_tiers.yaml. Every
# `value` leaf carries an A10-passing `source` (>= 12 chars, matches
# SOURCE_SHAPE_RE, free of the banned vocabulary). The four inert parameters
# are carried at their hard-tier values with a source saying exactly that.
# ---------------------------------------------------------------------------

_CARRIED_FROM_HARD = {
    "foreign_bin_share": (900, "ppm"),
    "amount_sampler": ("baseline_low_tail", "mode"),
    "session_reuse": (0, "ppm"),
    "hour_of_day_placement": (0, "hour_of_day"),
}


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_evasive_yaml_text(params: Dict, *, seed: int, budget: int) -> str:
    r"""The `evasive:` block as YAML text, matching config/attack_tiers.yaml's
    existing {value, unit, source} style. `evasive` is the LAST block in the
    file, so scripts/search_evasive.py splices this in by replacing the tail
    after `\nevasive:` -- easy/medium/hard are left byte-for-byte."""
    aph = int(params["attempts_per_hour"])
    band = params["amount_quantile_band"]
    prov = f"seed {seed}, {budget} evaluations"

    def src(what: str) -> str:
        return (
            f"Eval Protocol v2 §5 -- {what}; converged value of the Tier-E "
            f"config-space search ({prov})"
        )

    band_lo = max(1, int(aph * 0.6))
    band_hi = int(aph * 1.6) + 1

    lines = ["evasive:"]
    lines += [
        "  attempts_per_hour:",
        f"    value: {aph}",
        "    unit: attempts_per_hour",
        f'    source: "{src("pacing that keeps mean(score_calibrated) below theta_challenge and opens no incident")}"',
        "  attempts_per_hour_band:",
        f"    min: {band_lo}",
        f"    max: {band_hi}",
        f'    source: "Eval Protocol v2 §5 -- advisory band bracketing the Tier-E converged rate ({prov}); jittered-even spacing keeps the recomputed rate inside it"',
        "  ip_pool_size:",
        f"    value: {int(params['ip_pool_size'])}",
        "    unit: count",
        f'    source: "{src("IP fan-out that keeps attempts_per_ip_60s under R1 threshold")}"',
        "  distinct_cards:",
        f"    value: {int(params['distinct_cards'])}",
        "    unit: count",
        f'    source: "{src("stolen-list size the adversary cycles through the merchant")}"',
        "  bin_pool_size:",
        f"    value: {int(params['bin_pool_size'])}",
        "    unit: count",
        f'    source: "{src("BIN spread that keeps distinct_cards_per_bin_5m under R3 threshold")}"',
        "  amount_quantile_band:",
        f"    min: {int(band['min'])}",
        f"    max: {int(band['max'])}",
        "    unit: permille_of_quantile_table",
        f'    source: "Eval Protocol v2 §4/V2 -- low-tail quantile band shared with the baseline table; Tier-E converged window ({prov})"',
        "  episode_duration_s:",
        f"    value: {int(params['episode_duration_s'])}",
        "    unit: seconds",
        f'    source: "{src("episode length over which cards_validated_per_hour is maximised")}"',
    ]
    for name, (value, unit) in _CARRIED_FROM_HARD.items():
        lines += [
            f"  {name}:",
            f"    value: {_yaml_scalar(value)}",
            f"    unit: {unit}",
            '    source: "Day-7 Plan §6 -- carried at the hard-tier value; not consumed by generate_attack_episode, so it is not searched (Decision 92)"',
        ]
    return "\n".join(lines) + "\n"
