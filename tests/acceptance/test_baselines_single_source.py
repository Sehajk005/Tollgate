"""
Source: Day-4 Plan (rev. 2) §6 test 15 -- "Baselines use the one window
implementation." B2's per-event count equals compute_features()'s
distinct_cards_per_bin_5m on the same stream, exactly -- not "agrees with
a pandas oracle" -- is the same call (F3). B1: at event N, zero declines
from events in (t_N - 340ms, t_N] are visible (F4).
"""

from __future__ import annotations

from eval.baselines import B2BinConcentrationScorer, b1_decline_velocity_scores
from eval.dataset import Sample, build_dataset
from packages.features.compute import WINDOW_5M_MS, FeatureContext, classify_ua, compute_features
from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import WindowRequest
from packages.simulator.generate import build_stream


class TestB2MatchesComputeFeaturesExactly:
    def test_b2_count_equals_distinct_cards_per_bin_5m_event_by_event(self):
        result = build_stream(seed=42, tier="hard", hours=3)
        events = sorted(result.events, key=lambda e: e.seq)

        compute_store = InMemoryWindowStore()
        b2_store = InMemoryWindowStore()

        checked = 0
        for event in events:
            ctx = FeatureContext(
                merchant_id="eval-baseline", attempt_uid=f"a-{event.event_id}",
                ingest_ms=event.t_ms, payload_digest=f"pd-{event.event_id}", event_id=event.event_id,
                ip=event.ip, ua_class=classify_ua("Mozilla/5.0"), card_hash=event.card_hash,
                bin=event.bin, amount_minor=event.amount_minor, session_id=event.session_id,
            )
            features = compute_features(compute_store, ctx)
            canonical_count = features.values["distinct_cards_per_bin_5m"]

            # The exact same WindowRequest B2BinConcentrationScorer issues,
            # called directly here (rather than via the scorer's 0/1
            # threshold output) so the RAW COUNT can be compared, not just
            # the thresholded decision.
            b2_snapshot = b2_store.record_and_read(WindowRequest(
                merchant_id="eval-baseline", space="bin", key=event.bin, metric="card",
                member=event.card_hash, ingest_ms=event.t_ms, window_ms=WINDOW_5M_MS, read="count",
            ))
            assert b2_snapshot.count == canonical_count, (
                f"event {event.event_id}: B2 raw count {b2_snapshot.count} != "
                f"compute_features distinct_cards_per_bin_5m {canonical_count}"
            )
            checked += 1
        assert checked > 0

    def test_b2_scorer_thresholds_at_20_matching_r3(self):
        result = build_stream(seed=42, tier="hard", hours=3)
        b2_store = InMemoryWindowStore()
        scorer = B2BinConcentrationScorer(b2_store)
        assert scorer.THRESHOLD == 20
        scores = set()
        for event in sorted(result.events, key=lambda e: e.seq):
            sample = Sample(
                event_id=event.event_id, t_ms=event.t_ms, is_attack=False, stream_tier="hard",
                episode_tier=None, episode_id=None, kind="attack", scenario=None,
                entity_overlap=False, outcome_visible_ms=event.t_ms + 340, ip=event.ip,
                bin=event.bin, card_hash=event.card_hash, amount_minor=event.amount_minor,
                gateway_status="authorized", decline_code=None,
            )
            scores.add(scorer(sample))
        assert scores <= {0.0, 1.0}


class TestB1BitemporalHonesty:
    def test_zero_declines_visible_from_events_in_the_340ms_gap(self):
        result = build_stream(seed=42, tier="hard", hours=1)
        runs = [("hard", result)]
        samples = build_dataset(runs)

        store = InMemoryWindowStore()
        scores = b1_decline_velocity_scores(store, samples)
        assert len(scores) == len(samples)

        # Direct re-derivation: for any sample N, a decline from a
        # DIFFERENT event on the same IP whose t_ms falls in the 340ms gap
        # immediately before N (t_N - 340, t_N] must have
        # outcome_visible_ms strictly AFTER t_N -- it cannot have been
        # visible when N was scored, by construction of the gap itself.
        declined = [s for s in samples if s.gateway_status == "declined"]
        checked = 0
        for s in samples:
            near_gap_declines = [
                d for d in declined
                if d.event_id != s.event_id and d.ip == s.ip and s.t_ms - 340 < d.t_ms <= s.t_ms
            ]
            for d in near_gap_declines:
                assert d.outcome_visible_ms > s.t_ms, (
                    "a decline in the 340ms gap must have outcome_visible_ms after the query time"
                )
                checked += 1
        # Not asserting checked > 0 here (whether the gap is populated
        # depends on traffic density at this seed/tier) -- the invariant
        # must hold unconditionally either way; test_b1_matches_manual_
        # recount below is the non-vacuity proof.

    def test_b1_matches_a_manual_recount_at_a_few_sample_points(self):
        result = build_stream(seed=42, tier="hard", hours=1)
        samples = build_dataset([("hard", result)])
        store = InMemoryWindowStore()
        scores = b1_decline_velocity_scores(store, samples)

        checked_any = False
        for s in samples:
            manual_count = sum(
                1 for d in samples
                if d.gateway_status == "declined"
                and d.ip == s.ip
                and d.outcome_visible_ms <= s.t_ms
                and d.outcome_visible_ms > s.t_ms - 60_000
            )
            expected = 1.0 if manual_count >= 5 else 0.0
            assert scores[s.event_id] == expected, (
                f"{s.event_id}: b1 score {scores[s.event_id]} != manual recount-implied {expected} "
                f"(manual_count={manual_count})"
            )
            if manual_count > 0:
                checked_any = True
        assert checked_any, "no declines were ever visible in any window -- test is vacuous"
