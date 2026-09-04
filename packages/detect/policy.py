"""
Source: Threat Model v2 §4/P1 and Day-6 Plan §3.5 / §3.6 -- the policy
engine. Turns `p_calibrated` + Layer-2 evidence + the R1-R3 rule floor into
an ENTITY-SCOPED, cost-derived, hysteresis-damped, blast-radius-capped
enforcement proposal that can never automatically exceed `challenge`.

Day 1 shipped only `apply_auto_ceiling` here (Threat Model §4/P1's ceiling
mechanism); it is unchanged and still called. Everything else is Day 6.

PURE: no I/O, no wall clock, no `eval` import, no ground-truth label source
(tests/acceptance/test_detect_label_isolation.py). `PolicySnapshot` /
`StoreBaseline` are loaded by packages/storage/repository.py and passed in;
the cost-derived threshold ladder is read from `PolicySnapshot.thresholds`
(a JSON column populated at seed/tune time from `eval/cost.py`), so the
serving path takes no dependency on `eval/`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from packages.contracts.decision import Decision

# ---------------------------------------------------------------------------
# Auto-ceiling (Day 1, unchanged) -- Threat Model v2 §4/P1
# ---------------------------------------------------------------------------

AUTO_CEILING = Decision.CHALLENGE

_ORDER = [
    Decision.ALLOW,
    Decision.MONITOR,
    Decision.THROTTLE,
    Decision.CHALLENGE,
    Decision.STEP_UP,
    Decision.BLOCK,
]


def _rank(tier: Decision) -> int:
    return _ORDER.index(tier)


def apply_auto_ceiling(tier: Decision, ceiling: Decision = AUTO_CEILING) -> Decision:
    if _rank(tier) > _rank(ceiling):
        return ceiling
    return tier


def tier_max(a: Decision, b: Decision) -> Decision:
    """Rules set a FLOOR, never a ceiling (TRD §6.10) -- max in ladder order."""
    return a if _rank(a) >= _rank(b) else b


# ---------------------------------------------------------------------------
# Threshold ladder (Day-6 Plan §3.6.1 / §3.6.2) -- AFA-aware
# ---------------------------------------------------------------------------

# Source: Day-6 Plan §3.6.1 / TRD §6.7 / Threat Model §7a -- for a
# domestic-issued BIN, AFA (additional factor of authentication) already
# binds, so forcing 3-D Secure (`step_up`) is not an escalation. The
# domestic ladder drops it; the foreign ladder keeps it.
LADDER_DOMESTIC: Tuple[str, ...] = ("throttle", "challenge", "block")
LADDER_FOREIGN: Tuple[str, ...] = ("throttle", "challenge", "step_up", "block")


def select_ladder(bin_is_foreign_issued: float) -> str:
    """`bin_is_foreign_issued` is 0.0 for every live event today
    (bin_metadata has 0 rows -- Day-6 Plan risk 3); this returns "domestic"
    in practice and is exercised as a pure function on a synthetic foreign
    BIN by test_ladder_selection.py."""
    return "foreign" if bin_is_foreign_issued and bin_is_foreign_issued > 0.5 else "domestic"


def ladder_tiers(ladder: str) -> Tuple[str, ...]:
    return LADDER_FOREIGN if ladder == "foreign" else LADDER_DOMESTIC


def tier_from_score(p: float, thresholds: Dict[str, float], ladder: str) -> Decision:
    """
    Source: Day-6 Plan §3.6.2 -- the highest ladder tier whose theta_T the
    posterior clears. Below the lowest rung (theta_throttle) Layer 2 is in a
    watching posture, so the floor of the Layer-2 contribution is `monitor`,
    never `allow` -- `allow` is reserved for "no incident at all", handled by
    the caller.
    """
    best = Decision.MONITOR
    for tier_name in ladder_tiers(ladder):
        theta = thresholds.get(tier_name)
        if theta is None:
            continue
        if p >= theta:
            cand = Decision(tier_name)
            if _rank(cand) > _rank(best):
                best = cand
    return best


# ---------------------------------------------------------------------------
# Entity resolution (Day-6 Plan §3.5) -- TRD §6.7 "entity-scoped, never
# store-wide -- enforced in the schema, not just in code"
# ---------------------------------------------------------------------------

_ENTITY_TYPES = frozenset({"card", "ipua", "ip", "bin"})


@dataclass(frozen=True)
class EntityKey:
    """A resolved enforcement target. Store-wide enforcement is not merely
    forbidden, it is UNREPRESENTABLE: `entity_type` is a closed set and
    `entity_key` is a non-empty, non-whitespace string, both checked here
    and (again) by a schema CHECK constraint."""

    entity_type: str
    entity_key: str

    def __post_init__(self) -> None:
        if self.entity_type not in _ENTITY_TYPES:
            raise ValueError(
                f"entity_type {self.entity_type!r} not in {sorted(_ENTITY_TYPES)}"
            )
        if not isinstance(self.entity_key, str) or not self.entity_key.strip():
            raise ValueError("entity_key must be a non-empty, non-whitespace string")

    def as_tuple(self) -> Tuple[str, str]:
        return (self.entity_type, self.entity_key)


def ipua_hash(ip: str, ua_class: str) -> str:
    """sha1(ip || ua_class) -- the class, never the raw UA string (TRD §6.2).
    Mirrors packages.features.compute.ipua_key; duplicated (not imported) to
    keep policy.py's dependency surface to contracts only."""
    return hashlib.sha1(f"{ip}|{ua_class}".encode("utf-8")).hexdigest()


def resolve_entity(
    *,
    scope: str,
    ip: str,
    ua_class: str,
    card_hash: Optional[str] = None,
    bin: Optional[str] = None,
) -> EntityKey:
    """
    Source: Day-6 Plan §3.5 / TRD §6.2 rule 2 -- the NARROWEST key that
    covers the evidence:  card_hash -> (ip, ua_class) -> ip.  Never `asn`
    alone (that is not even an argument here). `bin` is available for a
    detector whose evidence is issuer-wide (R3 geometry), never as a
    fallback for a source-fan-out signal.

    Only S/M-class identifiers participate. C-class fields (`event_id`, raw
    `user_agent`, the `client_evidence` blob) have no path into this
    function -- they are not parameters.
    """
    if scope == "card":
        if card_hash and card_hash.strip():
            return EntityKey("card", card_hash)
        scope = "ipua"  # card evidence but no card hash -> narrow to ipua
    if scope == "bin":
        if bin and bin.strip():
            return EntityKey("bin", bin)
        scope = "ipua"
    if scope == "ipua":
        if ip and ip.strip() and ua_class:
            return EntityKey("ipua", ipua_hash(ip, ua_class))
        scope = "ip"
    if not (ip and ip.strip()):
        raise ValueError("resolve_entity: no S/M-class identifier available to scope enforcement")
    return EntityKey("ip", ip)


# ---------------------------------------------------------------------------
# P3 corroboration (Threat Model §4/P3) -- Day-6 Plan §3.6.3
# ---------------------------------------------------------------------------

# Source: Day-6 Plan §3.6.3 -- FEATURE_NAMES -> feature family. Layer-2-driven
# enforcement above `monitor` needs non-neutral evidence from >=2 of these
# families across >=2 CUSUM buckets. The `amount` and `decline_composition`
# families are largely inert until the store-relative quantiles (Decision 16)
# and /v1/outcome (Day 7) land; that is stated, not hidden.
FEATURE_FAMILY: Dict[str, str] = {
    "attempts_per_ip_60s": "velocity",
    "attempts_per_ip_5m": "velocity",
    "attempts_per_ipua_5m": "velocity",
    "attempts_per_session": "velocity",
    "distinct_cards_per_ip_5m_q": "velocity",
    "distinct_cards_per_ipua_5m_q": "velocity",
    "distinct_bins_per_ip_5m": "bin_structure",
    "distinct_ips_per_bin_5m": "bin_structure",
    "distinct_cards_per_bin_5m": "bin_structure",
    "bin_hhi_5m": "bin_structure",
    "bin_entropy_5m": "bin_structure",
    "bin_is_foreign_issued": "bin_structure",
    "foreign_bin_share_5m": "bin_structure",
    "foreign_bin_share_sigma": "bin_structure",
    "card_seen_24h": "velocity",
    "amount_percentile_vs_store": "amount",
    "distinct_amounts_per_ip_5m": "amount",
    "store_volume_deviation_sigma": "velocity",
    "store_decline_rate_deviation_sigma": "decline_composition",
    "decline_rate_per_ip_5m": "decline_composition",
    "invalid_cvv_share_ip_5m": "decline_composition",
    "outcome_coverage_ratio": "decline_composition",
    "event_id_reuse_count": "velocity",
    "clock_skew_s": "velocity",
}

# Source: Day-6 Plan §3.6.3 -- a rule fire is the strongest per-family
# non-neutral signal available today (the `_q`/`sigma`/decline features are
# still neutral -- Decision 16/64). R1/R2 are source-fan-out velocity; R3 is
# issuer-fan-out bin structure (test_rules_geometry.py's inverse geometry).
RULE_FAMILY: Dict[str, str] = {
    "attempts_per_ip_60s": "velocity",
    "distinct_cards_per_ip_5m": "velocity",
    "distinct_cards_per_bin_5m": "bin_structure",
}


def families_from_rules(fired_names) -> frozenset:
    return frozenset(RULE_FAMILY[n] for n in (fired_names or ()) if n in RULE_FAMILY)


# ---------------------------------------------------------------------------
# Snapshots and outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySnapshot:
    """Source: Day-6 Plan §3.6 -- a frozen view of one `policy_config`
    version. `Incident.pinned_policy_version` pins this at open; every later
    tier resolution for that incident reads the pinned version, never the
    live one (Backend Schema §3.1)."""

    version: int
    thresholds: Dict[str, float]     # {tier -> theta_T}, from CostModel.tier_ladder()
    hysteresis_gap: float
    cooldown_seconds: int
    cusum_rho: float
    cusum_h: float
    cusum_bucket_s: int
    drift_window_s: int
    allow_auto_block: bool
    auto_ceiling: str
    k_max_entities: int
    control_fraction: float
    rules_config: dict = field(default_factory=dict)

    @property
    def auto_ceiling_tier(self) -> Decision:
        return Decision(self.auto_ceiling)


@dataclass(frozen=True)
class PolicyOutcome:
    """Source: Day-6 Plan §3.10 -- what `resolve()` returns to the seam."""

    proposed_tier: Decision      # what the evidence supports (may exceed the ceiling)
    in_force_tier: Decision      # what is actually applied (<= auto_ceiling; == allow for control)
    entity: EntityKey
    control_arm: bool
    tier_ladder: str             # "domestic" | "foreign"
    regime: str                  # "in_control" | "alarm"
    prior_used: float
    advisory_mode: bool
    requires_confirmation: bool  # True for step_up / block (proposed, never in force)
    corroborated: bool


# ---------------------------------------------------------------------------
# Control arm (Eval Protocol §6.1) -- Day-6 Plan §3.9
# ---------------------------------------------------------------------------


def control_block_size(control_fraction: float) -> int:
    """N = round(1 / control_fraction); 20 at the 0.05 default."""
    if control_fraction <= 0.0:
        return 0
    return max(1, round(1.0 / control_fraction))


def control_position(merchant_id: str, policy_version: int, block: int, n: int) -> int:
    digest = hashlib.sha256(f"{merchant_id}:{policy_version}:{block}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % n


def is_control_ordinal(
    *, eligible_ordinal: int, merchant_id: str, policy_version: int, control_fraction: float
) -> bool:
    """
    Source: Day-6 Plan §3.9 -- exactly one position per consecutive block of
    N enforcement-eligible attempts is chosen pseudo-randomly from the seed
    (merchant_id + pinned policy_version). Exactly `control_fraction` up to
    the trailing partial block, seeded, bit-for-bit reproducible.
    """
    n = control_block_size(control_fraction)
    if n <= 0:
        return False
    block = eligible_ordinal // n
    j = control_position(merchant_id, policy_version, block, n)
    return (eligible_ordinal % n) == j


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class PolicyEngine:
    """
    Stateful per-merchant policy resolver. The ONLY mutable state is:
      * `_current_tier`     -- per-entity, for hysteresis
      * `_eligible_ordinal` -- per-merchant enforcement-eligible counter, for
        the deterministic control arm
    Both are cleared by `clear()` (wired into ReplayDriver.reset(), Day-6
    Plan critical constraint -- "clear all new in-process state").
    """

    def __init__(self) -> None:
        self._current_tier: Dict[Tuple[str, str], Decision] = {}
        self._eligible_ordinal: Dict[str, int] = {}
        # Source: Day-8 Plan Step 6 -- a per-entity ceiling an operator has
        # EXPLICITLY confirmed on D3. Empty by default, so the ceiling is still
        # `snapshot.auto_ceiling_tier` (challenge) for every entity no operator
        # has touched (Threat Model §4/P1). In-memory dict lookup on the hot
        # path -- no I/O, no latency change. Cleared by `clear()`
        # (ReplayDriver.reset) and per-entity by `clear_confirmed_ceiling`
        # (D3 "This was legitimate").
        self._confirmed_ceiling: Dict[Tuple[str, str], Decision] = {}

    def clear(self) -> None:
        self._current_tier.clear()
        self._eligible_ordinal.clear()
        self._confirmed_ceiling.clear()

    def set_confirmed_ceiling(self, entity: EntityKey, tier: Decision) -> None:
        """An operator confirmed `tier` for `entity` on D3 -- raise its ceiling
        so subsequent attempts from it resolve at the confirmed tier."""
        self._confirmed_ceiling[entity.as_tuple()] = tier

    def clear_confirmed_ceiling(self, entity: EntityKey) -> None:
        """The incident was resolved -- drop the confirmed ceiling so `entity`
        returns to the `challenge` auto-ceiling on subsequent attempts."""
        self._confirmed_ceiling.pop(entity.as_tuple(), None)

    def current_tier(self, entity: EntityKey) -> Decision:
        return self._current_tier.get(entity.as_tuple(), Decision.ALLOW)

    def _apply_hysteresis(
        self, entity: EntityKey, target: Decision, p: float, snapshot: PolicySnapshot
    ) -> Decision:
        """
        Source: Day-6 Plan §3.6.5 / D7 -- rise to T requires p >= theta_T
        (already true by construction of `target`); fall below T requires
        p < theta_T - hysteresis_gap. An oscillation inside
        [theta_T - gap, theta_T] therefore produces ONE tier change.
        Applies only to the score-driven Layer-2 tier; R1-R3 floors are
        unconditional (Decision 17) and are max'd in afterwards.
        """
        key = entity.as_tuple()
        current = self._current_tier.get(key, Decision.ALLOW)
        if _rank(target) > _rank(current):
            new = target
        elif _rank(target) < _rank(current):
            theta_current = snapshot.thresholds.get(current.value)
            if theta_current is None or p < theta_current - snapshot.hysteresis_gap:
                new = target
            else:
                new = current  # hold -- still inside the hysteresis band
        else:
            new = current
        self._current_tier[key] = new
        return new

    def resolve(
        self,
        *,
        merchant_id: str,
        p_calibrated: float,
        evaluation,
        entity: EntityKey,
        snapshot: PolicySnapshot,
        incident_open: bool,
        corroborated: bool,
        active_enforced_count: int,
        bin_is_foreign_issued: float = 0.0,
        regime: str = "in_control",
        prior_used: float,
    ) -> PolicyOutcome:
        ladder = select_ladder(bin_is_foreign_issued)
        rule_floor: Decision = evaluation.minimum_tier

        # Captured BEFORE hysteresis touches _current_tier: was this entity
        # already under enforcement coming into this attempt? (K_max, step 6.)
        entity_already_enforced = self.current_tier(entity) != Decision.ALLOW

        # 1. Layer-2 score-driven tier -- only when an incident is live for
        #    this entity; otherwise Layer 2 contributes nothing and the
        #    decision is exactly Day 5's (apply_auto_ceiling(rule_floor)).
        if incident_open:
            l2_tier = tier_from_score(p_calibrated, snapshot.thresholds, ladder)
            # 2. P3 corroboration -- uncorroborated Layer-2 evidence is
            #    capped at `monitor` (Threat Model §4/P3). R1-R3 floors are
            #    exempt (they are `rule_floor`, max'd in at step 4).
            if not corroborated and _rank(l2_tier) > _rank(Decision.MONITOR):
                l2_tier = Decision.MONITOR
            # 3. Hysteresis on the score-driven tier.
            l2_tier = self._apply_hysteresis(entity, l2_tier, p_calibrated, snapshot)
        else:
            l2_tier = Decision.ALLOW
            self._current_tier.pop(entity.as_tuple(), None)

        # 4. Rule floor -- rules raise, never lower (TRD §6.10).
        proposed = tier_max(l2_tier, rule_floor)

        # 5. Auto-ceiling (P1). step_up / block are PROPOSED, never in force --
        #    UNLESS an operator has explicitly confirmed a higher ceiling for
        #    THIS entity on D3 (Day-8 Plan Step 6). The default is still
        #    `snapshot.auto_ceiling_tier` (challenge) for every entity no
        #    operator has touched; only an explicit confirmation raises it, and
        #    resolving the incident clears it again.
        ceiling = self._confirmed_ceiling.get(entity.as_tuple(), snapshot.auto_ceiling_tier)
        in_force = apply_auto_ceiling(proposed, ceiling)
        requires_confirmation = _rank(proposed) > _rank(ceiling)

        # 6. K_max / advisory mode (P2). At the cap, stop issuing NEW
        #    enforcement on NEW entities; keep scoring; keep entities already
        #    under enforcement (entity_already_enforced captured pre-hysteresis).
        advisory_mode = (
            active_enforced_count >= snapshot.k_max_entities
            and not entity_already_enforced
        )
        if advisory_mode:
            # roll back the hysteresis memory -- a NEW entity at the cap is
            # not being enforced, so it must not read as "enforced" next time.
            self._current_tier.pop(entity.as_tuple(), None)

        # 7. Control arm + advisory mode both pass the attempt UNENFORCED,
        #    including past the R1-R3 floors (Day-6 Plan D10 -- an enforced
        #    "control" is not a control; Eval Protocol §6.1 unbiasedness).
        eligible = _rank(in_force) > _rank(Decision.ALLOW) and not advisory_mode
        control_arm = False
        if eligible:
            ordinal = self._eligible_ordinal.get(merchant_id, 0)
            control_arm = is_control_ordinal(
                eligible_ordinal=ordinal,
                merchant_id=merchant_id,
                policy_version=snapshot.version,
                control_fraction=snapshot.control_fraction,
            )
            self._eligible_ordinal[merchant_id] = ordinal + 1

        if advisory_mode or control_arm:
            in_force = Decision.ALLOW

        return PolicyOutcome(
            proposed_tier=proposed,
            in_force_tier=in_force,
            entity=entity,
            control_arm=control_arm,
            tier_ladder=ladder,
            regime=regime,
            prior_used=prior_used,
            advisory_mode=advisory_mode,
            requires_confirmation=requires_confirmation,
            corroborated=corroborated,
        )
