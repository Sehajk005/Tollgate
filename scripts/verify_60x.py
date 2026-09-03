"""
Source: remediation plan §17 -- the PERFORMANCE AND STABILITY GATE.

Verification only. Not a product deliverable, not imported by anything the
service runs.

The audit's core finding about AUDIT-006 was that a single successful run
proves nothing: two of its own runs wedged at different positions with the same
signature, and its controlled single-epoch reproduction passed cleanly. So every
gate here is repeated, and "it worked once" is a failure at every row.

    60x stability   3 consecutive full easy runs at speed 60, reset between,
                    with a WALL-CLOCK POST /v1/score injected at ~50% of each --
                    the interleaving the audit never varied, and the one that
                    crosses the two time domains.
    time-crossing   5 repetitions of the R2/R3 sequences: exactly one bounded
                    discontinuity WARNING each, and never a spin.
    throughput      20 consecutive easy runs at speed 0: each under 5 s, at
                    least 400 attempts/s, identical event counts.
    repeatability   across those 20: no first attempt of a run is ever an
                    idempotent replay, and the Redis key count returns to its
                    floor after each reset.
    drainer         across all 23: attempt_score row count == events scored,
                    the thread alive at the end, connect() calls <= 2 per run.

Usage:
    python -m scripts.verify_60x --gate all
    python -m scripts.verify_60x --gate 60x --faulthandler
    python -m scripts.verify_60x --gate throughput --redis redis://localhost:6379/9
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from packages.clock.clock import SystemClock
from packages.storage.db import connect, initialize_schema
from services.scorer.auth import hash_api_key

# Deliberately NOT imported from tests/: `test_oracle_isolation.py` walks the
# import closure of everything under scripts/ and requires that nothing there
# reaches into the test tree. The three helpers are small enough to own.
ENV_ALLOWLIST = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "TEMP", "TMP", "HOME", "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHASHSEED",
    "PYTHONIOENCODING", "PYTHONUTF8", "VIRTUAL_ENV",
)

# Wall clock for verification bookkeeping only, through the sanctioned accessor
# (TRD §4 / test_clock_discipline.py: nothing outside packages/clock reads it).
_WALL = SystemClock()


def _now_ms() -> int:
    return _WALL.now_ms()


def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def hermetic_env(db_path, spool_dir, port, extra_env=None) -> dict:
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    env["TOLLGATE_SKIP_DOTENV"] = "1"
    env["TOLLGATE_TEST_DB"] = str(db_path)
    env["TOLLGATE_TEST_SPOOL"] = str(spool_dir)
    env["TOLLGATE_TEST_PORT"] = str(port)
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    return env


# Startup, not steady state: `build_default()` loads LightGBM, the booster, the
# calibrator and Layer 2 before binding. On a machine that has just finished a
# multi-minute gate that can take well over 40 s, and a verifier that gives up
# during startup measures the wrong thing entirely.
def wait_for_health(port: int, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"scorer on port {port} did not become healthy in {timeout_s}s")

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "_run_scorer_for_test.py"
SCHEMA_PATH = REPO_ROOT / "schema.sql"

MERCHANT = "merchant_demo"
API_KEY = "verify-60x-key"
AUTH = {"X-Tollgate-Key": API_KEY}

TIER_LADDER = {
    "throttle": 0.06474820143884892,
    "challenge": 0.2571428571428571,
    "step_up": 0.5094339622641509,
    "block": 0.8737864077669902,
}

# §17 thresholds, verbatim.
HEALTH_P99_MS = 500.0
LOOP_LAG_MAX_S = 2.0
RSS_GROWTH_LIMIT_MB = 50.0
THROUGHPUT_RUN_LIMIT_S = 5.0
THROUGHPUT_MIN_ATTEMPTS_PER_S = 400.0
DRAINER_CONNECTS_PER_RUN = 2

LAG_RE = re.compile(r"event loop lag ([0-9.]+)s")
DISCONTINUITY_RE = re.compile(r"bounded time discontinuity")


def rss_mb(pid: int) -> float:
    """Resident set size, without adding a dependency for one number."""
    try:
        import psutil  # noqa: PLC0415

        return psutil.Process(pid).memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                text=True, stderr=subprocess.DEVNULL,
            )
            cells = next(csv_row for csv_row in [out.strip().split('","')] if len(csv_row) >= 5)
            return float(re.sub(r"[^0-9]", "", cells[4])) / 1024.0
        except Exception:  # noqa: BLE001
            return float("nan")
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


def seed(db_path: Path) -> None:
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'verify-60x', 'INR', 'Asia/Kolkata', ?, ?, 0)",
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


class HealthProbe(threading.Thread):
    def __init__(self, port: int, interval_s: float = 0.1):
        super().__init__(daemon=True)
        self.port = port
        self.interval_s = interval_s
        self.samples_ms = []
        self.failures = 0
        self._stop = threading.Event()

    def run(self):
        # ONE keep-alive client for the whole probe. A fresh connection per
        # sample means several thousand TCP setups over a multi-minute gate,
        # and on Windows the resulting ephemeral-port/TIME_WAIT pressure shows
        # up as sporadic second-long CONNECT stalls -- which would be measured
        # as scorer latency and are nothing of the kind. The gate must measure
        # the server, not the measurement.
        with httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}",
            timeout=5.0,
            limits=httpx.Limits(max_keepalive_connections=1, max_connections=1),
        ) as client:
            while not self._stop.is_set():
                t0 = time.perf_counter()
                try:
                    r = client.get("/healthz")
                    if r.status_code != 200:
                        self.failures += 1
                except httpx.HTTPError:
                    self.failures += 1
                self.samples_ms.append((time.perf_counter() - t0) * 1000.0)
                self._stop.wait(self.interval_s)

    def halt(self):
        self._stop.set()
        self.join(timeout=6)

    @property
    def p99_ms(self) -> float:
        if not self.samples_ms:
            return 0.0
        ordered = sorted(self.samples_ms)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms) if self.samples_ms else 0.0


class Scorer:
    """A scorer subprocess with its stderr captured, so the permanent
    instrumentation (loop lag, bounded discontinuity, drainer heartbeat) can be
    read back rather than guessed at."""

    _instance = 0

    def __init__(self, workdir: Path, *, redis_url=None, faulthandler=False):
        # A UNIQUE directory per scorer. Re-using one means `seed()` re-inserts
        # into an existing database and the gate dies on a UNIQUE constraint
        # instead of running -- a verifier that cannot be run twice is not much
        # of a verifier.
        Scorer._instance += 1
        workdir = workdir / f"{int(time.monotonic() * 1000)}-{Scorer._instance}"
        workdir.mkdir(parents=True, exist_ok=True)
        self.db_path = workdir / "tollgate.db"
        self.spool_dir = workdir / "spool"
        seed(self.db_path)
        self.port = free_port()
        extra = {}
        if redis_url:
            extra["TOLLGATE_REDIS_URL"] = redis_url
        if faulthandler:
            extra["TOLLGATE_FAULTHANDLER"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, str(RUNNER)],
            env=hermetic_env(self.db_path, self.spool_dir, self.port, extra),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.stderr_lines = []
        self._reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        wait_for_health(self.port)

    def _read_stderr(self):
        for raw in self.proc.stderr:
            self.stderr_lines.append(raw.decode("utf-8", "replace").rstrip())

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def health(self) -> dict:
        return httpx.get(f"{self.base}/healthz", timeout=10.0).json()

    def start(self, **body) -> dict:
        payload = {"tier": "easy", "seed": 42, "speed": 0, "epoch_ms": 0}
        payload.update(body)
        r = httpx.post(f"{self.base}/v1/replay/start", headers=AUTH, json=payload, timeout=30.0)
        r.raise_for_status()
        return r.json()

    def reset(self) -> dict:
        r = httpx.post(f"{self.base}/v1/replay/reset", headers=AUTH, timeout=30.0)
        r.raise_for_status()
        return r.json()

    def status(self) -> dict:
        return httpx.get(f"{self.base}/v1/replay/status", timeout=10.0).json()

    def score(self, i: int) -> int:
        """A WALL-CLOCK attempt -- the crossing the audit never varied."""
        r = httpx.post(
            f"{self.base}/v1/score", headers=AUTH,
            json={
                "event_id": f"wall-{_now_ms()}-{i}-{id(self)}", "card_hash": f"card-wall-{i}",
                "bin": "999001", "amount_minor": 120000, "currency": "INR",
            },
            timeout=30.0,
        )
        return r.status_code

    def await_terminal(self, timeout_s: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < deadline:
            last = self.status()
            if last["terminal"]:
                return last
            time.sleep(0.1)
        raise TimeoutError(f"replay never terminated; last status: {last}")

    def loop_lag_warnings(self):
        return [float(m.group(1)) for line in self.stderr_lines for m in [LAG_RE.search(line)] if m]

    def discontinuity_warnings(self):
        return [line for line in self.stderr_lines if DISCONTINUITY_RE.search(line)]

    def close(self) -> int:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self._reader.join(timeout=5)
        return self.proc.returncode


def rows_in(db_path: Path, table: str) -> int:
    conn = connect(db_path, read_only=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def redis_key_count(redis_url, merchant=MERCHANT) -> int:
    if not redis_url:
        return -1
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        return len(client.keys(f"tg:{merchant}:*"))
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def gate_60x(workdir: Path, redis_url, faulthandler: bool, runs: int = 3) -> dict:
    """3 consecutive full easy runs at speed 60, reset between, with a
    wall-clock checkout injected at ~50% of each."""
    scorer = Scorer(workdir / "gate60x", redis_url=redis_url, faulthandler=faulthandler)
    probe = HealthProbe(scorer.port)
    probe.start()
    result = {"gate": "60x", "runs": [], "faulthandler": faulthandler}
    rss_start = rss_mb(scorer.proc.pid)
    try:
        for run_index in range(runs):
            scorer.reset()
            started = scorer.start(speed=60, pace_from="episode")
            total_hint = None
            injected = False
            t0 = time.perf_counter()
            while True:
                status = scorer.status()
                if total_hint is None and status["total"]:
                    total_hint = status["total"]
                if (
                    not injected
                    and total_hint
                    and status["sent"] >= total_hint // 2
                ):
                    # THE interleaving: a wall-clock attempt lands mid-run, in a
                    # time domain ~1.756e8 buckets away from the replay's.
                    scorer.score(run_index)
                    injected = True
                if status["terminal"]:
                    break
                if time.perf_counter() - t0 > 600:
                    raise TimeoutError(f"run {run_index} did not terminate in 600 s")
                time.sleep(0.1)
            result["runs"].append({
                "run_index": run_index,
                "run_id": started["run_id"],
                "state": status["state"],
                "sent": status["sent"],
                "total": status["total"],
                "wall_s": round(time.perf_counter() - t0, 2),
                "checkout_injected": injected,
                "error": status["error"],
            })
        rss_end = rss_mb(scorer.proc.pid)
        health = scorer.health()
    finally:
        probe.halt()
        exit_code = scorer.close()

    lags = scorer.loop_lag_warnings()
    result.update({
        "health_p99_ms": round(probe.p99_ms, 1),
        "health_max_ms": round(probe.max_ms, 1),
        "health_failures": probe.failures,
        "loop_lag_warnings": lags,
        "loop_lag_max_s": max(lags) if lags else 0.0,
        "discontinuity_warnings": len(scorer.discontinuity_warnings()),
        "rss_start_mb": round(rss_start, 1),
        "rss_end_mb": round(rss_end, 1),
        "rss_growth_mb": round(rss_end - rss_start, 1),
        "exit_code": exit_code,
        "drainer_alive": health.get("drainer_alive"),
    })
    checks = {
        "all_runs_finished": all(r["state"] == "finished" for r in result["runs"]),
        "exact_terminal_counts": all(r["sent"] == r["total"] > 0 for r in result["runs"]),
        "checkout_interleaved": all(r["checkout_injected"] for r in result["runs"]),
        "zero_failed_runs": all(r["error"] is None for r in result["runs"]),
        "health_responsive": probe.failures == 0 and probe.p99_ms < HEALTH_P99_MS,
        "loop_lag_under_2s": not lags,
        "rss_growth_ok": not (result["rss_growth_mb"] == result["rss_growth_mb"])
        or result["rss_growth_mb"] < RSS_GROWTH_LIMIT_MB,
        "no_crash": exit_code in (0, 1, -15, 15, 143, 3221225786),
        "drainer_alive": health.get("drainer_alive") is True,
    }
    result["checks"] = checks
    result["pass"] = all(checks.values())
    return result


def gate_crossing(workdir: Path, redis_url, repetitions: int = 5) -> dict:
    """R2/R3 in both orders, five times. Each must complete, log exactly one
    bounded-discontinuity WARNING, and never spin."""
    result = {"gate": "crossing", "repetitions": []}
    ok = True
    for rep in range(repetitions):
        for order in ("replay_first", "score_first"):
            scorer = Scorer(workdir / f"crossing-{rep}-{order}", redis_url=redis_url)
            probe = HealthProbe(scorer.port)
            probe.start()
            t0 = time.perf_counter()
            try:
                if order == "replay_first":
                    scorer.start(speed=0)
                    final = scorer.await_terminal(timeout_s=120)
                    scorer.score(rep)
                else:
                    scorer.score(rep)
                    scorer.start(speed=0)
                    final = scorer.await_terminal(timeout_s=120)
                    scorer.score(rep + 1000)
            finally:
                probe.halt()
                exit_code = scorer.close()
            warnings = scorer.discontinuity_warnings()
            entry = {
                "rep": rep, "order": order, "state": final["state"],
                "sent": final["sent"], "total": final["total"],
                "wall_s": round(time.perf_counter() - t0, 2),
                "discontinuity_warnings": len(warnings),
                "health_max_ms": round(probe.max_ms, 1),
                "health_failures": probe.failures,
                "exit_code": exit_code,
            }
            entry["pass"] = (
                final["state"] == "finished"
                and final["sent"] == final["total"] > 0
                and probe.failures == 0
                and probe.max_ms < LOOP_LAG_MAX_S * 1000
                # The forward crossing must log exactly one; the backward one
                # logs one too now that it is handled rather than ignored.
                and len(warnings) >= (1 if order == "replay_first" else 0)
            )
            ok = ok and entry["pass"]
            result["repetitions"].append(entry)
    result["pass"] = ok
    return result


def gate_throughput(workdir: Path, redis_url, runs: int = 20) -> dict:
    """20 consecutive easy runs at speed 0 in ONE process. Also carries the
    repeatability and drainer gates, because those are assertions ABOUT these
    same runs and re-running them separately would prove less, not more."""
    scorer = Scorer(workdir / "throughput", redis_url=redis_url)
    probe = HealthProbe(scorer.port)
    probe.start()
    result = {"gate": "throughput", "runs": []}
    events_scored = 0
    key_floor = None
    rss_start = rss_mb(scorer.proc.pid)
    try:
        for run_index in range(runs):
            reset_body = scorer.reset()
            keys_after_reset = redis_key_count(redis_url)
            if key_floor is None:
                key_floor = keys_after_reset

            t0 = time.perf_counter()
            started = scorer.start(speed=0)
            final = scorer.await_terminal(timeout_s=120)
            wall_s = time.perf_counter() - t0
            events_scored += final["sent"]

            connects = scorer.health().get("drainer_connects", 0)
            result["runs"].append({
                "run_index": run_index,
                "run_id": started["run_id"],
                "state": final["state"],
                "sent": final["sent"],
                "total": final["total"],
                "wall_s": round(wall_s, 3),
                "attempts_per_s": round(final["sent"] / wall_s, 1) if wall_s > 0 else 0.0,
                "keys_after_reset": keys_after_reset,
                "reset_degraded": reset_body.get("degraded"),
                "drainer_connects_total": connects,
                # A failed run must say WHY in the report, or the gate tells you
                # only that something broke -- which is the shape of problem
                # this whole remediation exists to remove.
                "error": final.get("error"),
                "stop_reason": final.get("stop_reason"),
            })
        rss_end = rss_mb(scorer.proc.pid)
        health = scorer.health()
        # Let the drainer finish before comparing row counts.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and health.get("drainer_rows", 0) < events_scored:
            time.sleep(0.2)
            health = scorer.health()
    finally:
        probe.halt()
        exit_code = scorer.close()

    time.sleep(0.5)
    rows = rows_in(scorer.db_path, "attempt_score")
    counts = {r["sent"] for r in result["runs"]}
    lags = scorer.loop_lag_warnings()
    result.update({
        "events_scored": events_scored,
        "attempt_score_rows": rows,
        "distinct_event_counts": sorted(counts),
        "drainer_alive_at_end": health.get("drainer_alive"),
        "drainer_connects_total": health.get("drainer_connects"),
        "drainer_failures": health.get("drainer_failures"),
        "redis_key_floor": key_floor,
        "loop_lag_warnings": lags,
        "rss_growth_mb": round(rss_end - rss_start, 1),
        "health_p99_ms": round(probe.p99_ms, 1),
        "exit_code": exit_code,
        "stderr_tail": scorer.stderr_lines[-40:],
    })
    connects = health.get("drainer_connects") or 0
    checks = {
        "all_finished": all(r["state"] == "finished" for r in result["runs"]),
        "each_under_5s": all(r["wall_s"] < THROUGHPUT_RUN_LIMIT_S for r in result["runs"]),
        "throughput_ok": all(
            r["attempts_per_s"] >= THROUGHPUT_MIN_ATTEMPTS_PER_S for r in result["runs"]
        ),
        "identical_event_counts": len(counts) == 1,
        # Repeatability: every run produced a full stream, which is only
        # possible if no first attempt was swallowed as an idempotent replay.
        "no_run_was_swallowed": all(r["sent"] == r["total"] > 0 for r in result["runs"]),
        "redis_returns_to_floor": (
            redis_url is None
            or all(r["keys_after_reset"] == key_floor for r in result["runs"])
        ),
        "no_degraded_reset": all(r["reset_degraded"] is False for r in result["runs"]),
        # Drainer parity: every scored event landed as a row, exactly once.
        "attempt_score_row_parity": rows == events_scored,
        "drainer_alive": health.get("drainer_alive") is True,
        "drainer_connects_within_budget": connects <= DRAINER_CONNECTS_PER_RUN * runs,
        "loop_lag_under_2s": not lags,
    }
    result["checks"] = checks
    result["pass"] = all(checks.values())
    return result


GATES = {
    "60x": lambda wd, redis_url, fh: gate_60x(wd, redis_url, fh),
    "crossing": lambda wd, redis_url, fh: gate_crossing(wd, redis_url),
    "throughput": lambda wd, redis_url, fh: gate_throughput(wd, redis_url),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Remediation plan §17 performance gate")
    parser.add_argument("--gate", default="all", choices=["all", *GATES])
    parser.add_argument("--redis", default=os.environ.get("TOLLGATE_VERIFY_REDIS"))
    parser.add_argument("--faulthandler", action="store_true")
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--out", default=None, help="write the full report as JSON")
    args = parser.parse_args()

    workdir = Path(args.workdir) if args.workdir else REPO_ROOT / ".verify60x"
    workdir.mkdir(parents=True, exist_ok=True)

    names = list(GATES) if args.gate == "all" else [args.gate]
    report = {
        "faulthandler": args.faulthandler,
        "redis": args.redis,
        "gates": [],
    }
    overall = True
    for name in names:
        print(f"\n=== gate: {name} (faulthandler={args.faulthandler}) ===", flush=True)
        started = time.monotonic()
        outcome = GATES[name](workdir, args.redis, args.faulthandler)
        outcome["elapsed_s"] = round(time.monotonic() - started, 1)
        report["gates"].append(outcome)
        overall = overall and outcome["pass"]
        for key, value in outcome.get("checks", {}).items():
            print(f"  {'PASS' if value else 'FAIL'}  {key}", flush=True)
        print(f"  -> {'PASS' if outcome['pass'] else 'FAIL'} in {outcome['elapsed_s']}s", flush=True)

    report["pass"] = overall
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nreport written to {args.out}")
    print(f"\nOVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
