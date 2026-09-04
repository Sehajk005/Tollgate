"""
Source: remediation plan FIX-010 / §12 (AUDIT-012, plan F-F).

The audit recorded two hard crashes (SIGSEGV) in the drainer thread. The
contributing design: `_run` polled at 50 ms and `drain_once` opened a BRAND NEW
SQLite connection and re-issued `PRAGMA journal_mode = WAL` on it -- 20
connections and 20 journal-mode switches per second, forever, whether or not
there was anything to drain.

And F-F: `_run` had no `try/except` at all, so one `sqlite3.OperationalError`
ended persistence silently for the life of the process. Same shape of silent
failure as AUDIT-007, in a different thread.

HONEST LIMIT, restated: no unit test can prove the absence of a SIGSEGV. What
is proved here is that the pathological call pattern is gone and that the thread
survives a failure. The crash gate itself is statistical -- scripts/verify_60x.py,
run both with and without TOLLGATE_FAULTHANDLER.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from packages.storage.db import connect, initialize_schema
from packages.storage.drainer import POLL_HOT_S, POLL_IDLE_S, Drainer
from packages.storage.spool import Spool

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
MERCHANT_ID = "merchant_drainer"


def _workspace(tmp_path: Path):
    db_path = tmp_path / "tollgate.db"
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO merchant (merchant_id, display_name, currency, timezone, "
            "api_key_hash, outcome_hmac_key_hash, created_at) "
            "VALUES (?, 'Drainer', 'INR', 'Asia/Kolkata', 'k', 'k', 0)",
            (MERCHANT_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path, Spool(tmp_path / "spool")


def _attempt(i: int) -> dict:
    uid = f"01DRAIN{i:019d}"
    return {
        "attempt": {
            "attempt_uid": uid, "merchant_id": MERCHANT_ID, "event_id": f"evt-{i}",
            "payload_digest": f"pd-{i}", "ingest_time": 1_000_000 + i, "client_ts": None,
            "session_id": None, "card_hash": f"card-{i}", "bin": "999001", "last4": None,
            "exp_month": None, "exp_year": None, "amount_minor": 1000, "currency": "INR",
            "ip": "198.51.100.5", "asn": None, "ua_class": "unparseable",
            "ipua_key": "k", "client_evidence": "{}",
        },
        "score": {
            "attempt_uid": uid, "score_raw": 0.1, "score_calibrated": 0.1, "prior_used": 0.001,
            "regime": "in_control", "decision": "allow", "tier_ladder": "domestic",
            "control_arm": False, "shed": False, "model_version": "rules-only-v0",
            "calibrator_version": "identity", "policy_version": 1, "rules_fired": [],
            "feature_snapshot": {}, "top_contributors": None, "incident_id": None,
            "latency_ms": 1.0, "scored_at": 1_000_000 + i,
        },
    }


class TestConnectionLifecycle:
    def test_an_idle_drainer_opens_no_connections_at_all(self, tmp_path):
        """The whole point of §12's `stat().st_size == offset` skip: doing
        nothing must COST nothing. The second recorded SIGSEGV landed in the
        machinery this now skips."""
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        drainer.drain_from_start()
        baseline = drainer.connect_calls

        drainer.start()
        time.sleep(1.5)  # ~30 polls at the old 50 ms cadence
        drainer.stop()
        spool.close()

        assert drainer.connect_calls == baseline, (
            f"an idle drainer opened {drainer.connect_calls - baseline} connection(s) "
            f"in 1.5 s; the old design opened one per poll"
        )

    def test_a_busy_drainer_reuses_one_connection(self, tmp_path):
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        drainer.drain_from_start()
        baseline = drainer.connect_calls

        drainer.start()
        for i in range(40):
            spool.append(f"uid-{i}", _attempt(i))
            time.sleep(0.02)
        time.sleep(0.5)
        drainer.stop()
        spool.close()

        opened = drainer.connect_calls - baseline
        assert opened <= 2, (
            f"the drainer opened {opened} connections while draining 40 records; "
            f"the old design opened one per poll"
        )
        assert drainer.rows_drained >= 1

    def test_the_thread_owns_its_own_connection(self, tmp_path):
        """sqlite3's check_same_thread=True must be satisfied by construction:
        the connection is created INSIDE _run, never handed across threads."""
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        drainer.start()
        spool.append("uid-x", _attempt(999))
        time.sleep(0.4)
        alive = drainer.is_alive()
        failures = drainer.consecutive_failures
        drainer.stop()
        spool.close()
        assert alive, "the drainer thread died"
        assert failures == 0, "a cross-thread sqlite3 use would have raised ProgrammingError"


class TestWalIsSetOnceAndPersists:
    def test_journal_mode_is_wal_after_initialize_schema(self, tmp_path):
        db_path, spool = _workspace(tmp_path)
        conn = connect(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        spool.close()
        assert str(mode).lower() == "wal", (
            f"journal_mode is {mode!r}; it is persisted in the DB file, so "
            f"setting it once at schema init must be sufficient"
        )

    def test_connect_no_longer_issues_journal_mode(self):
        """Re-issuing it per connection was the pathological call at 20/s."""
        import inspect

        from packages.storage import db as db_module

        source = inspect.getsource(db_module.connect)
        assert "journal_mode" not in source, (
            "connect() still switches journal_mode on every connection"
        )


class TestSupervision:
    def test_an_exception_in_a_drain_does_not_kill_the_thread(self, tmp_path, monkeypatch):
        """F-F. One OperationalError used to end persistence for the whole
        process, silently, with no log and no state anyone could observe."""
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)

        calls = {"n": 0}
        real = drainer._drain_with

        def flaky(conn):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise sqlite3.OperationalError("database is locked")
            return real(conn)

        monkeypatch.setattr(drainer, "_drain_with", flaky)
        drainer.start()
        for i in range(5):
            spool.append(f"uid-{i}", _attempt(i))
            time.sleep(0.1)
        time.sleep(2.0)
        alive = drainer.is_alive()
        drainer.stop()
        spool.close()

        assert calls["n"] > 2, "the flaky drain was never retried"
        assert alive, "the drainer thread died on an exception -- persistence stops silently"
        conn = connect(db_path)
        try:
            n = conn.execute("SELECT COUNT(*) FROM auth_attempt").fetchone()[0]
        finally:
            conn.close()
        assert n == 5, f"recovered {n}/5 rows after the transient failures"

    def test_is_alive_reports_the_truth(self, tmp_path):
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        assert drainer.is_alive() is False
        drainer.start()
        assert drainer.is_alive() is True
        drainer.stop()
        spool.close()
        assert drainer.is_alive() is False


class TestRowParity:
    @pytest.mark.slow
    def test_a_soak_drains_every_record_exactly_once(self, tmp_path):
        db_path, spool = _workspace(tmp_path)
        drainer = Drainer(db_path=db_path, spool_path=spool.path)
        drainer.start()

        n = 5000
        for i in range(n):
            spool.append(f"uid-{i}", _attempt(i))
        deadline = time.time() + 90
        while time.time() < deadline:
            conn = connect(db_path)
            try:
                got = conn.execute("SELECT COUNT(*) FROM auth_attempt").fetchone()[0]
            finally:
                conn.close()
            if got >= n:
                break
            time.sleep(0.1)
        drainer.stop()
        spool.close()
        drainer.drain_from_start()

        conn = connect(db_path)
        try:
            attempts = conn.execute("SELECT COUNT(*) FROM auth_attempt").fetchone()[0]
            scores = conn.execute("SELECT COUNT(*) FROM attempt_score").fetchone()[0]
        finally:
            conn.close()
        assert attempts == n, f"attempt row parity: {attempts} != {n}"
        assert scores == n, f"score row parity: {scores} != {n}"

    def test_the_poll_backs_off_when_idle(self):
        assert POLL_IDLE_S > POLL_HOT_S, "the idle poll is not slower than the hot one"
        assert POLL_HOT_S == 0.05, "the hot-path latency the durability tests measure moved"
