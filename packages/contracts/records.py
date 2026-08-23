"""
Source: Implementation Plan v2.1 Day 1 -- AttemptRecord/ScoreRecord
persistence DTOs, mapping to the Day-1-relevant columns of auth_attempt and
attempt_score (schema.sql).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Optional

from packages.contracts.wire import ScoreRequest


@dataclass
class AttemptRecord:
    attempt_uid: str
    merchant_id: str
    event_id: str
    payload_digest: str
    ingest_time: int
    client_ts: Optional[int]
    session_id: Optional[str]
    card_hash: str
    bin: str
    last4: Optional[str]
    exp_month: Optional[int]
    exp_year: Optional[int]
    amount_minor: int
    currency: str
    ip: str
    asn: Optional[int]
    ua_class: Optional[str]
    ipua_key: Optional[str]
    client_evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreRecord:
    attempt_uid: str
    score_raw: float
    score_calibrated: float
    prior_used: float
    regime: str
    decision: str
    tier_ladder: str
    control_arm: bool
    shed: bool
    model_version: str
    calibrator_version: str
    policy_version: int
    rules_fired: list
    feature_snapshot: dict
    top_contributors: Optional[str]
    incident_id: Optional[str]
    latency_ms: int
    scored_at: int

    def to_dict(self) -> dict:
        return asdict(self)


def compute_payload_digest(body: ScoreRequest) -> str:
    """
    Source: Threat Model v2 §3 -- the idempotency key covers every M-class
    field. Day 1 computes and stores this digest but does not yet enforce the
    SET NX idempotency guard itself (Threat Model §3 steps 3-4 are Day 7).
    """
    canonical = json.dumps(
        {
            "card_hash": body.card_hash,
            "bin": body.bin,
            "last4": body.last4,
            "exp_month": body.exp_month,
            "exp_year": body.exp_year,
            "amount_minor": body.amount_minor,
            "currency": body.currency,
            "session_id": body.session_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
