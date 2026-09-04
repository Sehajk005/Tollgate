"""
Source: Day-8 Plan Step 6 -- the D3 backend. The only genuinely new backend
surface in Day 8. Everything it exposes already exists in SQLite; nothing
recomputes.

  GET  /v1/incidents?state=live       -- newest incident ids for the merchant;
                                        state in {live (default, non-CLOSED),
                                        closed, all} -- any other value -> 422
  GET  /v1/incidents/{id}             -- the full D3 read model (pseudonyms +
                                        truncated real keys; never a PAN, never
                                        a full card hash -- UIUX v2 §6.8)
  POST /v1/incidents/{id}/confirm     -- {action_id, tier}: confirm a PROPOSED
                                        step_up/block. Flips requires_confirmation
                                        -> 0, sets confirmed_by="operator",
                                        applied_at=now, and raises the entity's
                                        PolicyEngine ceiling. Rejects a tier not
                                        present as a proposed row (409).
  POST /v1/incidents/{id}/resolve     -- {resolution}: close the incident, release
                                        every enforcement row, clear the entity's
                                        confirmed ceiling (App Flow J4).

Auth: `X-Tollgate-Key` via `resolve_merchant_id_cached` (exactly as /v1/score).
Merchant isolation: an incident that is not the caller's returns 404. Reads use
a read-only connection; the two writes are direct (off the scoring hot path --
a synchronous operator action must be visible on the next read, not 50 ms
later). Confirmation affects SUBSEQUENT attempts only; already-scored attempts
are never retroactively changed.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from packages.contracts.decision import Decision
from packages.detect.policy import EntityKey
from packages.storage.db import connect
from packages.storage.repository import (
    confirm_enforcement_action,
    read_incident_detail,
    read_open_incidents,
    release_enforcement_for_incident,
    resolve_incident,
)
from services.scorer.auth import AuthBackendUnavailable, resolve_merchant_id_cached
from services.scorer.deps import ScorerState, get_scorer_state

router = APIRouter()

_PROPOSED_TIERS = {"step_up", "block"}
_RESOLUTIONS = {"false_positive", "true_positive"}


class ConfirmBody(BaseModel):
    action_id: str
    tier: str


class ResolveBody(BaseModel):
    resolution: str


def _auth(state: ScorerState, key: Optional[str]) -> str:
    try:
        merchant_id = resolve_merchant_id_cached(state, key)
    except AuthBackendUnavailable:
        raise HTTPException(status_code=503, detail="auth backend unavailable")
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return merchant_id


@router.get("/v1/incidents")
async def list_incidents(
    state: Literal["live", "closed", "all"] = "live",
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    scorer: ScorerState = Depends(get_scorer_state),
) -> dict:
    # DEF-D9-006: `state` used to be an unvalidated str that was never forwarded
    # -- ?state=closed and ?state=bogus returned the identical live list. It is
    # now a closed set (422 otherwise) and read_open_incidents applies it.
    merchant_id = _auth(scorer, x_tollgate_key)
    conn = connect(scorer.db_path, read_only=True)
    try:
        rows = read_open_incidents(conn, merchant_id, state=state)
    finally:
        conn.close()
    return {"incidents": rows}


@router.get("/v1/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    scorer: ScorerState = Depends(get_scorer_state),
) -> dict:
    merchant_id = _auth(scorer, x_tollgate_key)
    conn = connect(scorer.db_path, read_only=True)
    try:
        detail = read_incident_detail(conn, incident_id, merchant_id=merchant_id)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown incident")
    return detail


@router.post("/v1/incidents/{incident_id}/confirm")
async def confirm_incident(
    incident_id: str,
    body: ConfirmBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    scorer: ScorerState = Depends(get_scorer_state),
) -> dict:
    merchant_id = _auth(scorer, x_tollgate_key)
    now_ms = scorer.clock.now_ms()

    conn = connect(scorer.db_path)
    try:
        # merchant isolation + existence
        if read_incident_detail(conn, incident_id, merchant_id=merchant_id) is None:
            raise HTTPException(status_code=404, detail="unknown incident")

        row = conn.execute(
            "SELECT action_id, entity_type, entity_key, tier, requires_confirmation "
            "FROM enforcement_action WHERE action_id = ? AND incident_id = ?",
            (body.action_id, incident_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown action_id for this incident")
        # the operator confirms a PROPOSAL, never invents one
        if row["tier"] != body.tier or body.tier not in _PROPOSED_TIERS:
            raise HTTPException(status_code=409, detail="tier is not a proposed enforcement for this incident")
        if row["requires_confirmation"] != 1:
            raise HTTPException(status_code=409, detail="enforcement action is not awaiting confirmation")

        entity_type, entity_key = row["entity_type"], row["entity_key"]
        confirm_enforcement_action(conn, body.action_id, "operator", now_ms)
    finally:
        conn.close()

    # raise the entity's ceiling in the LIVE policy engine -- subsequent
    # attempts from this entity now resolve at the confirmed tier.
    if scorer.policy_engine is not None:
        scorer.policy_engine.set_confirmed_ceiling(
            EntityKey(entity_type, entity_key), Decision(body.tier)
        )

    return {"status": "confirmed", "action_id": body.action_id, "tier": body.tier, "applied_at": now_ms}


@router.post("/v1/incidents/{incident_id}/resolve")
async def resolve_incident_route(
    incident_id: str,
    body: ResolveBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    scorer: ScorerState = Depends(get_scorer_state),
) -> dict:
    merchant_id = _auth(scorer, x_tollgate_key)
    if body.resolution not in _RESOLUTIONS:
        raise HTTPException(status_code=422, detail="resolution must be false_positive or true_positive")
    now_ms = scorer.clock.now_ms()

    conn = connect(scorer.db_path)
    try:
        if read_incident_detail(conn, incident_id, merchant_id=merchant_id) is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        entities = [
            (r["entity_type"], r["entity_key"])
            for r in conn.execute(
                "SELECT entity_type, entity_key FROM incident_entity WHERE incident_id = ?",
                (incident_id,),
            ).fetchall()
        ]
        release_enforcement_for_incident(conn, incident_id, now_ms)
        resolve_incident(conn, incident_id, body.resolution, "operator", now_ms)
    finally:
        conn.close()

    # drop every confirmed ceiling for this incident's entities -- they return
    # to the `challenge` auto-ceiling on their next attempt.
    if scorer.policy_engine is not None:
        for entity_type, entity_key in entities:
            scorer.policy_engine.clear_confirmed_ceiling(EntityKey(entity_type, entity_key))

    return {"status": "resolved", "resolution": body.resolution, "closed_at": now_ms}
