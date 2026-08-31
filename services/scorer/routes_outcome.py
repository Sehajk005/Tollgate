r"""
Source: Day-7 Plan §4 Step 5 -- POST /v1/outcome. Threat Model §4/P5: reject
unsigned, stale, tampered, and replayed gateway-outcome reports.

The exact contract (new -- none was specified anywhere before Day 7):

  Headers   X-Tollgate-Key, X-Tollgate-Signature, X-Tollgate-Timestamp
            (epoch ms), X-Tollgate-Nonce.
  Canonical json.dumps(body.model_dump(), sort_keys=True, separators=(",",":")).
  Signing   f"{merchant_id}\n{timestamp_ms}\n{nonce}\n{sha256(canonical)}"
  sig       hmac_sha256(secret, signing_string).hexdigest(), compared with
            hmac.compare_digest.

  Secret    TOLLGATE_OUTCOME_SECRET, BOUND to the merchant by asserting
            hash_api_key(secret) == merchant.outcome_hmac_key_hash. No secret
            at rest, no schema change -- exactly how api_key_hash already works.

  Failures  missing header      -> 401
            bad / stale (|now-ts| > 300_000 ms) signature timestamp -> 401
            key not bound / bad signature -> 401
            unknown event_id    -> 404
            replayed nonce      -> 409 (outcome_nonce PK IntegrityError)
            secret unset        -> 503 (route disabled; logged once)

The response body is a bare {"status": ...} -- no detail is echoed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from packages.contracts.wire import OutcomeRequest, OutcomeResponse
from packages.storage.repository import insert_auth_outcome, insert_outcome_nonce
from services.scorer.auth import hash_api_key
from services.scorer.deps import ScorerState, get_scorer_state

logger = logging.getLogger("tollgate.scorer.outcome")

router = APIRouter()

STALENESS_MS = 300_000  # 5 virtual minutes
_MISCONFIG_LOGGED = {"done": False}


def _canonical(body: OutcomeRequest) -> str:
    return json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))


@router.post("/v1/outcome", response_model=OutcomeResponse)
async def outcome(
    body: OutcomeRequest,
    response: Response,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    x_tollgate_signature: Optional[str] = Header(default=None, alias="X-Tollgate-Signature"),
    x_tollgate_timestamp: Optional[str] = Header(default=None, alias="X-Tollgate-Timestamp"),
    x_tollgate_nonce: Optional[str] = Header(default=None, alias="X-Tollgate-Nonce"),
    state: ScorerState = Depends(get_scorer_state),
) -> OutcomeResponse:
    secret = os.environ.get("TOLLGATE_OUTCOME_SECRET")
    if not secret:
        if not _MISCONFIG_LOGGED["done"]:
            logger.error("TOLLGATE_OUTCOME_SECRET is unset; POST /v1/outcome is disabled (503)")
            _MISCONFIG_LOGGED["done"] = True
        raise HTTPException(status_code=503, detail="outcome verification not configured")

    if not (x_tollgate_key and x_tollgate_signature and x_tollgate_timestamp and x_tollgate_nonce):
        raise HTTPException(status_code=401, detail="unsigned")

    try:
        ts_ms = int(x_tollgate_timestamp)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="unsigned")

    now_ms = state.clock.now_ms()
    if abs(now_ms - ts_ms) > STALENESS_MS:
        raise HTTPException(status_code=401, detail="stale")

    conn = state.db_read_conn()
    try:
        merchant_row = conn.execute(
            "SELECT merchant_id, outcome_hmac_key_hash FROM merchant WHERE api_key_hash = ?",
            (hash_api_key(x_tollgate_key),),
        ).fetchone()
        if merchant_row is None:
            raise HTTPException(status_code=401, detail="unknown key")
        merchant_id = merchant_row["merchant_id"]

        # Bind the process-wide secret to THIS merchant (no secret at rest).
        if not hmac.compare_digest(hash_api_key(secret), merchant_row["outcome_hmac_key_hash"] or ""):
            raise HTTPException(status_code=401, detail="secret not bound to merchant")

        body_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        signing_string = f"{merchant_id}\n{ts_ms}\n{x_tollgate_nonce}\n{body_hash}"
        expected = hmac.new(
            secret.encode("utf-8"), signing_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_tollgate_signature):
            raise HTTPException(status_code=401, detail="bad signature")

        attempt_row = conn.execute(
            "SELECT attempt_uid FROM auth_attempt WHERE merchant_id = ? AND event_id = ?",
            (merchant_id, body.event_id),
        ).fetchone()
        if attempt_row is None:
            raise HTTPException(status_code=404, detail="unknown event_id")
        attempt_uid = attempt_row["attempt_uid"]

        try:
            insert_outcome_nonce(conn, x_tollgate_nonce, now_ms)
        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(status_code=409, detail="replayed nonce")

        insert_auth_outcome(conn, {
            "attempt_uid": attempt_uid,
            "gateway_status": body.gateway_status,
            "decline_code": body.decline_code,
            "gateway_latency_ms": body.gateway_latency_ms,
            "auth_fee_minor": body.auth_fee_minor,
            "reached_gateway": body.reached_gateway,
            "sig_verified": True,
            "ingest_time": now_ms,
        })
        conn.commit()
    finally:
        conn.close()

    return OutcomeResponse(status="recorded")
