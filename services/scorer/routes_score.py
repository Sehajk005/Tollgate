"""
Source: Implementation Plan v2.1 Day 1 -- POST /v1/score. Auth -> validation
-> three hard rules -> Decision -> spool-always -> SSE publish -> respond.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from packages.clock.stopwatch import Stopwatch
from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.contracts.wire import ScoreRequest, ScoreResponse
from packages.detect.policy import apply_auto_ceiling
from packages.detect.rules import RuleInput
from services.scorer.auth import resolve_merchant_id
from services.scorer.deps import ScorerState, get_scorer_state
from services.scorer.net import resolve_client_ip

router = APIRouter()


@router.post("/v1/score", response_model=ScoreResponse)
async def score(
    request: Request,
    body: ScoreRequest,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> ScoreResponse:
    stopwatch = Stopwatch()

    conn = state.db_read_conn()
    try:
        merchant_id = resolve_merchant_id(conn, x_tollgate_key)
    finally:
        conn.close()
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    ip = resolve_client_ip(request)
    ingest_ms = state.clock.now_ms()
    attempt_uid = state.ulid.new()

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

    latency_ms = stopwatch.elapsed_ms()

    client_evidence = json.dumps({"user_agent": request.headers.get("user-agent", "")})

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
        # No BIN metadata join on Day 1 (Threat Model tier-ladder selection is
        # Day 3+ work); 'domestic' is a documented placeholder that does not
        # affect Day 1 behaviour since no rule floors above `challenge`.
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

    await state.event_bus.publish(
        {
            "attempt_uid": attempt_uid,
            "decision": decision.value,
            "ip": ip,
            "bin": body.bin,
            "ingest_time": ingest_ms,
        }
    )

    return ScoreResponse(attempt_uid=attempt_uid, decision=decision, latency_ms=latency_ms)
