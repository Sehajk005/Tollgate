"""
Source: Implementation Plan v2.1 Day 1 -- POST /v1/score. Auth -> validation
-> three hard rules -> Decision -> spool-always -> SSE publish -> respond.

Day-2 Plan §L Step 6 / Decision 26: the route does auth + IP resolution +
Stopwatch only, delegating steps 5-11 to services/scorer/scoring.py::
score_attempt() -- the seam the replay driver (Step 7) also calls.

Day-7 Plan §4 Steps 3-4 -- the route now carries the two rungs BELOW the full
score path, both OUTSIDE the Layer-2 atomic block (§12 trap 9):

  FULL            score_attempt() as before.
  RULES-ONLY/SHED merchant token bucket empty -> shed_incr() the per-merchant
                  counter, evaluate R1 ONLY against it (Decision 15), set
                  `X-Tollgate-Shed: 1`, spool a shed=True ScoreRecord, return.
  FAIL-OPEN       any exception from score_attempt() -> record it on the
                  AvailabilityMonitor, spool an `allow` ScoreRecord with a
                  `fail_open:<reason>` degraded_reason, return `allow`.

Authentication is fenced off from all of this: a cold key cache + an
unavailable auth DB returns 503, never `allow` (Decision 89).
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from packages.clock.stopwatch import Stopwatch
from packages.contracts.decision import Decision
from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.contracts.wire import ScoreRequest, ScoreResponse
from packages.detect.policy import apply_auto_ceiling
from packages.features.compute import FEATURE_NAMES, classify_ua, ipua_key
from services.scorer.auth import AuthBackendUnavailable, resolve_merchant_id_cached
from services.scorer.deps import ScorerState, get_scorer_state
from services.scorer.net import resolve_client_ip
from services.scorer.scoring import score_attempt

router = APIRouter()

_IDLE_REPLAY = {
    "state": "idle", "tier": None, "seed": None, "speed": None,
    "sent": 0, "total": 0, "episode_id": None, "virtual_time_ms": 0,
}


def _classify_fail_open(exc: BaseException) -> str:
    """Map an exception from `score_attempt` to a `degraded_reason` suffix.
    Redis / connection / timeout faults are the window store; everything else
    (a model that raised, a calibrator that raised) is `model`."""
    module = type(exc).__module__ or ""
    if "redis" in module or isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return "window_store"
    return "model"


def _synthetic_records(
    state: ScorerState,
    *,
    attempt_uid: str,
    merchant_id: str,
    ip: str,
    body: ScoreRequest,
    user_agent: str,
    now_ms: int,
    decision: Decision,
    shed: bool,
    feature_snapshot: dict,
    latency_ms: int,
) -> Tuple[AttemptRecord, ScoreRecord]:
    ua_class = classify_ua(user_agent)
    attempt = AttemptRecord(
        attempt_uid=attempt_uid,
        merchant_id=merchant_id,
        event_id=body.event_id,
        payload_digest=state.payload_digest(body),
        ingest_time=now_ms,
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
        ua_class=ua_class,
        ipua_key=ipua_key(ip, ua_class),
        client_evidence=json.dumps({"user_agent": user_agent}),
    )
    score = ScoreRecord(
        attempt_uid=attempt_uid,
        score_raw=0.0,
        score_calibrated=0.0,
        prior_used=state.prior_steady_state,
        regime="in_control",
        decision=decision.value,
        tier_ladder="domestic",
        control_arm=False,
        shed=shed,
        model_version="rules-only-v0",
        calibrator_version="identity",
        policy_version=state.policy_version,
        rules_fired=[],
        feature_snapshot=feature_snapshot,
        top_contributors=None,
        incident_id=None,
        latency_ms=latency_ms,
        scored_at=now_ms,
    )
    return attempt, score


async def _shed(
    state: ScorerState,
    response: Response,
    *,
    merchant_id: str,
    ip: str,
    body: ScoreRequest,
    user_agent: str,
    now_ms: int,
    stopwatch: Stopwatch,
) -> ScoreResponse:
    """Source: Day-7 Plan §4 Step 3 -- the rules-only shed rung. R1 ONLY is
    evaluated against the merchant-scoped shed counter (Decision 15); R2/R3
    structurally cannot run without `compute_features`. The zero-filled
    snapshot keeps `eval.corpus.load_feature_corpus` total (§12 trap 6)."""
    ttl_ms = state.admission.config.shed_ttl_ms
    n = state.window_store.shed_incr(merchant_id, ip, now_ms, ttl_ms)
    r1_threshold = state.rules._r1_threshold
    tier = Decision.THROTTLE if n >= r1_threshold else Decision.ALLOW
    tier = apply_auto_ceiling(tier)  # the auto-ceiling wraps the shed tier too

    attempt_uid = state.ulid.new()
    snapshot = {name: 0.0 for name in FEATURE_NAMES}
    snapshot["attempts_per_ip_60s"] = float(n)
    snapshot["degraded_reason"] = "shed"
    attempt, score = _synthetic_records(
        state, attempt_uid=attempt_uid, merchant_id=merchant_id, ip=ip, body=body,
        user_agent=user_agent, now_ms=now_ms, decision=tier, shed=True,
        feature_snapshot=snapshot, latency_ms=stopwatch.elapsed_ms(),
    )
    state.spool.append(attempt_uid, {"attempt": attempt.to_dict(), "score": score.to_dict()})

    response.headers["X-Tollgate-Shed"] = "1"

    # Source: Day-8 Plan Step 2 (G2) -- the shed path previously published
    # nothing, so D0's rules-only banner and the Stream Rail's hollow tick had
    # no data source. Publish the EXACT event shape `_fail_open` already uses,
    # with `availability.shed=True`. The latency budget is measured on
    # `stopwatch.elapsed_ms()` stamped before this call (`_fail_open` set the
    # precedent), so `test_admission_shed.py`'s < 5 ms gate is unaffected.
    alerting = (
        state.availability.is_alerting(merchant_id, now_ms)
        if state.availability is not None else False
    )
    await state.event_bus.publish({
        "attempt_uid": attempt_uid,
        "decision": tier.value,
        "ip": ip,
        "bin": body.bin,
        "ingest_time": now_ms,
        "rules_fired": [],
        "feature_snapshot": snapshot,
        "threat_state": None,
        "regime": "in_control",
        "replay": _IDLE_REPLAY,
        "incident": None,
        "enforcement": {"active": 0, "k_max": 0, "advisory_mode": False},
        "control_arm": False,
        "availability": {"fail_open": False, "alert": alerting, "shed": True},
    })
    return ScoreResponse(attempt_uid=attempt_uid, decision=tier, latency_ms=stopwatch.elapsed_ms())


async def _fail_open(
    state: ScorerState,
    *,
    merchant_id: str,
    ip: str,
    body: ScoreRequest,
    user_agent: str,
    now_ms: int,
    stopwatch: Stopwatch,
    reason: str,
) -> ScoreResponse:
    """Source: Day-7 Plan §4 Step 4 -- the bottom rung. The response is ALWAYS
    `allow` (Decision 89); the AvailabilityMonitor turns a sustained breach
    into one ERROR log + an `alert` flag per window, never a 5xx."""
    if state.availability is not None:
        state.availability.record_fail_open(merchant_id, now_ms, reason)
        alerting = state.availability.is_alerting(merchant_id, now_ms)
    else:
        alerting = False

    attempt_uid = state.ulid.new()
    snapshot = {name: 0.0 for name in FEATURE_NAMES}
    snapshot["degraded_reason"] = f"fail_open:{reason}"
    attempt, score = _synthetic_records(
        state, attempt_uid=attempt_uid, merchant_id=merchant_id, ip=ip, body=body,
        user_agent=user_agent, now_ms=now_ms, decision=Decision.ALLOW, shed=False,
        feature_snapshot=snapshot, latency_ms=stopwatch.elapsed_ms(),
    )
    state.spool.append(attempt_uid, {"attempt": attempt.to_dict(), "score": score.to_dict()})

    # Surface the degraded state on the stream so the dashboard sees the
    # `alert` without waiting for the next healthy attempt (Day-7 §5 row 9).
    await state.event_bus.publish({
        "attempt_uid": attempt_uid,
        "decision": "allow",
        "ip": ip,
        "bin": body.bin,
        "ingest_time": now_ms,
        "rules_fired": [],
        "feature_snapshot": snapshot,
        "threat_state": None,
        "regime": "in_control",
        "replay": _IDLE_REPLAY,
        "incident": None,
        "enforcement": {"active": 0, "k_max": 0, "advisory_mode": False},
        "control_arm": False,
        # Day-8 Plan Step 2 -- `shed` added so `availability` is total on every
        # published event; a fail-open is not a shed.
        "availability": {"fail_open": True, "alert": alerting, "shed": False},
    })
    return ScoreResponse(attempt_uid=attempt_uid, decision=Decision.ALLOW, latency_ms=stopwatch.elapsed_ms())


@router.post("/v1/score", response_model=ScoreResponse)
async def score(
    request: Request,
    body: ScoreRequest,
    response: Response,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> ScoreResponse:
    stopwatch = Stopwatch()
    now_ms = state.clock.now_ms()

    # -- authentication: fenced off from fail-open (Decision 89) -------------
    try:
        merchant_id = resolve_merchant_id_cached(state, x_tollgate_key)
    except AuthBackendUnavailable:
        raise HTTPException(status_code=503, detail="auth backend unavailable")
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    ip = resolve_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    # -- admission: token bucket -> rules-only shed rung --------------------
    if state.admission is not None and not state.admission.try_consume(merchant_id, now_ms):
        return await _shed(
            state, response, merchant_id=merchant_id, ip=ip, body=body,
            user_agent=user_agent, now_ms=now_ms, stopwatch=stopwatch,
        )

    # -- full path, wrapped for fail-open ----------------------------------
    try:
        result, _event = await score_attempt(
            state, merchant_id=merchant_id, ip=ip, body=body,
            stopwatch=stopwatch, user_agent=user_agent,
        )
        return result
    except Exception as exc:  # noqa: BLE001 -- any fault fails OPEN to `allow`
        return await _fail_open(
            state, merchant_id=merchant_id, ip=ip, body=body, user_agent=user_agent,
            now_ms=now_ms, stopwatch=stopwatch, reason=_classify_fail_open(exc),
        )
