"""
Source: Day-6 Plan §4 / Backend Schema §3.1 -- a `policy_config` version
landing mid-incident does NOT change the open incident's tier resolution;
it resolves against `pinned_policy_version` (stamped at open).
"""

from __future__ import annotations

from packages.storage.db import connect
from packages.storage.repository import load_policy_config
from tests.acceptance._day6_helpers import (
    TIER_LADDER,
    build_state,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

MERCHANT = "m-pin"
# v2 shifts every theta near 1.0 -- under v2 the same posterior clears
# nothing, so a wrongly-unpinned incident would collapse to `monitor`.
V2_THRESHOLDS = {"throttle": 0.90, "challenge": 0.95, "step_up": 0.98, "block": 0.99}
_TIER_ORDER = ["allow", "monitor", "throttle", "challenge", "step_up", "block"]


class TestPolicyPinning:
    def test_a_new_version_mid_incident_does_not_move_the_open_incidents_tier(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, version=1, thresholds=TIER_LADDER, cusum_h=3.0, cooldown_seconds=3000)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp", MERCHANT)
        assert state.policy.version == 1

        first_half = [
            {"t_ms": i * 1500, "ip": "203.0.113.7", "card_hash": f"c-{i:03d}", "bin": "424242"}
            for i in range(24)
        ]
        sse1 = score_stream(state, MERCHANT, first_half)
        assert any(e["incident"] for e in sse1), "incident should have opened under v1"
        peak_under_v1 = max(
            (e["incident"]["proposed_tier"] for e in sse1 if e["incident"]),
            key=_TIER_ORDER.index,
        )
        assert peak_under_v1 in ("challenge", "step_up", "block")

        seed_policy(db, MERCHANT, version=2, thresholds=V2_THRESHOLDS, cusum_h=3.0, cooldown_seconds=3000)
        conn = connect(db)
        try:
            v2 = load_policy_config(conn, MERCHANT, 2)
        finally:
            conn.close()
        state.policy = v2
        state.policy_versions[2] = v2

        second_half = [
            {"t_ms": (24 + i) * 1500, "ip": "203.0.113.7", "card_hash": f"c-{100 + i:03d}", "bin": "424242"}
            for i in range(24)
        ]
        sse2 = score_stream(state, MERCHANT, second_half)
        incident_events = [e["incident"] for e in sse2 if e["incident"]]
        assert incident_events, "the incident is still live in the second half"
        assert all(
            ev["proposed_tier"] in ("throttle", "challenge", "step_up", "block")
            for ev in incident_events
        ), [ev["proposed_tier"] for ev in incident_events]

    def test_the_incident_row_records_the_pinned_version(self, tmp_path):
        db = make_db(tmp_path)
        seed_merchant(db, MERCHANT)
        seed_policy(db, MERCHANT, version=1, cusum_h=3.0)
        seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
        state = build_state(db, tmp_path / "sp", MERCHANT)
        events = [
            {"t_ms": i * 1500, "ip": "198.51.100.5", "card_hash": f"c-{i:03d}", "bin": "424242"}
            for i in range(20)
        ]
        score_stream(state, MERCHANT, events)
        state.spool.close()
        state.drainer.drain_from_start()
        conn = connect(db)
        try:
            row = conn.execute("SELECT pinned_policy_version FROM incident").fetchone()
        finally:
            conn.close()
        assert row is not None and row["pinned_policy_version"] == 1
