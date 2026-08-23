"""
Source: Threat Model v2 §4/P1 -- the automatic enforcement ceiling is
`challenge`. `block` and `step_up` are never applied automatically. R1-R3
never floor above `challenge` (decisions.md, decision 1), so this clamp is a
no-op for the Day 1 rules layer today, but it is the explicit, tested
mechanism that keeps it that way as later layers (Day 6 policy engine) are
added.
"""

from __future__ import annotations

from packages.contracts.decision import Decision

AUTO_CEILING = Decision.CHALLENGE

_ORDER = [
    Decision.ALLOW,
    Decision.MONITOR,
    Decision.THROTTLE,
    Decision.CHALLENGE,
    Decision.STEP_UP,
    Decision.BLOCK,
]


def apply_auto_ceiling(tier: Decision, ceiling: Decision = AUTO_CEILING) -> Decision:
    if _ORDER.index(tier) > _ORDER.index(ceiling):
        return ceiling
    return tier
