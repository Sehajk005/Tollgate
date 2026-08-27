"""
Source: Day-4 Plan (rev. 2) Step 6 -- B1 (naive decline-velocity) and B2
(BIN-concentration). Neither contains bespoke windowing code (F3): both
drive the production `WindowStore.record_and_read(WindowRequest)` over the
stream, the same implementation the online path uses.

Standing caveats the report must carry: B1 requires completed outcomes the
live pre-auth path never has at decision time; B2 shares R3's statistic
(compute.py:203), so B0 (rules) already contains it -- B2's contribution
is not independent of B0's.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from eval.dataset import Sample
from packages.features.compute import WINDOW_5M_MS, WINDOW_60S_MS
from packages.features.memory_store import InMemoryWindowStore
from packages.features.store import WindowRequest, WindowStore

MERCHANT_ID = "eval-baseline"


class B2BinConcentrationScorer:
    """
    B2 -- BIN-concentration. `WindowRequest(space="bin", key=sample.bin,
    metric="card", member=sample.card_hash, window_ms=WINDOW_5M_MS,
    read="count")`, threshold >= 20. Byte-for-byte the same request
    `compute_features()` issues at compute.py:203 (window #6,
    distinct_cards_per_bin_5m) -- so it can be asserted equal to that
    canonical feature, not merely "agreeing" with it (test 15).
    """

    THRESHOLD = 20

    def __init__(self, store: WindowStore):
        self._store = store

    def __call__(self, sample: Sample) -> float:
        snapshot = self._store.record_and_read(WindowRequest(
            merchant_id=MERCHANT_ID, space="bin", key=sample.bin, metric="card",
            member=sample.card_hash, ingest_ms=sample.t_ms, window_ms=WINDOW_5M_MS, read="count",
        ))
        return 1.0 if snapshot.count >= self.THRESHOLD else 0.0


B1_THRESHOLD = 5
B1_WINDOW_MS = WINDOW_60S_MS


def b1_decline_velocity_scores(
    store: WindowStore, samples: Sequence[Sample],
    *, threshold: int = B1_THRESHOLD, window_ms: int = B1_WINDOW_MS,
) -> Dict[str, float]:
    """
    B1 -- naive decline-velocity, bitemporally honest (F4). Processes
    `samples` as a single merged chronological timeline of two event
    kinds: a "score" at t_ms, and (for declined samples only) an "insert"
    at outcome_visible_ms = t_ms + 340ms -- strictly after the sample's own
    scoring point. At an exact tie between a score and an insert, the score
    is processed FIRST (a decline that "just landed" is not yet visible),
    so at event N, zero declines from events in (t_N - window_ms, t_N] can
    ever be counted from an outcome that had not yet landed.

    The window is read via a per-IP constant probe member (never a
    per-event unique key) so repeated reads for the same IP only ever
    update ONE phantom entry rather than accumulating garbage; the +1 it
    contributes is a known, constant offset, subtracted out below.
    """
    events = []
    for s in samples:
        events.append((s.t_ms, 0, "score", s))
        if s.gateway_status == "declined":
            events.append((s.outcome_visible_ms, 1, "insert", s))
    events.sort(key=lambda e: (e[0], e[1]))

    scores: Dict[str, float] = {}
    for _t, _tie, kind, sample in events:
        if kind == "insert":
            store.record_and_read(WindowRequest(
                merchant_id=MERCHANT_ID, space="ip", key=sample.ip, metric="decline",
                member=sample.event_id, ingest_ms=sample.outcome_visible_ms, window_ms=window_ms,
            ))
        else:
            probe_member = f"__b1_probe__:{sample.ip}"
            snapshot = store.record_and_read(WindowRequest(
                merchant_id=MERCHANT_ID, space="ip", key=sample.ip, metric="decline",
                member=probe_member, ingest_ms=sample.t_ms, window_ms=window_ms,
            ))
            real_count = max(0, snapshot.count - 1)
            scores[sample.event_id] = 1.0 if real_count >= threshold else 0.0
    return scores


def b1_decline_velocity(
    samples: Sequence[Sample], *, threshold: int = B1_THRESHOLD, window_ms: int = B1_WINDOW_MS,
) -> List[float]:
    """Convenience wrapper: fresh store, scores returned in `samples`' own input order."""
    store = InMemoryWindowStore()
    scores_by_event_id = b1_decline_velocity_scores(store, samples, threshold=threshold, window_ms=window_ms)
    return [scores_by_event_id[s.event_id] for s in samples]
