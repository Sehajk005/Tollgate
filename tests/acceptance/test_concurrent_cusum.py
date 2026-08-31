"""
Source: Day-7 Plan §4 Step 1, acceptance row 3 (Impl Plan §Day 7). Pins R3:
100 attempts scored concurrently produce the byte-identical per-merchant
Poisson-CUSUM state as the same 100 scored sequentially.

The guarantee rests entirely on `services/scorer/scoring.py::_resolve_layer2`
containing no `await`: under a single-threaded event loop the whole Layer-2
fold for one attempt runs to completion before another coroutine's fold
starts (the only await in `score_attempt` is the terminal
`event_bus.publish`). This test is the executable half of that invariant; the
docstring note in `packages/detect/episode.py` / the comment in
`_resolve_layer2` is the other half. If this fails, an `await` has leaked into
the Layer-2 block -- stop and remove it, do not weaken this test.
"""

from __future__ import annotations

import asyncio
import random

from packages.clock.clock import VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from services.scorer.scoring import score_attempt
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-cusum-cc"
BUCKET_S = 10
# One fixed ingest time: bucket_index = INGEST_MS // (BUCKET_S * 1000). Every
# attempt lands in this one bucket, so the CUSUM fold is order-independent by
# construction and the test isolates the concurrency question, not bucket
# accounting.
INGEST_MS = 3_600_000
N = 100


def _fresh_state(tmp_path, suffix: str):
    db = make_db(tmp_path / suffix)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=50.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    return build_state(db, tmp_path / suffix / "sp", MERCHANT)


def _body(i: int) -> ScoreRequest:
    return ScoreRequest(
        event_id=f"e-{i:05d}", card_hash=f"c-{i:05d}", bin="999123",
        amount_minor=1999, currency="INR", session_id="s-1",
    )


def _cusum_state(state) -> tuple:
    mc = state.layer2._merchant(MERCHANT)
    return (mc.pending_n, mc.pending_bucket, mc.committed_bucket, round(mc.cusum.s, 12))


def _run_sequential(state) -> None:
    clock = VirtualClock(epoch_ms=0)
    clock.set_ms(INGEST_MS)
    ulid = UlidGenerator(clock=clock, rng=random.Random("cc-seq"))

    async def _go():
        for i in range(N):
            await score_attempt(
                state, merchant_id=MERCHANT, ip="198.51.100.5",
                body=_body(i), clock=clock, ulid=ulid,
            )

    asyncio.run(_go())


def _run_concurrent(state) -> None:
    clock = VirtualClock(epoch_ms=0)
    clock.set_ms(INGEST_MS)
    ulid = UlidGenerator(clock=clock, rng=random.Random("cc-conc"))

    async def _go():
        await asyncio.gather(*[
            score_attempt(
                state, merchant_id=MERCHANT, ip="198.51.100.5",
                body=_body(i), clock=clock, ulid=ulid,
            )
            for i in range(N)
        ])

    asyncio.run(_go())


class TestConcurrentCusumEqualsSequential:
    def test_100_concurrent_scores_produce_the_same_cusum_as_sequential(self, tmp_path):
        seq_state = _fresh_state(tmp_path, "seq")
        _run_sequential(seq_state)
        seq_before = _cusum_state(seq_state)
        seq_state.layer2.flush(MERCHANT, INGEST_MS // (BUCKET_S * 1000))
        seq_after_s = round(seq_state.layer2._merchant(MERCHANT).cusum.s, 12)
        seq_state.spool.close()

        conc_state = _fresh_state(tmp_path, "conc")
        _run_concurrent(conc_state)
        conc_before = _cusum_state(conc_state)
        conc_state.layer2.flush(MERCHANT, INGEST_MS // (BUCKET_S * 1000))
        conc_after_s = round(conc_state.layer2._merchant(MERCHANT).cusum.s, 12)
        conc_state.spool.close()

        assert seq_before[0] == N, f"sequential run did not gate all {N} attempts: {seq_before}"
        assert conc_before == seq_before, (
            f"concurrent CUSUM state {conc_before} != sequential {seq_before} -- "
            "an await has leaked into the Layer-2 block"
        )
        assert conc_after_s == seq_after_s, (
            f"committed CUSUM statistic diverged: concurrent {conc_after_s} != sequential {seq_after_s}"
        )
        assert seq_after_s > 0.0, "the committed bucket should have moved the statistic off zero"
