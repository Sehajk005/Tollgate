"""
Source: Day-2 Plan §F stream.py -- "merge, canonical serialization, episode
records". Event record shape and field derivation are Day-2 Plan §F's own
table; canonical serialization is Decision 30: json.dumps(sort_keys=True,
separators=(",",":"), ensure_ascii=True) + "\n", files opened newline="\n".

Identifiers (event_id, seq) are assigned strictly sequentially across the
MERGED stream (Day-2 Plan §F anti-leakage checklist: "no tier or is_attack
marker in any identifier") -- never from a per-source-model counter, which
would otherwise let event_id's numeric range alone reveal origin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional


def canonical_line(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_jsonl(path, lines: list) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line)


@dataclass(frozen=True)
class RawItem:
    """Pre-merge, pre-numbered event content, produced by baseline.py / attack.py."""

    t_ms: int
    ip: str
    card_hash: str
    bin: str
    amount_minor: int
    currency: str
    session_id: str
    is_attack: bool
    episode_id: Optional[str]
    gateway_status: str
    decline_code: Optional[str]


@dataclass(frozen=True)
class Event:
    event_id: str
    seq: int
    t_ms: int
    ip: str
    card_hash: str
    bin: str
    amount_minor: int
    currency: str
    session_id: str

    def to_dict(self) -> dict:
        return {
            "amount_minor": self.amount_minor, "bin": self.bin, "card_hash": self.card_hash,
            "currency": self.currency, "event_id": self.event_id, "ip": self.ip,
            "seq": self.seq, "session_id": self.session_id, "t_ms": self.t_ms,
        }

    def to_score_request(self) -> dict:
        """
        Source: Day-2 Plan §F field-derivation table -- "exactly the wire
        fields the simulator may set" (packages/contracts/wire.py). `ip`
        and `t_ms` are carried out-of-band by the replay driver, never
        through the request body (Threat Model v2 §2 / finding K8).
        """
        return {
            "event_id": self.event_id, "card_hash": self.card_hash, "bin": self.bin,
            "amount_minor": self.amount_minor, "currency": self.currency,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class Label:
    event_id: str
    seq: int
    is_attack: bool
    episode_id: Optional[str]
    gateway_status: str
    decline_code: Optional[str]

    def to_dict(self) -> dict:
        return {
            "decline_code": self.decline_code, "episode_id": self.episode_id,
            "event_id": self.event_id, "gateway_status": self.gateway_status,
            "is_attack": self.is_attack, "seq": self.seq,
        }


@dataclass(frozen=True)
class Episode:
    episode_id: str
    kind: str
    tier: Optional[str]
    scenario: Optional[str]
    started_at: int
    ended_at: int
    attempt_count: int
    distinct_cards: int
    generator_seed: int
    evasion_params: Optional[dict]

    def to_dict(self) -> dict:
        return {
            "attempt_count": self.attempt_count, "distinct_cards": self.distinct_cards,
            "ended_at": self.ended_at, "episode_id": self.episode_id,
            "evasion_params": self.evasion_params, "generator_seed": self.generator_seed,
            "kind": self.kind, "scenario": self.scenario, "started_at": self.started_at,
            "tier": self.tier,
        }


@dataclass
class SimulatorOutput:
    events: list
    labels: list
    episodes: list


def merge_and_number(baseline_items: list, attack_items: list) -> tuple:
    """
    Merges baseline and attack RawItems by t_ms (stable sort: input order
    -- always baseline-then-attack -- breaks ties deterministically across
    environments) and assigns event_id/seq from the merged position.
    Returns (events: list[Event], labels: list[Label]).
    """
    combined = list(baseline_items) + list(attack_items)
    combined.sort(key=lambda item: item.t_ms)

    events = []
    labels = []
    for seq, item in enumerate(combined):
        event_id = f"e-{seq:07d}"
        events.append(Event(
            event_id=event_id, seq=seq, t_ms=item.t_ms, ip=item.ip, card_hash=item.card_hash,
            bin=item.bin, amount_minor=item.amount_minor, currency=item.currency,
            session_id=item.session_id,
        ))
        labels.append(Label(
            event_id=event_id, seq=seq, is_attack=item.is_attack, episode_id=item.episode_id,
            gateway_status=item.gateway_status, decline_code=item.decline_code,
        ))
    return events, labels
