"""
Source: remediation plan §11.1 (FIX-001) -- the AUDIT-006 reproduction.

AUDIT-006 recorded a scorer that pinned one CPU core, froze the replay counter
and `virtual_time_ms`, and stopped answering `/healthz`, `/v1/score` and
`/v1/replay/status` entirely -- with healthy Redis, an unlocked SQLite and a
flat 9 MB working set. The audit could not determine the cause; the plan's F-A
names it:

    Layer2Engine._commit_through() iterates ONCE PER 10-SECOND BUCKET between
    `pending_bucket` and `target_bucket`, with no bound, synchronously on the
    event-loop thread.

`bucket_index = ingest_ms // 10_000`. A replay launched with `epoch_ms: 0` (what
the dashboard's Launch sends) produces bucket indices 0..1080. A `POST /v1/score`
from the storefront uses `SystemClock`, so it produces bucket index ~1.756e8.
Both feed the SAME `Layer2Engine` for the SAME merchant. One wall-clock attempt
arriving after an epoch-0 replay therefore drives ~175,600,000 iterations of
`baseline_lambda0()` + `PoissonCusum.observe()` -- measured at ~200,000
buckets/s, i.e. ~20 MINUTES of uninterruptible CPU inside one call.

These are the falsifiable reproductions. R1 is the deterministic core; R2/R3 are
the service-level crossings in both orders.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from packages.detect.baseline import StoreBaseline
from packages.detect.cusum import CusumParams
from packages.detect.drift import DriftParams
from packages.detect.layer2 import Layer2Engine
from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key
from tests.acceptance._scorer_process import free_port, spawn_scorer, wait_for_health

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"

MERCHANT = "merchant_demo"
API_KEY = "test-key-time-discontinuity"

# The bucket index a wall-clock `POST /v1/score` lands in. A fixed constant, not
# `time.time()`, so the reproduction is deterministic.
WALL_CLOCK_MS = 1_756_000_000_000
BUCKET_MS = 10_000
WALL_CLOCK_BUCKET = WALL_CLOCK_MS // BUCKET_MS  # 175,600,000

# The whole point: the crossing must resolve in well under a second, not in
# minutes. Generous by ~3 orders of magnitude against the bounded implementation.
CROSSING_BUDGET_S = 1.0

TIER_LADDER = {
    "throttle": 0.06474820143884892,
    "challenge": 0.2571428571428571,
    "step_up": 0.5094339622641509,
    "block": 0.8737864077669902,
}


def build_engine() -> Layer2Engine:
    baseline = StoreBaseline(
        merchant_id=MERCHANT,
        hourly_volume_profile=tuple([60.0] * 24),
        flagged_rate_mean=1.0,
        cards_per_ip_quantiles={
            "5m": [1, 1, 1, 1, 1, 2, 2, 3, 4, 5, 10],
            "30m": [1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 12],
        },
    )
    return Layer2Engine(
        baseline=baseline,
        cusum_params=CusumParams(rho=5.0, h=3.0, bucket_s=10, lambda_min=0.02),
        drift_params=DriftParams(
            exceedance_quantile=0.95, p1=0.5, alpha=0.01, beta=0.05, enabled=True
        ),
        tau_flag=0.06,
    )


def _timed_crossing(engine: Layer2Engine, from_bucket: int, to_bucket: int, budget_s: float):
    """Run one `regime_for` crossing on a daemon thread so an UNBOUNDED loop
    surfaces as a test FAILURE rather than hanging the suite forever.

    Returns (completed, elapsed_s, regime). A pure-Python loop cannot be
    interrupted from outside, so the worker is a daemon: on the unbounded code
    it keeps spinning until the process exits, which is precisely the defect
    being demonstrated. Once bounded it returns in microseconds.
    """
    engine.regime_for(MERCHANT, from_bucket)
    done = threading.Event()
    out = {}

    def work():
        t0 = time.perf_counter()
        out["regime"] = engine.regime_for(MERCHANT, to_bucket)
        out["elapsed"] = time.perf_counter() - t0
        done.set()

    threading.Thread(target=work, daemon=True).start()
    completed = done.wait(budget_s)
    return completed, out.get("elapsed"), out.get("regime")


class TestR1CrossingIsBounded:
    """R1 -- the falsifiable core. Deterministic, no service, no I/O."""

    def test_epoch_zero_to_wall_clock_crossing_completes_promptly(self):
        completed, elapsed, regime = _timed_crossing(
            build_engine(), 0, WALL_CLOCK_BUCKET, CROSSING_BUDGET_S
        )
        assert completed, (
            f"Layer2Engine.regime_for did not return within {CROSSING_BUDGET_S}s while "
            f"crossing {WALL_CLOCK_BUCKET:,} buckets (epoch-0 replay -> wall-clock "
            f"/v1/score). This is AUDIT-006: an unbounded catch-up loop running "
            f"synchronously on the event-loop thread."
        )
        assert elapsed < CROSSING_BUDGET_S
        assert regime is not None and regime[0] in ("alarm", "in_control")

    def test_wall_clock_to_epoch_zero_crossing_completes_promptly(self):
        """The reverse direction. On the unbounded code it returns instantly
        (the loop only runs forward) but leaves `pending_bucket` stranded
        ~1.756e8 buckets in the future, so every subsequent replay bucket is
        silently discarded and Layer 2 is dead for the whole run."""
        completed, elapsed, _ = _timed_crossing(
            build_engine(), WALL_CLOCK_BUCKET, 0, CROSSING_BUDGET_S
        )
        assert completed, "the backward crossing did not return promptly"
        assert elapsed < CROSSING_BUDGET_S

    def test_a_backward_crossing_does_not_strand_the_merchant_in_the_future(self):
        engine = build_engine()
        engine.regime_for(MERCHANT, WALL_CLOCK_BUCKET)
        engine.regime_for(MERCHANT, 0)
        # After crossing back, an epoch-0 replay's gated attempts must actually
        # be counted -- i.e. the pending bucket must track the replay's domain.
        mc = engine._merchants[MERCHANT]
        assert mc.pending_bucket is not None
        assert mc.pending_bucket < WALL_CLOCK_BUCKET // 2, (
            f"pending_bucket is stranded at {mc.pending_bucket:,} after a jump back to "
            f"bucket 0 -- every replay attempt would be discarded and Layer 2 would "
            f"silently never fire for the rest of the run"
        )


# ---------------------------------------------------------------------------
# R2 / R3 -- the same crossing through the real service, in both orders.
# ---------------------------------------------------------------------------


def _seed(db_path: Path) -> None:
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'Time Discontinuity', 'INR', 'Asia/Kolkata', ?, ?, 0)",
            (MERCHANT, hash_api_key(API_KEY), hash_api_key("outcome-secret")),
        )
        # Layer 2 only loads with populated thresholds AND a store_baseline row --
        # without both, this test would exercise the Day-5 path and prove nothing.
        conn.execute(
            """
            INSERT INTO policy_config (
                merchant_id, version, thresholds, hysteresis_gap, cooldown_seconds,
                cusum_rho, cusum_h, cusum_bucket_s, drift_window_s, allow_auto_block,
                auto_ceiling, k_max_entities, control_fraction, rules_config, created_at
            ) VALUES (?, 1, ?, 0.08, 300, 5.0, 3.0, 10, 1800, 0, 'challenge', 10, 0.0, '{}', 0)
            """,
            (MERCHANT, json.dumps(TIER_LADDER)),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO store_baseline (
                merchant_id, hourly_volume_profile, decline_rate_mean, decline_rate_std,
                amount_p05_minor, amount_p50_minor, amount_p95_minor, bin_entropy_mean,
                bin_entropy_std, foreign_bin_share_mean, foreign_bin_share_std,
                cards_per_ip_quantiles, flagged_rate_mean, sample_count, is_stable, updated_at
            ) VALUES (?, ?, 0, 0, 100, 500, 2000, 0, 0, 0, 0, ?, 1.0, 100, 0, 0)
            """,
            (
                MERCHANT,
                json.dumps([60.0] * 24),
                json.dumps({
                    "5m": [1, 1, 1, 1, 1, 2, 2, 3, 4, 5, 10],
                    "30m": [1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 12],
                }),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _wall_clock_score(port: int, n: int = 1) -> None:
    for i in range(n):
        r = httpx.post(
            f"http://127.0.0.1:{port}/v1/score",
            headers={"X-Tollgate-Key": API_KEY},
            json={
                "event_id": f"wallclock-{time.time_ns()}-{i}",
                "card_hash": f"card-wall-{i}",
                "bin": "999001",
                "amount_minor": 120000,
                "currency": "INR",
            },
            timeout=15.0,
        )
        assert r.status_code == 200, f"/v1/score returned {r.status_code}: {r.text[:200]}"


class _HealthProbe:
    """Polls /healthz continuously and records the worst latency seen. This is
    the observable AUDIT-006 signature: a blocked event loop stops answering."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._stop = threading.Event()
        self.max_latency_s = 0.0
        self.failures = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                r = httpx.get(f"http://127.0.0.1:{self._port}/healthz", timeout=5.0)
                if r.status_code != 200:
                    self.failures += 1
            except httpx.HTTPError:
                self.failures += 1
            self.max_latency_s = max(self.max_latency_s, time.perf_counter() - t0)
            self._stop.wait(0.1)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=8)


def _await_terminal(port: int, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = httpx.get(f"http://127.0.0.1:{port}/v1/replay/status", timeout=5.0).json()
        if last.get("state") in ("finished", "stopped", "failed"):
            return last
        time.sleep(0.2)
    raise AssertionError(f"replay never reached a terminal state; last status: {last}")


def _run_crossing(tmp_path: Path, replay_first: bool):
    db_path = tmp_path / "tollgate.db"
    spool_dir = tmp_path / "spool"
    _seed(db_path)
    port = free_port()
    proc = spawn_scorer(db_path, spool_dir, port)
    try:
        wait_for_health(port)
        with _HealthProbe(port) as probe:
            if replay_first:
                start = httpx.post(
                    f"http://127.0.0.1:{port}/v1/replay/start",
                    headers={"X-Tollgate-Key": API_KEY},
                    json={"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0},
                    timeout=15.0,
                )
                assert start.status_code == 202, start.text
                _await_terminal(port)
                _wall_clock_score(port, n=3)
            else:
                _wall_clock_score(port, n=1)
                start = httpx.post(
                    f"http://127.0.0.1:{port}/v1/replay/start",
                    headers={"X-Tollgate-Key": API_KEY},
                    json={"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0},
                    timeout=15.0,
                )
                assert start.status_code == 202, start.text
                _await_terminal(port)
                _wall_clock_score(port, n=1)

            final = httpx.get(f"http://127.0.0.1:{port}/v1/replay/status", timeout=5.0).json()
        return final, probe
    finally:
        proc.kill()
        proc.wait(timeout=10)


@pytest.mark.slow
class TestServiceLevelCrossing:
    def test_r3_replay_at_epoch_zero_then_a_wall_clock_checkout(self, tmp_path):
        """R3 -- the forward crossing, and the one that wedges: the replay
        leaves the merchant CUSUM near bucket 0, then a real checkout drags it
        ~175.6 million buckets forward inside `POST /v1/score`."""
        final, probe = _run_crossing(tmp_path, replay_first=True)
        assert final["state"] == "finished", final
        assert final["sent"] == final["total"] > 0, final
        assert probe.failures == 0, f"{probe.failures} /healthz probes failed during the crossing"
        assert probe.max_latency_s < 2.0, (
            f"/healthz worst latency was {probe.max_latency_s:.1f}s -- the event loop was "
            f"blocked, which is AUDIT-006's observable signature"
        )

    def test_r2_wall_clock_checkout_then_a_replay_at_epoch_zero(self, tmp_path):
        """R2 -- the reverse order. The catch-up loop does not run backwards, so
        this must not wedge; it is the control that proves the bound did not
        merely move the problem."""
        final, probe = _run_crossing(tmp_path, replay_first=False)
        assert final["state"] == "finished", final
        assert final["sent"] == final["total"] > 0, final
        assert probe.failures == 0, f"{probe.failures} /healthz probes failed during the crossing"
        assert probe.max_latency_s < 2.0, (
            f"/healthz worst latency was {probe.max_latency_s:.1f}s"
        )
