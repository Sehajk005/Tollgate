"""
Source: TRD v2 §5.2 -- Decision (6) and ClientOutcome (8) in one module.

v2.1 reconciliation (decision 18 / finding N2): the wire carries `decision`
only. `ClientOutcome` -- including `shed` (header-signalled) and `fail_open`
(never on the wire; the absence of a decision) -- is derived client-side by
resolve_client_outcome(), the sole authority for App Flow v2 §4's 8-row table.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Mapping, Optional


class Decision(StrEnum):
    ALLOW = "allow"
    MONITOR = "monitor"
    THROTTLE = "throttle"
    CHALLENGE = "challenge"
    STEP_UP = "step_up"
    BLOCK = "block"


class ClientOutcome(StrEnum):
    ALLOW = "allow"
    MONITOR = "monitor"
    THROTTLE = "throttle"
    CHALLENGE = "challenge"
    STEP_UP = "step_up"
    BLOCK = "block"
    SHED = "shed"
    FAIL_OPEN = "fail_open"


# Source: App Flow v2 §4 -- Decision -> screen mapping. Day 1 has no operator
# confirmation UI (D3 arrives Day 8) so step_up/block route to the same
# screen ids the spec assigns them; only allow/monitor/throttle/challenge/
# shed/fail_open are reachable in the Day 1 build.
UI_ROUTING_TABLE: Mapping[ClientOutcome, str] = {
    ClientOutcome.ALLOW: "S5",
    ClientOutcome.MONITOR: "S5",
    ClientOutcome.THROTTLE: "S7",
    ClientOutcome.CHALLENGE: "S3",
    ClientOutcome.STEP_UP: "S4",
    ClientOutcome.BLOCK: "S6",
    ClientOutcome.SHED: "S5",
    ClientOutcome.FAIL_OPEN: "S5",
}


def resolve_client_outcome(
    *,
    status_code: Optional[int],
    headers: Mapping[str, str],
    body: Optional[Mapping[str, object]],
    error: Optional[BaseException],
) -> ClientOutcome:
    """
    The sole authority mapping a /v1/score wire response to a ClientOutcome.

    `fail_open` is never on the wire (TRD §5.2) -- it is the absence of a
    decision, signalled by a timeout, connection error, or 5xx. `shed` is
    signalled by the `X-Tollgate-Shed` response header, not a body field.
    """
    if error is not None or status_code is None or status_code >= 500:
        return ClientOutcome.FAIL_OPEN
    if headers.get("X-Tollgate-Shed") == "1":
        return ClientOutcome.SHED
    if body is None or "decision" not in body:
        return ClientOutcome.FAIL_OPEN
    return ClientOutcome(body["decision"])
