"""
Source: Day-6 Plan §4 (tests/characterization, non-gating) / Impl Plan §1.2
-- a snapshot of the incident / entity / transition / enforcement rows a
fixed synthetic burst produces. A failure here is a PROMPT TO LOOK
(regenerate the snapshot or find the regression), never a build gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.storage.db import connect
from tests.acceptance._day6_helpers import (
    build_state,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

pytestmark = pytest.mark.characterization

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "day6_incident_shape.json"
MERCHANT = "m-shape"


def _shape(tmp_path) -> dict:
    db = make_db(tmp_path)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, cusum_h=3.0, cooldown_seconds=100_000, control_fraction=0.0)
    seed_baseline(db, MERCHANT, hourly_rate=60.0, flagged_rate_mean=1.0)
    state = build_state(db, tmp_path / "sp", MERCHANT)
    events = [
        {"t_ms": i * 1200, "ip": "203.0.113.7", "card_hash": f"c-{i:03d}", "bin": "424242"}
        for i in range(60)
    ]
    score_stream(state, MERCHANT, events)
    state.spool.close()
    state.drainer.drain_from_start()

    conn = connect(db)
    try:
        inc = conn.execute(
            "SELECT state, detector, peak_tier, attempts_total, attempts_before_alert, "
            "cards_exposed_before_alert, pinned_policy_version FROM incident"
        ).fetchall()
        ent = conn.execute("SELECT entity_type, pseudonym FROM incident_entity").fetchall()
        trans = conn.execute("SELECT from_tier, to_tier FROM tier_transition ORDER BY at").fetchall()
        enf = conn.execute(
            "SELECT tier, requires_confirmation, confirmed_by IS NULL AS unconfirmed, "
            "applied_at IS NULL AS unapplied FROM enforcement_action ORDER BY tier"
        ).fetchall()
        n_with_incident = conn.execute(
            "SELECT COUNT(*) AS c FROM attempt_score WHERE incident_id IS NOT NULL"
        ).fetchone()["c"]
    finally:
        conn.close()

    return {
        "n_incidents": len(inc),
        "incident": [dict(r) for r in inc],
        "n_entities": len(ent),
        "entity_types": sorted(r["entity_type"] for r in ent),
        "pseudonyms": sorted(r["pseudonym"] for r in ent),
        "transitions": [[r["from_tier"], r["to_tier"]] for r in trans],
        "enforcement": [dict(r) for r in enf],
        "n_attempt_score_with_incident": n_with_incident,
    }


class TestIncidentShape:
    def test_shape_matches_the_committed_snapshot(self, tmp_path):
        fresh = _shape(tmp_path)
        if not SNAPSHOT.exists():
            SNAPSHOT.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            pytest.skip(f"wrote first-run snapshot to {SNAPSHOT.name}")
        committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        assert fresh == committed, (
            "Day-6 incident shape drifted from the committed snapshot -- regenerate "
            f"{SNAPSHOT.name} or investigate:\n"
            f"  fresh    = {json.dumps(fresh, sort_keys=True)}\n"
            f"  snapshot = {json.dumps(committed, sort_keys=True)}"
        )
