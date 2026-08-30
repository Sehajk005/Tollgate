"""
Source: Day-6 Plan §4 / Threat Model §4/P1 / Backend Schema §3.3 --
`step_up` / `block` are PROPOSED, never in force: their enforcement_action
rows carry `confirmed_by IS NULL` AND `applied_at IS NULL`
(`requires_confirmation = 1`), and the decision the client receives is never
above `challenge`.
"""

from __future__ import annotations

from packages.storage.db import connect
from tests.acceptance._day6_helpers import (
    build_state,
    drain,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-enf"
_ALLOWED_DECISIONS = {"allow", "monitor", "throttle", "challenge"}


class TestEnforcementConfirmation:
    def test_step_up_or_block_rows_are_unconfirmed_and_the_decision_is_capped(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=300)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp", MERCHANT)

        events = [
            {"t_ms": i * 1500, "ip": "203.0.113.7", "card_hash": f"c-{i:03d}", "bin": "424242"}
            for i in range(48)
        ]
        sse = score_stream(state, MERCHANT, events)
        drain(state)

        for e in sse:
            assert e["decision"] in _ALLOWED_DECISIONS, e["decision"]

        conn = connect(db)
        try:
            rows = conn.execute(
                "SELECT tier, requires_confirmation, confirmed_by, applied_at "
                "FROM enforcement_action WHERE tier IN ('step_up', 'block')"
            ).fetchall()
        finally:
            conn.close()
        assert rows, "expected at least one step_up/block (proposed) enforcement_action row"
        for r in rows:
            assert r["requires_confirmation"] == 1
            assert r["confirmed_by"] is None
            assert r["applied_at"] is None

    def test_throttle_and_challenge_rows_are_in_force(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, cusum_h=3.0)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp", MERCHANT)
        events = [
            {"t_ms": i * 1500, "ip": "198.51.100.9", "card_hash": f"k-{i:03d}", "bin": "411111"}
            for i in range(48)
        ]
        score_stream(state, MERCHANT, events)
        drain(state)
        conn = connect(db)
        try:
            rows = conn.execute(
                "SELECT tier, requires_confirmation, confirmed_by, applied_at "
                "FROM enforcement_action WHERE tier IN ('throttle', 'challenge')"
            ).fetchall()
        finally:
            conn.close()
        assert rows
        for r in rows:
            assert r["requires_confirmation"] == 0
            assert r["confirmed_by"] == "auto"
            assert r["applied_at"] is not None
