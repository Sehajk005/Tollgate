"""
Source: Day-2 Plan §L Step 6 / Decision 26 -- the scoring core, extracted
so both /v1/score (SystemClock, the storefront) and the replay driver
(VirtualClock, Step 7) call the identical path. A pure move of Day-1
routes_score.py steps 5-11 (state.clock.now_ms() through the SSE publish);
the HTTP route keeps auth + IP resolution + Stopwatch and delegates here.

`clock` and `ulid` both default to `state.clock` / `state.ulid` -- the
storefront path never passes either, so it is byte-for-byte the same
control flow Day 1 shipped. The replay driver passes its own VirtualClock
and a seed-derived UlidGenerator so that attempt_uid minting, not just
decisions, is reproducible under A13's speed=0-vs-60 comparison.

Day-3 Plan Step 7 -- the three separate record_and_read() calls (one per
rule) are replaced by one compute_features() call (itself exactly one
store.score_path() round trip, TRD §6.3), then
DayOneRules.evaluate_from_features() reads R1-R3 from that single fetch.
feature_snapshot is now the canonical 24-feature vector merged with the
rule-level snapshot (Day-3 Plan §2 D6): compute.py's FEATURE_NAMES uses a
quantile-suffixed name for R2's statistic, while the rules dict keeps the
Day-1/2 raw key names (distinct_cards_per_ip_5m etc.) that
services/dashboard/src/App.jsx already reads -- the two dicts do not
collide on keys carrying different values.
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
from packages.features.compute import (
    FEATURE_NAMES,
    FeatureContext,
    classify_ua,
    compute_features,
    ipua_key,
)
from services.scorer.deps import ScorerState

# Source: config/features.yaml `top_contributors_k` (Day-5 Plan Step 1 -- the
# value is provenanced there and covered by config_hash; this constant must
# match it). Only used when a Layer-1 model is loaded.
TOP_CONTRIBUTORS_K = 5


def _top_k_contributors_json(contribs, k: int) -> str:
    """The k feature slots (never the bias term) with the largest |contribution|,
    as a JSON list -- written to attempt_score.top_contributors."""
    feature_contribs = list(zip(FEATURE_NAMES, list(contribs)[: len(FEATURE_NAMES)]))
    ranked = sorted(feature_contribs, key=lambda kv: abs(kv[1]), reverse=True)[:k]
    return json.dumps([{"feature": name, "contribution": round(float(v), 6)} for name, v in ranked])


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

    ua_class = classify_ua(user_agent)
    ipua = ipua_key(ip, ua_class)

    feature_ctx = FeatureContext(
        merchant_id=merchant_id,
        attempt_uid=attempt_uid,
        ingest_ms=ingest_ms,
        payload_digest=state.payload_digest(body),
        event_id=body.event_id,
        ip=ip,
        ua_class=ua_class,
        card_hash=body.card_hash,
        bin=body.bin,
        amount_minor=body.amount_minor,
        session_id=body.session_id,
    )
    features = compute_features(state.window_store, feature_ctx)
    evaluation = state.rules.evaluate_from_features(features)

    # Source: Day-5 Plan Step 9 -- score yes, decide no. TRD §6.3's order is
    # features -> rules -> model -> calibration + prior correction -> policy,
    # and this runs INSIDE the latency_ms measurement stamped below. With no
    # model artifact loaded (state.model is None) the block is skipped and the
    # six score fields are exactly Day 4's -- the authorized rules-only fallback.
    if state.model is not None and state.calibrator is not None:
        # calibrate.py (and numpy) were already imported by deps._load_model.
        from packages.detect.calibrate import serving_prior, sigmoid

        model_input = [features.values[name] for name in FEATURE_NAMES]
        margin, contribs = state.model.score_one(model_input)
        pi_s = serving_prior("in_control", state)  # state carries .prior_steady_state
        score_raw = sigmoid(margin)
        score_calibrated = state.calibrator.apply(margin, pi_s)
        top_contributors = _top_k_contributors_json(contribs, TOP_CONTRIBUTORS_K)
        model_version = state.model.model_version
        calibrator_version = state.calibrator.calibrator_version
        prior_used = pi_s
    else:
        score_raw = state.rule_score(evaluation)
        score_calibrated = score_raw
        top_contributors = None
        model_version = "rules-only-v0"
        calibrator_version = "identity"
        prior_used = state.prior_steady_state

    # Decision 57 / Decision 17: applying theta_T to the calibrated posterior is
    # Day 6; the R1-R3 tier floors hold unconditionally. Unchanged.
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
        ua_class=ua_class,
        ipua_key=ipua,
        client_evidence=client_evidence,
    )

    feature_snapshot = features.snapshot()
    feature_snapshot.update(evaluation.feature_snapshot)

    score_record = ScoreRecord(
        attempt_uid=attempt_uid,
        score_raw=score_raw,
        score_calibrated=score_calibrated,
        prior_used=prior_used,
        regime="in_control",
        decision=decision.value,
        tier_ladder="domestic",
        control_arm=False,
        shed=False,
        model_version=model_version,
        calibrator_version=calibrator_version,
        policy_version=state.policy_version,
        rules_fired=evaluation.fired_names,
        feature_snapshot=feature_snapshot,
        top_contributors=top_contributors,
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
        "feature_snapshot": feature_snapshot,
        "threat_state": threat_state,
        "regime": "in_control",
        "replay": replay_snapshot,
    }
    await state.event_bus.publish(event)

    response = ScoreResponse(attempt_uid=attempt_uid, decision=decision, latency_ms=latency_ms)
    return response, event
