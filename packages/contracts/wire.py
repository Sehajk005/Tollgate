"""
Source: Implementation Plan v2.1 Day 1 -- ScoreRequest/ScoreResponse. Strict
enough to reject invalid values and missing required fields.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.decision import Decision


class ScoreRequest(BaseModel):
    """
    Wire contract for POST /v1/score.

    Source: Threat Model v2 §2 -- `ip` is never accepted from the request
    body; it is resolved server-side from the TCP peer / a validated
    X-Forwarded-For hop (services/scorer/net.py). This model declares no `ip`
    field, and extra="ignore" means a client-supplied `ip` (or any other
    unrecognized field) is silently dropped rather than consulted or causing
    a validation error.
    """

    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(min_length=1)
    card_hash: str = Field(min_length=1)
    bin: str = Field(min_length=1)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=1)

    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    session_id: Optional[str] = None


class ScoreResponse(BaseModel):
    """
    Source: v2.1 reconciliation, decision 18 (N2) -- the wire carries
    `decision` only. ClientOutcome (including shed/fail_open, neither of
    which can be a body field) is derived client-side by
    packages.contracts.decision.resolve_client_outcome(). No rule names, no
    raw score: Threat Model A2 grants the attacker the design; echoing which
    rule fired would additionally hand an efficient threshold-search oracle.
    """

    model_config = ConfigDict(extra="forbid")

    attempt_uid: str
    decision: Decision
    latency_ms: int
