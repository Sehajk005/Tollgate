"""
Source: Day-4 Plan (rev. 2) §6 test 17 -- "Loader is idempotent." Running
load_truth twice at one seed -> identical row count, identical rows, no
IntegrityError; a different seed yields different episode_ids (F14).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.load import load_truth
from packages.simulator.generate import build_stream
from packages.storage.db import connect, initialize_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
MERCHANT_ID = "m-load-test"


def _fresh_db(tmp_path):
    db_path = tmp_path / "eval_load_test.db"
    initialize_schema(db_path, SCHEMA_PATH)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO merchant (merchant_id, display_name, currency, timezone, "
        "api_key_hash, outcome_hmac_key_hash, created_at) "
        "VALUES (?, 'test', 'INR', 'Asia/Kolkata', 'x', 'x', '2026-01-01T00:00:00')",
        (MERCHANT_ID,),
    )
    return conn


def _seed_auth_attempts(conn, events):
    """Insert one auth_attempt row per event so load_truth has something to FK against."""
    for event in events:
        conn.execute(
            "INSERT INTO auth_attempt (attempt_uid, merchant_id, event_id, payload_digest, "
            "ingest_time, card_hash, bin, amount_minor, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"attempt-{event.event_id}", MERCHANT_ID, event.event_id, f"digest-{event.event_id}",
                event.t_ms, event.card_hash, event.bin, event.amount_minor, event.currency,
            ),
        )
    conn.commit()


class TestLoaderIsIdempotent:
    def test_running_twice_yields_identical_row_counts_and_no_integrity_error(self, tmp_path):
        conn = _fresh_db(tmp_path)
        result = build_stream(seed=42, tier="easy", hours=1)
        _seed_auth_attempts(conn, result.events)
        runs = [("easy", result)]

        first = load_truth(conn, MERCHANT_ID, runs)
        assert first.labels_skipped_no_attempt == 0
        episode_count_1 = conn.execute("SELECT COUNT(*) AS c FROM episode_truth").fetchone()["c"]
        label_count_1 = conn.execute("SELECT COUNT(*) AS c FROM attempt_label").fetchone()["c"]

        second = load_truth(conn, MERCHANT_ID, runs)  # must not raise IntegrityError
        episode_count_2 = conn.execute("SELECT COUNT(*) AS c FROM episode_truth").fetchone()["c"]
        label_count_2 = conn.execute("SELECT COUNT(*) AS c FROM attempt_label").fetchone()["c"]

        assert episode_count_1 == episode_count_2
        assert label_count_1 == label_count_2
        assert first.episodes_written == second.episodes_written
        assert first.labels_written == second.labels_written

        rows_1 = {r["episode_id"]: dict(r) for r in conn.execute("SELECT * FROM episode_truth")}
        conn.commit()
        rows_2 = {r["episode_id"]: dict(r) for r in conn.execute("SELECT * FROM episode_truth")}
        assert rows_1 == rows_2

        conn.close()

    def test_labels_without_a_matching_auth_attempt_are_skipped_and_counted(self, tmp_path):
        conn = _fresh_db(tmp_path)
        result = build_stream(seed=42, tier="easy", hours=1)
        # Deliberately do NOT seed auth_attempt rows -- every label should skip.
        runs = [("easy", result)]

        loaded = load_truth(conn, MERCHANT_ID, runs)
        assert loaded.labels_written == 0
        assert loaded.labels_skipped_no_attempt == len(result.labels)
        assert loaded.episodes_written == len(result.episodes)  # episode_truth is unconditional

        conn.close()

    def test_a_different_seed_yields_different_episode_ids(self, tmp_path):
        conn = _fresh_db(tmp_path)
        result_a = build_stream(seed=1, tier="easy", hours=1)
        result_b = build_stream(seed=2, tier="easy", hours=1)
        load_truth(conn, MERCHANT_ID, [("easy", result_a)])
        load_truth(conn, MERCHANT_ID, [("easy", result_b)])

        episode_ids = {r["episode_id"] for r in conn.execute("SELECT episode_id FROM episode_truth")}
        assert result_a.episodes[0].episode_id != result_b.episodes[0].episode_id
        assert episode_ids == {result_a.episodes[0].episode_id, result_b.episodes[0].episode_id}

        conn.close()
