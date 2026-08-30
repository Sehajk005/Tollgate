"""
Source: Day-6 Plan §4 -- the incident state-machine gate (Impl Plan Day 6).

  * CLOSED -> ESCALATED raises IllegalTransition  (the named test case)
  * a re-fire during cooldown MERGES -- one incident_id, not two
  * two entities hold overlapping incidents with independent cooldown timers
  * an episode fed in two halves against a warm registry yields ONE incident
    (M8 at incident level)
"""

from __future__ import annotations

import pytest

from packages.contracts.decision import Decision
from packages.detect.episode import DetectorSignal, IllegalTransition, IncidentRegistry, IncidentState
from packages.detect.policy import EntityKey

COOLDOWN_S = 300
COOLDOWN_MS = COOLDOWN_S * 1000
PINNED_V = 1


def _sig(fired=True, detector="cusum", bucket=0, families=frozenset({"velocity", "bin_structure"}),
         first_seen=0, attempts=0, cards=0, cusum_stat=300.0, signal_value=5.0):
    return DetectorSignal(
        fired=fired, detector=detector, cusum_stat=cusum_stat, signal_value=signal_value,
        cusum_bucket_index=bucket, families=families, entity_first_seen_ms=first_seen,
        attempts_on_entity=attempts, cards_on_entity=cards,
    )


def _step(reg, entity, ingest_ms, signal):
    return reg.step(
        merchant_id="m", entity=entity, ingest_ms=ingest_ms, signal=signal,
        cooldown_seconds=COOLDOWN_S, pinned_policy_version=PINNED_V,
    )


class TestEpisodeStateMachine:
    def test_closed_incident_rejects_any_further_transition(self):
        reg = IncidentRegistry()
        e = EntityKey("ip", "203.0.113.7")
        inc = _step(reg, e, 0, _sig())
        assert inc.state == IncidentState.OPEN
        _step(reg, EntityKey("ip", "9.9.9.9"), 3 * COOLDOWN_MS, _sig(fired=False, detector="none"))
        assert inc.state == IncidentState.CLOSED
        with pytest.raises(IllegalTransition):
            reg.note_tier(inc, Decision.CHALLENGE, 3 * COOLDOWN_MS, "policy", 9.0)

    def test_refire_during_cooldown_merges_into_the_same_incident(self):
        reg = IncidentRegistry()
        e = EntityKey("ip", "203.0.113.7")
        first = _step(reg, e, 0, _sig())
        first_id = first.incident_id
        cooling = _step(reg, e, COOLDOWN_MS + 1000, _sig(fired=False, detector="none"))
        assert cooling.incident_id == first_id
        assert cooling.state == IncidentState.COOLING
        refire = _step(reg, e, COOLDOWN_MS + 20_000, _sig())
        assert refire.incident_id == first_id
        assert refire.state == IncidentState.OPEN
        assert len(reg.all_incidents()) == 1

    def test_two_entities_hold_independent_overlapping_incidents(self):
        reg = IncidentRegistry()
        a = EntityKey("ip", "1.1.1.1")
        b = EntityKey("ip", "2.2.2.2")
        ia = _step(reg, a, 0, _sig())
        ib = _step(reg, b, 5_000, _sig())
        assert ia.incident_id != ib.incident_id
        _step(reg, b, COOLDOWN_MS + 10_000, _sig())
        _step(reg, a, COOLDOWN_MS + 10_000, _sig(fired=False, detector="none"))
        assert ia.state == IncidentState.COOLING
        assert ib.state in (IncidentState.OPEN, IncidentState.ESCALATED)
        assert len(reg.all_incidents()) == 2

    def test_episode_fed_in_two_halves_is_one_incident(self):
        reg = IncidentRegistry()
        e = EntityKey("ip", "198.51.100.5")
        half1 = [(i * 5_000, _sig(bucket=i // 2)) for i in range(6)]
        half2 = [(30_000 + i * 5_000, _sig(bucket=6 + i // 2)) for i in range(6)]
        for t, s in half1:
            _step(reg, e, t, s)
        ids_after_half1 = {inc.incident_id for inc in reg.all_incidents()}
        for t, s in half2:
            _step(reg, e, t, s)
        assert {inc.incident_id for inc in reg.all_incidents()} == ids_after_half1
        assert len(reg.all_incidents()) == 1

    def test_second_detector_escalates(self):
        reg = IncidentRegistry()
        e = EntityKey("ip", "203.0.113.7")
        inc = _step(reg, e, 0, _sig(detector="cusum"))
        assert inc.state == IncidentState.OPEN
        inc2 = _step(reg, e, 2_000, _sig(detector="drift"))
        assert inc2.detector == "both"
        assert inc2.state == IncidentState.ESCALATED
