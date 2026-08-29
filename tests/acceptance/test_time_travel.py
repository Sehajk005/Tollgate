"""
Source: Day-5 Plan §7 test 1 -- AC 1 (Impl Plan §1.5). The persisted
`attempt_score.feature_snapshot` corpus must be reproducible: for a sampled
attempt, feeding its run's events with `t_ms <= its ingest_time` through the
SAME `compute_features` implementation on a fresh InMemoryWindowStore must
reproduce the logged 24-vector exactly. This proves `compute_features` is a
pure function of the event prefix and that `eval.corpus.replay_corpus`
recorded it faithfully.
"""

from __future__ import annotations

import random

from eval.corpus import build_runs, load_feature_corpus
from packages.contracts.records import compute_payload_digest
from packages.contracts.wire import ScoreRequest
from packages.features.compute import (
    FEATURE_NAMES,
    FeatureContext,
    classify_ua,
    compute_features,
)
from packages.features.memory_store import InMemoryWindowStore
from packages.storage.db import connect

N_SAMPLED = 200
SEED = 42


def _recompute_vector(run, events_prefix) -> tuple:
    """Feed `events_prefix` (already t_ms-sorted, ending at the target event)
    through compute_features on a fresh store; return the last 24-vector."""
    store = InMemoryWindowStore()
    last = None
    for i, ev in enumerate(events_prefix):
        body = ScoreRequest(**ev.to_score_request())
        ctx = FeatureContext(
            merchant_id=run.merchant_id,
            attempt_uid=f"tt-{run.run_index}-{i}",
            ingest_ms=ev.t_ms,
            payload_digest=compute_payload_digest(body),
            event_id=ev.event_id,
            ip=ev.ip,
            ua_class=classify_ua(""),  # replay driver passes user_agent=""
            card_hash=ev.card_hash,
            bin=ev.bin,
            amount_minor=ev.amount_minor,
            session_id=ev.session_id,
        )
        last = compute_features(store, ctx)
    return tuple(float(last.values[name]) for name in FEATURE_NAMES)


class TestTimeTravel:
    def test_sampled_snapshots_reproduce_exactly(self, day5_corpus):
        runs = {r.run_index: r for r in build_runs(SEED)}
        conn = connect(day5_corpus)
        try:
            corpus = load_feature_corpus(conn)
        finally:
            conn.close()
        assert corpus, "feature corpus is empty"

        rng = random.Random(SEED)
        keys = rng.sample(sorted(corpus.keys()), min(N_SAMPLED, len(corpus)))

        checked = 0
        for run_index, event_id in keys:
            run = runs[run_index]
            row = corpus[(run_index, event_id)]
            prefix = sorted(
                (e for e in run.output.events if e.t_ms <= row.ingest_time),
                key=lambda e: (e.t_ms, e.seq),
            )
            assert prefix and prefix[-1].event_id == event_id, (
                f"event {event_id} not the last in its t_ms<=ingest_time prefix"
            )
            recomputed = _recompute_vector(run, prefix)
            assert recomputed == row.x, (
                f"run {run_index} event {event_id}: recomputed 24-vector != logged feature_snapshot\n"
                f"  recomputed={recomputed}\n  logged    ={row.x}"
            )
            checked += 1
        assert checked >= min(N_SAMPLED, len(corpus)), "sampled fewer attempts than intended"
