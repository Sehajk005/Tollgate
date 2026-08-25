r"""
Source: TRD v2 §6.11 -- narrator contract. "Template first. packages/
narrator/template.py ships Day 3 and renders from the identical bundle.
Gemini is a drop-in on Day 8 behind NARRATOR_BACKEND." Output is
`{"narrative": str, "confidence_note": str}`, schema-validated by shape,
600-char cap, rendered as plain text. `recommended_action` is deleted from
the schema entirely -- the action bar's tier comes from the policy engine
only (§6.11); this module never produces one.

Threat Model §5/5 -- the charset gate `^[A-Za-z0-9 ,.:%₹()\[\]{}"\n_-]+$`
is asserted against the rendered output before it would ever be dispatched
to an LLM backend (Day 8). Applying it here too, on the template backend,
means both backends share one gate and one failure mode from the start.
Note the gate has no apostrophe/single-quote in its class, so the
narrative text below is built without one.
"""

from __future__ import annotations

import os
import re
from typing import Dict

from packages.narrator.bundle import EvidenceBundle

MAX_NARRATIVE_CHARS = 600

# Source: Threat Model v2 §5/5 -- exact charset assertion.
CHARSET_RE = re.compile(r'^[A-Za-z0-9 ,.:%₹()\[\]{}"\n_-]+$')

_RULE_LABELS = {
    "attempts_per_ip_60s": "attempt volume from one IP within 60 seconds",
    "distinct_cards_per_ip_5m": "distinct cards attempted from one IP within 5 minutes",
    "distinct_cards_per_bin_5m": "distinct cards attempted against one BIN within 5 minutes",
}


def render(bundle: EvidenceBundle) -> Dict[str, str]:
    """
    Source: TRD §6.11 -- template backend. Deterministic, no external call,
    no attacker-reachable bytes (Threat Model §5): every value read here
    comes from EvidenceBundle's closed-vocabulary fields, never from a raw
    identifier or user_agent.
    """
    label = _RULE_LABELS.get(bundle.primary_rule, bundle.primary_rule)
    narrative = (
        f"Entity {bundle.pseudonym} ({bundle.entity_type}) was assigned tier "
        f"\"{bundle.decision}\". Triggering signal: {label}, value {bundle.primary_value:g} "
        f"against threshold {bundle.primary_threshold:g}. "
        f"Rules fired: {', '.join(bundle.rules_fired) if bundle.rules_fired else 'none'}."
    )
    narrative = narrative[:MAX_NARRATIVE_CHARS]

    confidence_note = (
        "Rules-based detection (Day 1-3 scope): no ML calibration or learned "
        "baseline is active yet, so this reflects fixed thresholds only."
    )

    if not CHARSET_RE.match(narrative):
        # Source: Threat Model §5/5 -- "Anything else raises and falls back
        # to the template narrative." The template backend IS the fallback,
        # so a charset failure here falls back to a fixed, static sentence
        # rather than raising to the caller.
        narrative = (
            f"Entity {bundle.pseudonym} was assigned tier \"{bundle.decision}\". "
            f"Evidence unavailable in renderable form."
        )

    return {"narrative": narrative, "confidence_note": confidence_note}


def render_for_backend(bundle: EvidenceBundle) -> Dict[str, str]:
    """
    Source: TRD §6.11 -- NARRATOR_BACKEND selects the backend; "template" is
    the only implemented value on Day 3. Day 8 adds "gemini" as a drop-in
    behind this same dispatcher.
    """
    backend = os.environ.get("NARRATOR_BACKEND", "template")
    if backend != "template":
        raise NotImplementedError(
            f"NARRATOR_BACKEND={backend!r} is not implemented before Day 8; use 'template'"
        )
    return render(bundle)
