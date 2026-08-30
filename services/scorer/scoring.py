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

Day-6 Plan §3.10 -- ONE guarded seam. Between the existing model block and
`apply_auto_ceiling`, and inside the latency_ms window:
    layer2.regime_for()   -> alarm regime (picks the serving prior)
    layer2.observe()      -> CusumStep + DriftStep + DetectorSignal
    incidents.step()      -> Incident | None  (the state machine)
    policy.resolve()      -> PolicyOutcome (proposed / in-force tier, entity,
                             control arm, ladder, advisory mode)
When `state.policy is None` the entire block is skipped and `decision`,
`tier_ladder`, `regime`, `control_arm`, `incident_id`, `policy_version` are
exactly Day 5's -- the guard argument Decision 26 / Day 5 both used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Tuple

from packages.clock.clock import Clock
from packages.clock.ids import UlidGenerator
from packages.clock.stopwatch import Stopwatch
from packages.contracts.decision import Decision
from packages.contracts.records import AttemptRecord, ScoreRecord
from packages.contracts.wire import ScoreRequest, ScoreResponse
from packages.detect.episode import IllegalTransition
from packages.detect.policy import _rank, apply_auto_ceiling, families_from_rules, resolve_entity
from packages.features.compute import (
    FEATURE_NAMES,
    FeatureContext,
    classify_ua,
    compute_features,
    ipua_key,
)
from services.scorer.deps import DECISION_CACHE_MAX, ScorerState

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


def _remember_decision(
    state: ScorerState, idem_digest: str, attempt_uid: str, decision_value: str
) -> None:
    """Source: Day-7 Plan §4 Step 2 -- record the resolved decision so a later
    idempotent replay of the same request returns it verbatim. Bounded FIFO:
    `dict` preserves insertion order, so evicting `next(iter(...))` drops the
    oldest entry. In-process only (Decision 71's single-worker trade)."""
    if not idem_digest:
        return
    cache = state.decision_cache
    if idem_digest in cache:
        return
    cache[idem_digest] = (attempt_uid, decision_value)
    if len(cache) > DECISION_CACHE_MAX:
        del cache[next(iter(cache))]


def _action_id(incident_id: str, entity_type: str, entity_key: str, tier: str) -> str:
    """Deterministic enforcement_action id -- one row per (incident, entity,
    tier), so the drainer's byte-0 re-drain is idempotent."""
    raw = f"{incident_id}|{entity_type}|{entity_key}|{tier}"
    return "A" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:25].upper()


@dataclass(frozen=True)
class _Day6Outcome:
    decision: Decision
    tier_ladder: str
    control_arm: bool
    policy_version: int
    incident_id: Optional[str]
    threat_state: Optional[str]
    sse_incident: Optional[dict]
    sse_enforcement: dict
    spool_extras: dict


def _pinned_snapshot(state: ScorerState, merchant_id: str, version: int):
    """Backend Schema §3.1 -- an open incident resolves against its PINNED
    policy version. Cache hit is the norm (the live version); a pinned
    version is loaded from the DB once, then cached, so this is never a
    per-attempt read on the hot path."""
    cached = state.policy_versions.get(version)
    if cached is not None:
        return cached
    try:
        from packages.storage.db import connect
        from packages.storage.repository import load_policy_config

        conn = connect(state.db_path, read_only=True)
        try:
            snap = load_policy_config(conn, merchant_id, version)
        finally:
            conn.close()
        if snap is not None:
            state.policy_versions[snap.version] = snap
        return snap
    except Exception:  # noqa: BLE001 -- fall back to the live snapshot
        return None


def _resolve_layer2(
    state: ScorerState,
    *,
    # ------------------------------------------------------------------
    # Day-7 Plan §3 R3 / §12 trap 9 -- THIS BLOCK MUST CONTAIN NO `await`.
    # Layer-2 concurrency safety (100 concurrent scores == sequential, pinned
    # by tests/acceptance/test_concurrent_cusum.py) rests entirely on the
    # whole Layer-2 fold running to completion under the single-threaded
    # event loop before another coroutine's fold starts. The only await in
    # score_attempt is the terminal event_bus.publish. Admission control and
    # the fail-open wrapper stay OUTSIDE this function, in routes_score.py.
    # ------------------------------------------------------------------
    merchant_id: str,
    ip: str,
    ua_class: str,
    body: ScoreRequest,
    evaluation,
    features,
    score_calibrated: float,
    prior_used: float,
    regime: str,
    ingest_ms: int,
) -> _Day6Outcome:
    live_snapshot = state.policy
    # Entity scope: the narrowest key that covers the evidence (Day-6 Plan
    # §3.5). CUSUM (store rate) and drift (per-IP fan-out) both point at the
    # source `ip`; a rules-only decision driven by R3 alone is issuer-wide.
    fired = set(evaluation.fired_names)
    scope = "bin" if fired == {"distinct_cards_per_bin_5m"} else "ip"
    entity = resolve_entity(
        scope=scope, ip=ip, ua_class=ua_class, card_hash=body.card_hash, bin=body.bin
    )

    # A pre-existing incident for this entity resolves against its pinned
    # policy version; a brand-new incident (opened by step() below) pins the
    # live version.
    existing = state.incidents.live_incident(merchant_id, entity)
    snapshot = live_snapshot
    if existing is not None:
        snapshot = _pinned_snapshot(state, merchant_id, existing.pinned_policy_version) or live_snapshot

    families = families_from_rules(evaluation.fired_names)
    signal, _cstep, _dstep = state.layer2.observe(
        merchant_id=merchant_id,
        entity=entity,
        ingest_ms=ingest_ms,
        bucket_index=features.cusum_bucket_index,
        p_calibrated=score_calibrated,
        distinct_cards_per_ip_30m=features.distinct_cards_per_ip_30m_raw,
        rule_families=families,
        card_hash=body.card_hash,
    )

    incident = state.incidents.step(
        merchant_id=merchant_id,
        entity=entity,
        ingest_ms=ingest_ms,
        signal=signal,
        cooldown_seconds=snapshot.cooldown_seconds,
        pinned_policy_version=snapshot.version,
    )
    incident_open = incident is not None and incident.is_live()
    corroborated = incident.corroborated() if incident is not None else False
    active_before = state.incidents.active_enforced_entities(merchant_id)

    outcome = state.policy_engine.resolve(
        merchant_id=merchant_id,
        p_calibrated=score_calibrated,
        evaluation=evaluation,
        entity=entity,
        snapshot=snapshot,
        incident_open=incident_open,
        corroborated=corroborated,
        active_enforced_count=active_before,
        bin_is_foreign_issued=features.values.get("bin_is_foreign_issued", 0.0),
        regime=regime,
        prior_used=prior_used,
    )

    incident_id = None
    sse_incident = None
    spool_extras: dict = {}
    if incident is not None:
        # Record the tier transition against the PINNED policy version
        # (Backend Schema §3.1). A CLOSED incident raises -- defensive only,
        # the machine already freed the slot.
        try:
            state.incidents.note_tier(
                incident, outcome.proposed_tier, ingest_ms,
                f"policy:{signal.detector}:{regime}", signal.signal_value,
            )
        except IllegalTransition:
            pass
        incident_id = incident.incident_id
        pseudonym = state.incidents.pseudonym(merchant_id, entity)

        # Source: Day-7 Plan §4 Step 6 -- at incident-open ONLY (narrative is
        # still None), build the narrator EvidenceBundle through the single
        # admission point, run the input-side charset gate on the assembled
        # prompt, then render the template narrative onto the incident row via
        # the existing spool -> drainer path. Deterministic and I/O-free -- not
        # an LLM call, no latency-budget impact (§12 trap 10). Gemini is Day 8.
        if incident.narrative is None:
            try:
                from packages.narrator.bundle import build_bundle
                from packages.narrator.prompt import assemble_prompt
                from packages.narrator.template import render as _render_narrative

                _bundle = build_bundle(
                    entity_type=entity.entity_type,
                    pseudonym=pseudonym,
                    decision=outcome.proposed_tier.value,
                    evaluation=evaluation,
                )
                assemble_prompt(_bundle)  # input-side gate; raises on hostile bytes
                incident.narrative = _render_narrative(_bundle)["narrative"]
                incident.narrative_source = "template"
            except Exception:  # noqa: BLE001 -- gate/vocab failure -> no narrative, never a 500
                pass

        enforcement_rows = []
        if not outcome.control_arm and not outcome.advisory_mode:
            proposed = outcome.proposed_tier
            # An enforcement_action row is written only for a tier that
            # carries friction -- throttle and up. `monitor` / `allow` are
            # not enforcement (Day-6 Plan §3.6 proposed-vs-in-force table).
            if _rank(proposed) >= _rank(Decision.THROTTLE):
                in_force = _rank(proposed) <= _rank(snapshot.auto_ceiling_tier)
                enforcement_rows.append({
                    "action_id": _action_id(
                        incident.incident_id, entity.entity_type, entity.entity_key, proposed.value
                    ),
                    "incident_id": incident.incident_id,
                    "merchant_id": merchant_id,
                    "entity_type": entity.entity_type,
                    "entity_key": entity.entity_key,
                    "tier": proposed.value,
                    "requires_confirmation": 0 if in_force else 1,
                    "confirmed_by": "auto" if in_force else None,
                    "applied_at": ingest_ms if in_force else None,
                    "expires_at": ingest_ms + state.enforcement_ttl_ms,
                    "released_at": None,
                    "applied_by": "auto",
                })

        spool_extras = {
            "incident": incident.to_row(),
            "incident_entity": [incident.entity_row(pseudonym)],
            "tier_transition": incident.transition_rows(),
        }
        if enforcement_rows:
            spool_extras["enforcement"] = enforcement_rows

        sse_incident = {
            "incident_id": incident.incident_id,
            "state": incident.state.value,
            "detector": incident.detector,
            "entity_type": entity.entity_type,
            "pseudonym": pseudonym,
            "proposed_tier": outcome.proposed_tier.value,
            "in_force_tier": outcome.in_force_tier.value,
        }

    active_after = state.incidents.active_enforced_entities(merchant_id)
    sse_enforcement = {
        "active": active_after,
        "k_max": snapshot.k_max_entities,
        "advisory_mode": outcome.advisory_mode,
    }
    threat_state = state.incidents.worst_threat_state(merchant_id)

    return _Day6Outcome(
        decision=outcome.in_force_tier,
        tier_ladder=outcome.tier_ladder,
        control_arm=outcome.control_arm,
        policy_version=snapshot.version,
        incident_id=incident_id,
        threat_state=threat_state,
        sse_incident=sse_incident,
        sse_enforcement=sse_enforcement,
        spool_extras=spool_extras,
    )


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

    # Source: Day-7 Plan §4 Step 2 -- stored-decision replay reply. An
    # idempotent replay (SET NX found the key) carries no new observation;
    # compute_features already returned zeros and left every window / the
    # CUSUM bucket untouched. When this request's decision is still cached
    # in-process, return the winner's (attempt_uid, decision) verbatim,
    # skipping the spool append and the SSE publish so no duplicate
    # auth_attempt / attempt_score row or attempt event is produced. A
    # cross-process or FIFO-evicted miss falls through to the pre-Day-7 path.
    if features.idempotent_replay:
        cached = state.decision_cache.get(features.idem_digest)
        if cached is not None:
            stored_uid, stored_decision_value = cached
            replay_response = ScoreResponse(
                attempt_uid=stored_uid,
                decision=Decision(stored_decision_value),
                latency_ms=active_stopwatch.elapsed_ms(),
            )
            return replay_response, {
                "replayed": True,
                "attempt_uid": stored_uid,
                "decision": stored_decision_value,
            }

    evaluation = state.rules.evaluate_from_features(features)

    layer2_live = (
        state.policy is not None
        and state.layer2 is not None
        and state.incidents is not None
        and state.policy_engine is not None
        # An idempotent replay (Threat Model §3 / M7) carries no new
        # observation -- compute_features already returned zeros and left
        # every window untouched; Layer 2 must not fold it into the CUSUM,
        # the drift SPRT or the incident machine either.
        and not features.idempotent_replay
    )

    # Day-6 Plan §3.10 -- resolve the alarm regime BEFORE the model, so the
    # prior that produces score_calibrated is a pure function of CUSUM
    # buckets that are already fully scored (no circularity with the
    # tau_flag gate).
    regime = "in_control"
    alarm_rate_ratio: Optional[float] = None
    if layer2_live:
        regime, alarm_rate_ratio = state.layer2.regime_for(merchant_id, features.cusum_bucket_index)

    # Source: Day-5 Plan Step 9 -- score yes, decide no. TRD §6.3's order is
    # features -> rules -> model -> calibration + prior correction -> policy,
    # and this runs INSIDE the latency_ms measurement stamped below. With no
    # model artifact loaded (state.model is None) the block is skipped and the
    # six score fields are exactly Day 4's -- the authorized rules-only fallback.
    if state.model is not None and state.calibrator is not None:
        from packages.detect.calibrate import serving_prior, sigmoid

        model_input = [features.values[name] for name in FEATURE_NAMES]
        margin, contribs = state.model.score_one(model_input)
        if regime == "alarm" and alarm_rate_ratio is not None:
            pi_s = serving_prior("alarm", state, rate_ratio=alarm_rate_ratio)
        else:
            pi_s = serving_prior("in_control", state)
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

    # Day-6 Plan §3.10 -- the one seam. layer2_live is False => skipped, and
    # every field below is exactly Day 5's.
    tier_ladder = "domestic"
    control_arm = False
    policy_version = state.policy_version
    incident_id = None
    day6: Optional[_Day6Outcome] = None
    if layer2_live:
        day6 = _resolve_layer2(
            state,
            merchant_id=merchant_id,
            ip=ip,
            ua_class=ua_class,
            body=body,
            evaluation=evaluation,
            features=features,
            score_calibrated=score_calibrated,
            prior_used=prior_used,
            regime=regime,
            ingest_ms=ingest_ms,
        )
        decision = day6.decision
        tier_ladder = day6.tier_ladder
        control_arm = day6.control_arm
        policy_version = day6.policy_version
        incident_id = day6.incident_id
    else:
        # Decision 57 / Decision 17: applying theta_T to the calibrated
        # posterior is Day 6; the R1-R3 tier floors hold unconditionally.
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
        regime=regime,
        decision=decision.value,
        tier_ladder=tier_ladder,
        control_arm=control_arm,
        shed=False,
        model_version=model_version,
        calibrator_version=calibrator_version,
        policy_version=policy_version,
        rules_fired=evaluation.fired_names,
        feature_snapshot=feature_snapshot,
        top_contributors=top_contributors,
        incident_id=incident_id,
        latency_ms=latency_ms,
        scored_at=ingest_ms,
    )

    # Source: Day-7 Plan §4 Step 2 -- remember the resolved decision before it
    # is spooled, so a later idempotent replay of this exact request returns
    # the same (attempt_uid, decision) without re-scoring or re-spooling.
    _remember_decision(state, features.idem_digest, attempt_uid, decision.value)

    spool_payload = {"attempt": attempt.to_dict(), "score": score_record.to_dict()}
    if day6 is not None and day6.spool_extras:
        spool_payload.update(day6.spool_extras)
    state.spool.append(attempt_uid, spool_payload)

    if day6 is not None:
        threat_state = day6.threat_state
    elif state.threat is not None:
        threat_state = state.threat.observe(
            rules_fired=evaluation.fired_names, decision=decision.value, ingest_ms=ingest_ms,
        )
    else:
        threat_state = None

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
    # Day-6 Plan §3.11 -- SSE gains `incident`, `enforcement`, `control_arm`;
    # only the incident_entity.pseudonym is published, never a raw key.
    event = {
        "attempt_uid": attempt_uid,
        "decision": decision.value,
        "ip": ip,
        "bin": body.bin,
        "ingest_time": ingest_ms,
        "rules_fired": evaluation.fired_names,
        "feature_snapshot": feature_snapshot,
        "threat_state": threat_state,
        "regime": regime,
        "replay": replay_snapshot,
        "incident": day6.sse_incident if day6 is not None else None,
        "enforcement": (
            day6.sse_enforcement if day6 is not None
            else {"active": 0, "k_max": 0, "advisory_mode": False}
        ),
        "control_arm": control_arm,
        # Source: Day-7 Plan §4 Step 4.5 -- additive; the dashboard ignores
        # unknown keys. `fail_open` is always False on the healthy path (a
        # fail-open never reaches here -- it is caught in routes_score.py);
        # `alert` reflects the merchant's rolling fail-open budget.
        "availability": {
            "fail_open": False,
            "alert": (
                state.availability.is_alerting(merchant_id, ingest_ms)
                if state.availability is not None else False
            ),
        },
    }
    await state.event_bus.publish(event)

    response = ScoreResponse(attempt_uid=attempt_uid, decision=decision, latency_ms=latency_ms)
    return response, event
