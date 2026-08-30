"""
Source: Day-6 Plan §4 / §8 -- THE Day-6 exit gate. One incident opens on
`handmade_40.jsonl` at the hand-counted alert seq.

Per Decision 14 / Impl Plan §1.8 this fixture and its `alert_seq` are an
ABSOLUTE carve-out: the implementation agent must not generate the events,
the feature values, or the alert point. Until a human supplies:

  tests/fixtures/handmade_40.jsonl            (40 events; also read by test_handmade_40.py)
  tests/fixtures/handmade_40.expected.jsonl   (per-seq feature values PLUS one final line:
      {"seq": null, "incident": {"alert_seq": N, "detector": "...",
                                 "entity_type": "...", "entity_key": "..."}})
  tests/fixtures/handmade_40.sha256

this test xfails (strict=False) with a named reason -- it does not, and must
not, generate them. It mirrors test_handmade_40.py exactly.

Note: the incident alert point depends on lambda_0(t), which depends on the
store baseline. This test derives a baseline from the 40 events' own volume
(a deterministic, transparent assumption); if the human's paper computation
assumed a different baseline, `handmade_40.baseline.json` may be supplied
alongside to pin it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance._day6_helpers import (
    TIER_LADDER,
    build_state,
    make_db,
    score_stream,
    seed_baseline,
    seed_merchant,
    seed_policy,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
EVENTS_PATH = FIXTURES_DIR / "handmade_40.jsonl"
EXPECTED_PATH = FIXTURES_DIR / "handmade_40.expected.jsonl"
SHA_PATH = FIXTURES_DIR / "handmade_40.sha256"
BASELINE_PATH = FIXTURES_DIR / "handmade_40.baseline.json"

FIXTURE_PRESENT = EVENTS_PATH.exists() and EXPECTED_PATH.exists() and SHA_PATH.exists()
MERCHANT = "merchant_handmade"


def _read_alert_line():
    for line in EXPECTED_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("seq") is None and "incident" in row:
            return row["incident"]
    return None


@pytest.mark.xfail(
    not FIXTURE_PRESENT,
    reason=(
        "tests/fixtures/handmade_40.{jsonl,expected.jsonl,sha256} and the "
        "hand-counted `alert_seq` line have not been authored yet. Per "
        "Decisions.md decision 14 / Impl Plan v2.1 §1.8, this fixture and its "
        "alert point must be computed on paper by a human and are carved out "
        "of the implementation agent's scope entirely -- this test does not, "
        "and must not, generate them."
    ),
    strict=False,
)
def test_one_incident_opens_at_the_hand_counted_alert_seq(tmp_path):
    if not FIXTURE_PRESENT:
        pytest.fail("handmade_40 fixture files are not present yet")

    events_raw = [
        json.loads(line)
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    alert = _read_alert_line()
    assert alert is not None, (
        'handmade_40.expected.jsonl has no {"seq": null, "incident": {...}} line'
    )

    db = make_db(tmp_path)
    seed_merchant(db, MERCHANT)
    seed_policy(db, MERCHANT, thresholds=TIER_LADDER, cusum_h=3.0, cooldown_seconds=100_000)

    if BASELINE_PATH.exists():
        b = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        seed_baseline(
            db, MERCHANT,
            hourly_rate=float(b.get("hourly_rate", 60.0)),
            flagged_rate_mean=float(b.get("flagged_rate_mean", 1.0)),
            q30m=b.get("cards_per_ip_30m"),
        )
    else:
        span_ms = max(e["t_ms"] for e in events_raw) - min(e["t_ms"] for e in events_raw)
        span_hours = max(span_ms / 3_600_000.0, 1e-6)
        seed_baseline(
            db, MERCHANT,
            hourly_rate=len(events_raw) / span_hours,
            flagged_rate_mean=1.0,
        )

    state = build_state(db, tmp_path / "sp", MERCHANT)
    stream = [
        {
            "t_ms": e["t_ms"], "ip": e["ip"], "card_hash": e["card_hash"],
            "bin": e["bin"], "amount_minor": e.get("amount_minor", 1999),
            "event_id": e["event_id"], "session_id": e.get("session_id"),
        }
        for e in events_raw
    ]
    sse = score_stream(state, MERCHANT, stream)

    incidents = state.incidents.all_incidents()
    assert len(incidents) == 1, f"expected exactly one incident, got {len(incidents)}"

    first_incident_seq = next(
        (events_raw[i]["seq"] for i, e in enumerate(sse) if e["incident"] is not None), None
    )
    assert first_incident_seq == alert["alert_seq"], (
        f"incident opened at seq {first_incident_seq}, hand-counted alert_seq is {alert['alert_seq']}"
    )
    inc = incidents[0]
    if "detector" in alert:
        assert alert["detector"] in inc.detector
    if "entity_type" in alert:
        assert inc.entity.entity_type == alert["entity_type"]
    if "entity_key" in alert:
        assert inc.entity.entity_key == alert["entity_key"]
