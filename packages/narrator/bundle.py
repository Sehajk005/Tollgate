"""
Source: Threat Model v2 §5 (S1 -- indirect prompt injection into the
narrator) -- "the prompt contains no attacker-reachable bytes." Every field
here is an int, a float, or drawn from a fixed closed-vocabulary enum
defined in code; no free text, no raw user_agent, no raw IP/BIN/card hash.
Entities are pseudonymised (`ip_1`, `bin_A`) -- the real value never
crosses into this dataclass. Day-3 Plan Step 8.

Incidents (packages/detect, `incident_entity.pseudonym`) do not exist until
Day 6, so the Day-3 bundle is built at decision time, straight from a
rules evaluation and the feature vector that produced it. The shape is
deliberately the same one Day 6's incident-level narrator call will use
with more slots filled -- not a different type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# Source: Threat Model §5/1 -- "feature names (enum of ~16)". Extended here
# to the Day-3 rule names actually in RulesEvaluation.feature_snapshot
# (packages/detect/rules.py); still a closed, code-defined vocabulary.
RULE_NAME_VOCAB = (
    "attempts_per_ip_60s",
    "distinct_cards_per_ip_5m",
    "distinct_cards_per_bin_5m",
)

# Source: Threat Model §5/1 -- "entity types (enum of 5)"; TRD §6.1's spaces.
ENTITY_TYPE_VOCAB = ("ip", "ipua", "card", "bin", "session")

# Source: TRD §6.11 -- tier names (enum of 6), packages.contracts.decision.Decision.
TIER_VOCAB = ("allow", "monitor", "throttle", "challenge", "step_up", "block")


@dataclass(frozen=True)
class EvidenceBundle:
    entity_type: str  # one of ENTITY_TYPE_VOCAB
    pseudonym: str  # e.g. "ip_1", "bin_A" -- never the real identifier
    decision: str  # one of TIER_VOCAB
    rules_fired: Tuple[str, ...]  # subset of RULE_NAME_VOCAB
    primary_rule: str  # the single rule driving the narrative; in RULE_NAME_VOCAB
    primary_value: float
    primary_threshold: float

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPE_VOCAB:
            raise ValueError(f"entity_type {self.entity_type!r} outside closed vocabulary")
        if self.decision not in TIER_VOCAB:
            raise ValueError(f"decision {self.decision!r} outside closed vocabulary")
        for name in self.rules_fired:
            if name not in RULE_NAME_VOCAB:
                raise ValueError(f"rule name {name!r} outside closed vocabulary")
        if self.primary_rule not in RULE_NAME_VOCAB:
            raise ValueError(f"primary_rule {self.primary_rule!r} outside closed vocabulary")
