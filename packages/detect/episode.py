"""
Source: Day-6 Plan §3.3 -- the incident episode state machine, the declared
replacement for the Day-2 stand-in `packages/detect/threat_state.py`
(Decision 33).

    IncidentState = OPEN | ESCALATED | COOLING | CLOSED

A pure fold over `ingest_ms`: the machine holds no end-of-stream assumption,
so feeding a stream in two halves against a warm registry yields ONE
incident (M8 at incident level -- tests/acceptance/test_episode_state_machine.py
and test_metamorphic.py).

PURE: no I/O, no wall clock, no `eval` import, no label source. `ingest_ms`
and every parameter arrive as arguments; the registry is cleared by
`clear()` (wired into ReplayDriver.reset()).

Day-7 Plan §3 R3 / §12 trap 9 -- the caller (`services/scorer/scoring.py::
_resolve_layer2`) that folds these transitions runs with NO `await` inside
the block. The 100-concurrent-vs-sequential CUSUM guarantee
(tests/acceptance/test_concurrent_cusum.py) depends on that; never add an
`await` to the Layer-2 resolution path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from packages.contracts.decision import Decision
from packages.detect.policy import EntityKey, _rank

# Source: Day-6 Plan §3.3 -- threat_state continuity. The four strings and
# the SSE key are unchanged from Day 2 (services/dashboard/src/App.jsx,
# test_day2_e2e.py keep passing).
_THREAT_STATE = {
    None: "calm",
    "CLOSED": "calm",
    "OPEN": "elevated",
    "ESCALATED": "under_attack",
    "COOLING": "resolved",
}


class IncidentState(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    COOLING = "COOLING"
    CLOSED = "CLOSED"


# Source: Day-6 Plan §3.3 -- CLOSED is terminal; any transition out of it
# raises. `CLOSED -> ESCALATED` is the named test case.
_ALLOWED: Dict[IncidentState, Set[IncidentState]] = {
    IncidentState.OPEN: {IncidentState.OPEN, IncidentState.ESCALATED, IncidentState.COOLING},
    IncidentState.ESCALATED: {IncidentState.ESCALATED, IncidentState.COOLING},
    IncidentState.COOLING: {
        IncidentState.OPEN, IncidentState.ESCALATED, IncidentState.COOLING, IncidentState.CLOSED,
    },
    IncidentState.CLOSED: set(),
}


class IllegalTransition(Exception):
    pass


def threat_state_for(state: Optional[str]) -> str:
    return _THREAT_STATE.get(state, "calm")


def _incident_id(merchant_id: str, entity: EntityKey, opened_at: int) -> str:
    """Deterministic so the drainer's byte-0 re-drain is idempotent
    (upsert_incident ON CONFLICT DO UPDATE -- Day-6 Plan §3.4)."""
    raw = f"{merchant_id}|{entity.entity_type}|{entity.entity_key}|{opened_at}"
    return "I" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:25].upper()


def _transition_id(incident_id: str, ordinal: int) -> str:
    return "T" + hashlib.sha1(f"{incident_id}|{ordinal}".encode("utf-8")).hexdigest()[:25].upper()


@dataclass
class TierTransition:
    from_tier: Optional[str]
    to_tier: str
    trigger: str
    signal_value: Optional[float]
    at: int


@dataclass
class Incident:
    incident_id: str
    merchant_id: str
    entity: EntityKey
    state: IncidentState
    detector: str                      # "cusum" | "drift" | "both"
    opened_at: int
    pinned_policy_version: int
    escalated_at: Optional[int] = None
    cooling_at: Optional[int] = None
    closed_at: Optional[int] = None
    peak_tier: str = Decision.MONITOR.value
    attempts_total: int = 0
    attempts_before_alert: Optional[int] = None
    cards_exposed_before_alert: Optional[int] = None
    time_to_detect_s: Optional[float] = None
    cusum_stat_at_alert: Optional[float] = None
    resolution: Optional[str] = None
    resolved_by: Optional[str] = None
    # Source: Day-7 Plan §4 Step 6 -- the incident narrative + its source
    # ("template" on Day 7; "gemini" is Day 8). Populated at incident-open by
    # _resolve_layer2 from a build_bundle() -> assemble_prompt() gate ->
    # template.render() render; the columns already exist (schema.sql:178-179).
    narrative: Optional[str] = None
    narrative_source: Optional[str] = None
    # internal bookkeeping (not persisted directly)
    last_fire_ms: int = 0
    cooldown_ms: int = 300_000
    transitions: List[TierTransition] = field(default_factory=list)
    families_by_bucket: Dict[int, Set[str]] = field(default_factory=dict)
    entity_first_seen: int = 0
    entity_last_seen: int = 0

    # -- derived -----------------------------------------------------------

    def threat_state(self) -> str:
        return threat_state_for(self.state.value)

    def corroborated(self) -> bool:
        """Source: Threat Model §4/P3 -- >=2 independent feature families
        across >=2 CUSUM buckets."""
        buckets_with_evidence = [b for b, fams in self.families_by_bucket.items() if fams]
        all_families: Set[str] = set()
        for fams in self.families_by_bucket.values():
            all_families |= fams
        return len(buckets_with_evidence) >= 2 and len(all_families) >= 2

    def is_live(self) -> bool:
        return self.state != IncidentState.CLOSED

    # -- persistence rows -------------------------------------------------

    def to_row(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "merchant_id": self.merchant_id,
            "state": self.state.value,
            "detector": self.detector,
            "opened_at": self.opened_at,
            "escalated_at": self.escalated_at,
            "cooling_at": self.cooling_at,
            "closed_at": self.closed_at,
            "peak_tier": self.peak_tier,
            "attempts_total": self.attempts_total,
            "attempts_before_alert": self.attempts_before_alert,
            "cards_exposed_before_alert": self.cards_exposed_before_alert,
            "time_to_detect_s": self.time_to_detect_s,
            "cusum_stat_at_alert": self.cusum_stat_at_alert,
            "decline_mix": None,
            "narrative": self.narrative,
            "narrative_source": self.narrative_source,
            "recommended_tier": self.peak_tier,
            "resolution": self.resolution,
            "resolved_by": self.resolved_by,
            "pinned_policy_version": self.pinned_policy_version,
        }

    def entity_row(self, pseudonym: str) -> dict:
        return {
            "incident_id": self.incident_id,
            "entity_type": self.entity.entity_type,
            "entity_key": self.entity.entity_key,
            "pseudonym": pseudonym,
            "attempt_count": self.attempts_total,
            "first_seen": self.entity_first_seen or self.opened_at,
            "last_seen": self.entity_last_seen or self.opened_at,
        }

    def transition_rows(self) -> List[dict]:
        rows = []
        for i, tr in enumerate(self.transitions):
            rows.append({
                "transition_id": _transition_id(self.incident_id, i),
                "incident_id": self.incident_id,
                "from_tier": tr.from_tier,
                "to_tier": tr.to_tier,
                "trigger": tr.trigger,
                "signal_value": tr.signal_value,
                "at": tr.at,
            })
        return rows


@dataclass(frozen=True)
class DetectorSignal:
    """What Layer2Engine hands the registry for one attempt."""

    fired: bool
    detector: str                 # "cusum" | "drift" | "none"
    cusum_stat: float
    signal_value: float           # rate_ratio (cusum) or Lambda (drift) -- tier_transition.signal_value
    cusum_bucket_index: int
    families: frozenset            # rule families with non-neutral evidence this attempt
    entity_first_seen_ms: int
    attempts_on_entity: int       # count on the entity BEFORE this attempt
    cards_on_entity: int          # distinct cards on the entity BEFORE this attempt


class IncidentRegistry:
    """`Dict[merchant_id -> Dict[entity_tuple -> Incident]]`. Re-fire during
    cooldown resolves to the same key -> the same `Incident` object -> merge,
    not a second row (Day-6 Plan §3.3)."""

    def __init__(self) -> None:
        self._by_merchant: Dict[str, Dict[Tuple[str, str], Incident]] = {}
        self._pseudonyms: Dict[str, Dict[Tuple[str, str], str]] = {}

    def clear(self) -> None:
        self._by_merchant.clear()
        self._pseudonyms.clear()

    # -- queries --------------------------------------------------------

    def live_incident(self, merchant_id: str, entity: EntityKey) -> Optional[Incident]:
        inc = self._by_merchant.get(merchant_id, {}).get(entity.as_tuple())
        if inc is not None and inc.is_live():
            return inc
        return None

    def all_incidents(self) -> List[Incident]:
        out: List[Incident] = []
        for by_entity in self._by_merchant.values():
            out.extend(by_entity.values())
        return out

    def worst_threat_state(self, merchant_id: str) -> str:
        """Store-wide D1 threat band -- the most severe threat_state across
        every live incident for the merchant (Day-6 Plan §3.3). `calm` when
        nothing is live."""
        order = {"calm": 0, "resolved": 1, "elevated": 2, "under_attack": 3}
        worst = "calm"
        for inc in self._by_merchant.get(merchant_id, {}).values():
            ts = inc.threat_state()
            if order.get(ts, 0) > order.get(worst, 0):
                worst = ts
        return worst

    def active_enforced_entities(self, merchant_id: str) -> int:
        """Distinct entities with a live (non-CLOSED) incident whose peak_tier
        is above `allow` -- the K_max blast-radius count (Threat Model §4/P2).
        A live enforcement_action is 1:1 with this on the single-worker demo."""
        n = 0
        for inc in self._by_merchant.get(merchant_id, {}).values():
            if inc.is_live() and _rank(Decision(inc.peak_tier)) > _rank(Decision.ALLOW):
                n += 1
        return n

    def pseudonym(self, merchant_id: str, entity: EntityKey) -> str:
        book = self._pseudonyms.setdefault(merchant_id, {})
        key = entity.as_tuple()
        if key not in book:
            same_type = len([k for k in book if k[0] == entity.entity_type])
            book[key] = f"{entity.entity_type}_{same_type + 1}"
        return book[key]

    # -- the machine --------------------------------------------------

    def _sweep(self, merchant_id: str, now_ms: int, cooldown_ms: int) -> None:
        for inc in self._by_merchant.get(merchant_id, {}).values():
            if inc.state in (IncidentState.OPEN, IncidentState.ESCALATED):
                if now_ms - inc.last_fire_ms >= cooldown_ms:
                    inc.cooling_at = inc.last_fire_ms + cooldown_ms
                    self._set_state(inc, IncidentState.COOLING)
            if inc.state == IncidentState.COOLING and inc.cooling_at is not None:
                if now_ms - inc.cooling_at >= cooldown_ms:
                    inc.closed_at = inc.cooling_at + cooldown_ms
                    inc.resolution = "auto"
                    inc.resolved_by = "auto"
                    self._set_state(inc, IncidentState.CLOSED)

    def _set_state(self, inc: Incident, new: IncidentState) -> None:
        if new == inc.state:
            return
        if new not in _ALLOWED[inc.state]:
            raise IllegalTransition(f"{inc.state.value} -> {new.value} is not a legal incident transition")
        inc.state = new
        if new == IncidentState.ESCALATED and inc.escalated_at is None:
            inc.escalated_at = inc.last_fire_ms

    def flush(self, merchant_id: str, now_ms: int, cooldown_ms: int) -> None:
        """End-of-stream sweep so COOLING incidents reach CLOSED deterministically."""
        self._sweep(merchant_id, now_ms, cooldown_ms)

    def step(
        self,
        *,
        merchant_id: str,
        entity: EntityKey,
        ingest_ms: int,
        signal: DetectorSignal,
        cooldown_seconds: int,
        pinned_policy_version: int,
    ) -> Optional[Incident]:
        cooldown_ms = int(cooldown_seconds) * 1000
        self._sweep(merchant_id, ingest_ms, cooldown_ms)

        book = self._by_merchant.setdefault(merchant_id, {})
        inc = book.get(entity.as_tuple())

        if inc is not None and inc.is_live():
            inc.attempts_total += 1
            inc.entity_last_seen = ingest_ms
            inc.cooldown_ms = cooldown_ms
            if signal.families:
                inc.families_by_bucket.setdefault(signal.cusum_bucket_index, set()).update(signal.families)
            if signal.fired:
                inc.last_fire_ms = ingest_ms
                if inc.state == IncidentState.COOLING:
                    inc.cooling_at = None
                    self._set_state(inc, IncidentState.OPEN)
                if signal.detector != "none" and signal.detector not in inc.detector:
                    inc.detector = "both"
                    self._maybe_escalate(inc, ingest_ms, "second_detector", signal.signal_value)
                if inc.cusum_stat_at_alert is None:
                    inc.cusum_stat_at_alert = signal.cusum_stat
            return inc

        if signal.fired:
            inc = Incident(
                incident_id=_incident_id(merchant_id, entity, ingest_ms),
                merchant_id=merchant_id,
                entity=entity,
                state=IncidentState.OPEN,
                detector=signal.detector if signal.detector != "none" else "cusum",
                opened_at=ingest_ms,
                pinned_policy_version=pinned_policy_version,
                cusum_stat_at_alert=signal.cusum_stat,
                attempts_before_alert=int(signal.attempts_on_entity),
                cards_exposed_before_alert=int(signal.cards_on_entity),
                time_to_detect_s=(
                    (ingest_ms - signal.entity_first_seen_ms) / 1000.0
                    if signal.entity_first_seen_ms
                    else 0.0
                ),
                last_fire_ms=ingest_ms,
                cooldown_ms=cooldown_ms,
                entity_first_seen=signal.entity_first_seen_ms or ingest_ms,
                entity_last_seen=ingest_ms,
            )
            inc.attempts_total = 1
            inc.transitions.append(
                TierTransition(None, Decision.MONITOR.value, f"open:{inc.detector}", signal.signal_value, ingest_ms)
            )
            if signal.families:
                inc.families_by_bucket.setdefault(signal.cusum_bucket_index, set()).update(signal.families)
            book[entity.as_tuple()] = inc
            return inc

        return None

    def note_tier(
        self, inc: Incident, proposed_tier: Decision, ingest_ms: int, trigger: str, signal_value: float
    ) -> None:
        """Record a tier transition after the policy engine resolves. Raises
        IllegalTransition if the incident is already CLOSED."""
        if inc.state == IncidentState.CLOSED:
            raise IllegalTransition("cannot record a tier transition on a CLOSED incident")
        prev = inc.peak_tier
        if _rank(proposed_tier) > _rank(Decision(prev)):
            inc.transitions.append(
                TierTransition(prev, proposed_tier.value, trigger, signal_value, ingest_ms)
            )
            inc.peak_tier = proposed_tier.value
            self._maybe_escalate(inc, ingest_ms, trigger, signal_value)

    def _maybe_escalate(self, inc: Incident, ingest_ms: int, trigger: str, signal_value: float) -> None:
        if inc.state == IncidentState.OPEN:
            inc.escalated_at = ingest_ms
            self._set_state(inc, IncidentState.ESCALATED)
