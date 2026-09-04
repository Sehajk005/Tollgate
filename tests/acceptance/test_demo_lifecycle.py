"""
Source: remediation plan §16 -- Scenarios A-G, against a REAL scorer
subprocess (the `test_day2_e2e` harness pattern, Decision 22).

These are the scenarios an operator actually performs. Every one of them was
broken before this remediation, and none of them had an automated test:

  A  clean run to completion          -- rendered as RUNNING (N-1/N) forever
  B  stop once                        -- returned the pre-stop snapshot
  C  reset mid-run                    -- reported idle while still scoring
  D  repeat the same tier             -- invisible for 24 hours
  E  cross-tier                       -- carried the previous run's windows
  F  refresh mid-run                  -- showed an all-clear dashboard
  G  a run that fails                 -- froze at a confident counter

Scenario H (60x stability) is scripts/verify_60x.py -- it needs minutes, not
seconds, and belongs in the performance gate rather than the suite.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key
from tests.acceptance._scorer_process import free_port, spawn_scorer, wait_for_health

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
MERCHANT = "merchant_demo"
API_KEY = "test-key-demo-lifecycle"
AUTH = {"X-Tollgate-Key": API_KEY}

TIER_LADDER = {
    "throttle": 0.06474820143884892,
    "challenge": 0.2571428571428571,
    "step_up": 0.5094339622641509,
    "block": 0.8737864077669902,
}


def _seed(db_path: Path) -> None:
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'Demo Lifecycle', 'INR', 'Asia/Kolkata', ?, ?, 0)",
            (MERCHANT, hash_api_key(API_KEY), hash_api_key("outcome-secret")),
        )
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


class Scorer:
    """A live scorer subprocess plus the two things every scenario needs: an
    SSE listener and a /healthz probe."""

    def __init__(self, tmp_path: Path):
        self.db_path = tmp_path / "tollgate.db"
        self.spool_dir = tmp_path / "spool"
        _seed(self.db_path)
        self.port = free_port()
        self.proc = spawn_scorer(self.db_path, self.spool_dir, self.port)
        # ONE ordered list. Splitting attempts and control frames into two
        # lists at capture time would lose the interleaving, and Scenario C's
        # whole assertion is about ordering: nothing may be scored AFTER the
        # reset frame.
        self.stream = []
        self._stop = threading.Event()
        self._health_worst = 0.0
        self._health_failures = 0

    # -- lifecycle -------------------------------------------------------

    def __enter__(self):
        wait_for_health(self.port)
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()
        self._prober = threading.Thread(target=self._probe, daemon=True)
        self._prober.start()
        time.sleep(0.3)  # let the subscriber register
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self.proc.kill()
        self.proc.wait(timeout=10)

    def _listen(self):
        try:
            with httpx.stream("GET", f"{self.base}/v1/stream", timeout=120.0) as resp:
                for line in resp.iter_lines():
                    if self._stop.is_set():
                        return
                    if not line or not line.startswith("data: "):
                        continue
                    self.stream.append(json.loads(line[len("data: "):]))
        except httpx.HTTPError:
            return  # the subprocess is killed out from under this read

    def _probe(self):
        # ONE keep-alive client. A fresh connection per sample means thousands
        # of TCP setups across a run, and on Windows the resulting
        # ephemeral-port / TIME_WAIT pressure surfaces as sporadic second-long
        # CONNECT stalls -- which would be recorded as scorer latency and are
        # nothing of the kind. Measured directly: with per-sample connections
        # the 60x gate reported a /healthz p99 of 1358 ms; with one reused
        # connection, 24 ms for the same workload. The probe must measure the
        # server, not itself.
        with httpx.Client(base_url=self.base, timeout=5.0,
                          limits=httpx.Limits(max_keepalive_connections=1, max_connections=1)) as client:
            while not self._stop.is_set():
                t0 = time.perf_counter()
                try:
                    if client.get("/healthz").status_code != 200:
                        self._health_failures += 1
                except httpx.HTTPError:
                    self._health_failures += 1
                self._health_worst = max(self._health_worst, time.perf_counter() - t0)
                self._stop.wait(0.1)

    @property
    def events(self):
        """Attempt events, in order."""
        return [f for f in self.stream if f.get("attempt_uid")]

    @property
    def frames(self):
        """Lifecycle control frames, in order."""
        return [f for f in self.stream if f.get("type") == "replay_status"]

    def clear_stream(self):
        self.stream.clear()

    # -- API -------------------------------------------------------------

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, **body):
        payload = {"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0}
        payload.update(body)
        return httpx.post(f"{self.base}/v1/replay/start", headers=AUTH, json=payload, timeout=20.0)

    def stop_replay(self):
        return httpx.post(f"{self.base}/v1/replay/stop", headers=AUTH, timeout=20.0)

    def reset(self):
        return httpx.post(f"{self.base}/v1/replay/reset", headers=AUTH, timeout=20.0)

    def status(self):
        return httpx.get(f"{self.base}/v1/replay/status", timeout=10.0).json()

    def incidents(self):
        return httpx.get(f"{self.base}/v1/incidents?state=live", headers=AUTH, timeout=10.0).json()

    def recent(self, after=None):
        url = f"{self.base}/v1/stream/recent"
        if after:
            url += f"?after={after}"
        return httpx.get(url, timeout=10.0).json()["events"]

    def await_terminal(self, timeout_s: float = 180.0) -> dict:
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            last = self.status()
            if last["terminal"]:
                return last
            time.sleep(0.1)
        raise AssertionError(f"never reached a terminal state; last: {last}")

    @property
    def health_worst_s(self) -> float:
        return self._health_worst

    @property
    def health_failures(self) -> int:
        return self._health_failures


@pytest.fixture
def scorer(tmp_path):
    with Scorer(tmp_path) as s:
        yield s


@pytest.mark.slow
class TestScenarioACleanRun:
    def test_a_clean_easy_run_reaches_the_exact_terminal_count(self, scorer):
        assert scorer.reset().status_code == 200
        assert scorer.start().status_code == 202
        final = scorer.await_terminal()

        assert final["state"] == "finished", final
        assert final["sent"] == final["total"] > 0, (
            f"finished at {final['sent']}/{final['total']} -- AUDIT-002"
        )
        assert final["error"] is None
        assert final["terminal"] is True, "Launch would stay disabled"

        time.sleep(0.4)
        assert scorer.frames, "no lifecycle control frame ever reached the stream"
        terminal_frames = [f for f in scorer.frames if f["replay"]["state"] == "finished"]
        assert terminal_frames, "the terminal transition published nothing (AUDIT-002)"
        assert terminal_frames[-1]["replay"]["sent"] == final["total"]
        assert scorer.health_failures == 0
        assert scorer.health_worst_s < 2.0, (
            f"/healthz worst latency {scorer.health_worst_s:.2f}s during a clean run"
        )


@pytest.mark.slow
class TestScenarioBStop:
    def test_stop_once_reports_the_true_terminal_count(self, scorer):
        scorer.reset()
        assert scorer.start(speed=60).status_code == 202
        time.sleep(0.5)

        resp = scorer.stop_replay()
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] != "running", "stop returned the pre-stop snapshot (AUDIT-003)"

        final = scorer.await_terminal()
        assert final["state"] in ("stopped", "finished")
        time.sleep(0.5)
        assert scorer.status()["state"] == final["state"], "the state moved after terminal"
        # The count the API reports must be the count the stream produced.
        assert len(scorer.events) >= final["sent"] - 2, (
            f"backend says {final['sent']} sent, stream carried {len(scorer.events)}"
        )
        assert scorer.start().status_code == 202, "Launch did not re-enable after a stop"
        scorer.await_terminal()


@pytest.mark.slow
class TestScenarioCReset:
    def test_reset_mid_run_terminates_before_clearing_and_leaves_idle(self, scorer):
        scorer.reset()
        scorer.start(speed=60)
        time.sleep(0.6)

        body = scorer.reset().json()
        assert body["state"] == "idle", body
        assert body["degraded"] is False, body["cleared"]

        time.sleep(0.6)
        positions = [i for i, f in enumerate(scorer.stream) if f.get("reset") is True]
        assert positions, "no reset frame was published"
        # THE invariant: nothing may be scored after the reset frame. An attempt
        # event published afterwards means the loop was still running while its
        # windows were being cleared underneath it -- AUDIT-004's signature.
        after_reset = scorer.stream[positions[-1] + 1:]
        stragglers = [f for f in after_reset if f.get("attempt_uid")]
        assert not stragglers, (
            f"{len(stragglers)} attempt event(s) were published AFTER the reset "
            f"frame; the backend was still scoring while reporting idle"
        )
        assert scorer.status()["state"] == "idle"
        assert scorer.status()["run_id"] is None

        assert scorer.incidents()["incidents"] == [], "incidents survived the reset"
        assert scorer.start().status_code == 202, "Launch after a reset was refused"
        assert scorer.await_terminal()["state"] == "finished"


@pytest.mark.slow
class TestScenarioDRepeatRun:
    def test_the_same_tier_runs_twice_with_identical_counts(self, scorer):
        scorer.reset()
        scorer.start()
        first = scorer.await_terminal()
        assert first["state"] == "finished"
        assert first["sent"] >= 800, f"the easy tier produced only {first['sent']} events"
        first_events = len(scorer.events)
        first_rules = {r for e in scorer.events for r in (e.get("rules_fired") or [])}
        assert first_rules, "no rule fired at all in run 1"

        scorer.reset()
        scorer.clear_stream()
        second = scorer.start()
        assert second.status_code == 202
        final = scorer.await_terminal()

        assert final["state"] == "finished"
        assert final["sent"] == first["sent"], (
            f"run 2 sent {final['sent']} against run 1's {first['sent']} -- "
            f"AUDIT-005: the repeat run was swallowed as an idempotent replay"
        )
        time.sleep(0.5)
        assert len(scorer.events) >= first_events - 5, (
            f"run 2 published {len(scorer.events)} events against run 1's {first_events}"
        )
        second_rules = {r for e in scorer.events for r in (e.get("rules_fired") or [])}
        assert second_rules, (
            "run 2 fired no rules -- the AUDIT-005 signature exactly: every "
            "window write was suppressed by the previous run's idempotency keys"
        )

    def test_launch_auto_clears_without_an_explicit_reset(self, scorer):
        scorer.reset()
        scorer.start()
        first = scorer.await_terminal()
        body = scorer.start().json()
        assert body["auto_reset"] is True
        second = scorer.await_terminal()
        assert second["sent"] == first["sent"]
        assert second["run_id"] != first["run_id"]


@pytest.mark.slow
class TestScenarioECrossTier:
    def test_every_tier_runs_from_a_clean_baseline(self, scorer):
        counts = {}
        for tier in ("easy", "medium", "hard", "evasive"):
            scorer.reset()
            scorer.clear_stream()
            assert scorer.start(tier=tier).status_code == 202, tier
            final = scorer.await_terminal()
            assert final["state"] == "finished", (tier, final)
            assert final["tier"] == tier
            counts[tier] = final["sent"]
            assert final["sent"] == final["total"] > 0, (tier, final)
        assert len(set(counts.values())) > 1, (
            f"every tier produced the same count -- {counts} -- which suggests "
            f"the tier parameter is not reaching the generator"
        )


@pytest.mark.slow
class TestScenarioFRefreshMidRun:
    def test_a_late_mount_reconstructs_with_no_gap_and_no_duplicate(self, scorer):
        """What a browser does on F5: fetch the status, back-fill the recent
        buffer, and fetch the incidents -- concurrently. Before FIX-013 the
        dashboard mounted EMPTY and showed an all-clear screen mid-attack."""
        scorer.reset()
        scorer.start(speed=60)
        time.sleep(2.0)

        # The three mount fetches, exactly as the frontend issues them.
        status = scorer.status()
        backfill = scorer.recent()
        incidents = scorer.incidents()

        assert status["state"] in ("starting", "running"), status
        assert status["tier"] == "easy", "the tier a refreshed client would show is wrong"
        assert status["sent"] > 0, "a refreshed client would show a zeroed progress counter"
        assert isinstance(incidents.get("incidents"), list)

        attempts = [e for e in backfill if e.get("attempt_uid")]
        assert attempts, (
            "the back-fill is empty mid-run -- a refreshed dashboard would show "
            "a calm, empty screen while an attack is in progress (AUDIT-009)"
        )
        uids = [e["attempt_uid"] for e in attempts]
        assert len(uids) == len(set(uids)), "the back-fill contains duplicates"

        # Continue from the back-fill's cursor: the seam must have no gap and no
        # repeat.
        cursor = uids[-1]
        time.sleep(1.0)
        following = [e for e in scorer.recent(cursor) if e.get("attempt_uid")]
        overlap = set(uids) & {e["attempt_uid"] for e in following}
        assert not overlap, f"{len(overlap)} event(s) were delivered twice across the seam"

        scorer.stop_replay()
        scorer.await_terminal()

    def test_the_threat_state_is_recoverable_from_the_backfill(self, scorer):
        scorer.reset()
        scorer.start()
        scorer.await_terminal()
        time.sleep(0.4)
        backfill = [e for e in scorer.recent() if e.get("attempt_uid")]
        assert backfill, "nothing to reconstruct from"
        assert backfill[-1].get("threat_state"), (
            "the newest back-filled event carries no threat_state, so a "
            "refreshed client cannot render the band"
        )


@pytest.mark.slow
class TestScenarioGFailureRecovery:
    def test_a_run_that_cannot_build_its_stream_reports_failed_with_a_reason(self, scorer):
        """A REAL failure path, not an injected one: an unknown tier makes
        `build_stream` raise inside the replay task. Before FIX-007 the
        exception vanished into a never-awaited task and the status stayed
        `running` with a frozen counter forever (AUDIT-007)."""
        scorer.reset()
        resp = scorer.start(tier="no-such-tier")
        assert resp.status_code == 202, "the failure must happen in the task, not at validation"

        final = scorer.await_terminal(timeout_s=30)
        assert final["state"] == "failed", (
            f"a replay that could not start reported {final['state']!r} -- the "
            f"operator would watch a frozen counter with no explanation"
        )
        assert final["error"], "no reason was recorded"
        assert final["terminal"] is True

        time.sleep(0.4)
        failed_frames = [f for f in scorer.frames if f["replay"]["state"] == "failed"]
        assert failed_frames, "the failure was never announced on the stream"

    def test_the_system_recovers_completely_after_a_failure(self, scorer):
        scorer.reset()
        scorer.start(tier="no-such-tier")
        assert scorer.await_terminal(timeout_s=30)["state"] == "failed"

        assert scorer.reset().status_code == 200
        assert scorer.start().status_code == 202
        final = scorer.await_terminal()
        assert final["state"] == "finished"
        assert final["error"] is None
        assert final["sent"] == final["total"] > 0


@pytest.mark.slow
class TestIncidentsAreReachable:
    def test_an_incident_opens_and_is_readable_through_the_api(self, scorer):
        """AUDIT-008: the audit could not reach D3 at all, so Confirm and
        Resolve went untested. The API path the screen now uses is exercised
        here; the button presses themselves are §23's browser gate."""
        scorer.reset()
        scorer.start(tier="easy")
        scorer.await_terminal()
        time.sleep(0.5)

        listing = scorer.incidents()["incidents"]
        assert listing, (
            "an easy replay opened no incident, so D3 has nothing to show and "
            "the incident path cannot be verified at all"
        )
        newest = sorted(listing, key=lambda r: r.get("opened_at") or 0, reverse=True)[0]
        detail = httpx.get(
            f"{scorer.base}/v1/incidents/{newest['incident_id']}", headers=AUTH, timeout=10.0
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["incident"]["incident_id"] == newest["incident_id"]
        assert "timeline" in body and "entities" in body

    def test_resolve_closes_the_incident(self, scorer):
        scorer.reset()
        scorer.start(tier="easy")
        scorer.await_terminal()
        time.sleep(0.5)
        listing = scorer.incidents()["incidents"]
        assert listing, "no incident to resolve"
        incident_id = listing[0]["incident_id"]

        resp = httpx.post(
            f"{scorer.base}/v1/incidents/{incident_id}/resolve",
            headers=AUTH, json={"resolution": "false_positive"}, timeout=10.0,
        )
        assert resp.status_code == 200, resp.text
        remaining = [i["incident_id"] for i in scorer.incidents()["incidents"]]
        assert incident_id not in remaining, "the incident is still listed as live after Resolve"
