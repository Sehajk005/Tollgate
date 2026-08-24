"""
Source: Day-2 Plan §L Step 6 / Decision 26 -- the scoring core, extracted
so both /v1/score (SystemClock, the storefront) and the replay driver
(VirtualClock, Step 7) call the identical path. A pure move of Day-1
routes_score.py steps 5-11 (state.clock.now_ms() through the SSE publish);
the HTTP route keeps auth + IP resolution + Stopwatch and delegates here.
No behaviour change of any kind: the 55 Day-1 tests are the proof, and this
file introduces zero edits to any of them.

`clock` and `ulid` both default to `state.clock` / `state.ulid` -- the
storefront path never passes either, so it is byte-for-byte the same
control flow Day 1 shipped. The replay driver passes its own VirtualClock
and a seed-derived UlidGenerator so that attempt_uid minting, not just
decisions, is reproducible under A13's speed=0-vs-60 comparison.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from packages.clock.clock import Clock
from packages.clock.ids import UlidGenerator
from packages.clock.stopwatch import Stopwatch
from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.contracts.wire import ScoreRequest, ScoreResponse
from packages.detect.policy import apply_auto_ceiling
from packages.detect.rules import RuleInput
from services.scorer.deps import ScorerState


async def score_attempt(
    state: ScorerState,
    *,
    merchant_id: str,
    ip: str,
    body: ScoreRequest,
    clock: Optional[Clock] = None,
    ulid: Optional[UlidGenerator] = None,
    stopwatch: Optional[Stopwatch] = None,
    user_agent: str = "",
) -> Tuple[ScoreResponse, dict]:
    active_clock = clock if clock is not None else state.clock
    active_ulid = ulid if ulid is not None else state.ulid
    active_stopwatch = stopwatch if stopwatch is not None else Stopwatch()

    ingest_ms = active_clock.now_ms()
    attempt_uid = active_ulid.new()

    rule_input = RuleInput(
        merchant_id=merchant_id,
        attempt_uid=attempt_uid,
        ingest_ms=ingest_ms,
        ip=ip,
        card_hash=body.card_hash,
        bin=body.bin,
    )
    evaluation = state.rules.evaluate(rule_input)
    decision = apply_auto_ceiling(evaluation.minimum_tier)

    latency_ms = active_stopwatch.elapsed_ms()

    client_evidence = json.dumps({"user_agent": user_agent})

    attempt = AttemptRecord(
        attempt_uid=attempt_uid,
        merchant_id=merchant_id,
        event_id=body.event_id,
        payload_digest=state.payload_digest(body),
        ingest_time=ingest_ms,
        client_ts=None,
        session_id=body.session_id,
        card_hash=body.card_hash,
        bin=body.bin,
        last4=body.last4,
        exp_month=body.exp_month,
        exp_year=body.exp_year,
        amount_minor=body.amount_minor,
        currency=body.currency,
        ip=ip,
        asn=None,
        ua_class=None,
        ipua_key=None,
        client_evidence=client_evidence,
    )

    score_value = state.rule_score(evaluation)
    score_record = ScoreRecord(
        attempt_uid=attempt_uid,
        score_raw=score_value,
        score_calibrated=score_value,
        prior_used=state.prior_steady_state,
        regime="in_control",
        decision=decision.value,
        tier_ladder="domestic",
        control_arm=False,
        shed=False,
        model_version="rules-only-v0",
        calibrator_version="identity",
        policy_version=state.policy_version,
        rules_fired=evaluation.fired_names,
        feature_snapshot=evaluation.feature_snapshot,
        top_contributors=None,
        incident_id=None,
        latency_ms=latency_ms,
        scored_at=ingest_ms,
    )

    state.spool.append(
        attempt_uid,
        {"attempt": attempt.to_dict(), "score": score_record.to_dict()},
    )

    threat_state = None
    if state.threat is not None:
        threat_state = state.threat.observe(
            rules_fired=evaluation.fired_names, decision=decision.value, ingest_ms=ingest_ms,
        )

    if state.replay_driver is not None:
        replay_snapshot = state.replay_driver.status.to_dict()
    else:
        replay_snapshot = {
            "state": "idle", "tier": None, "seed": None, "speed": None,
            "sent": 0, "total": 0, "episode_id": None, "virtual_time_ms": 0,
        }

    # Source: Day-2 Plan Decision 34 -- SSE gains rules_fired, feature_snapshot,
    # threat_state, replay; card_hash is never on the stream (/v1/stream is
    # unauthenticated -- publishing it would disclose threshold proximity).
    event = {
        "attempt_uid": attempt_uid,
        "decision": decision.value,
        "ip": ip,
        "bin": body.bin,
        "ingest_time": ingest_ms,
        "rules_fired": evaluation.fired_names,
        "feature_snapshot": evaluation.feature_snapshot,
        "threat_state": threat_state,
        "regime": "in_control",
        "replay": replay_snapshot,
    }
    await state.event_bus.publish(event)

    response = ScoreResponse(attempt_uid=attempt_uid, decision=decision, latency_ms=latency_ms)
    return response, event
