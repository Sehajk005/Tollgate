"""
Source: Day-2 Plan §F identity.py -- "opaque card_hash + fictional BIN
allocation". BINs are fictional (PRD v2 §9 / Schema v2 §3.2): a reserved
prefix ("999") disjoint from every real IIN range (which start 1-8), so
nothing here can collide with or resemble a real card BIN.
"""

from __future__ import annotations

from packages.simulator.rng import SubStream

FICTIONAL_BIN_PREFIX = "999"
FICTIONAL_BIN_POOL = [f"{FICTIONAL_BIN_PREFIX}{n:03d}" for n in range(200)]  # 999000..999199

# Source: Day-4 Plan (rev. 2) Step 3 -- the `nri_traffic` negative control
# needs a BIN pool that is "foreign-issued" by construction, disjoint from
# FICTIONAL_BIN_POOL (999000-999199) so a length change to that pool never
# shifts this one's draws or vice versa. Same reasoned prefix (F18): still
# 6 digits, still starts with FICTIONAL_BIN_PREFIX, still outside every
# real MII range (1-8).
FOREIGN_BIN_POOL = [f"{FICTIONAL_BIN_PREFIX}{n:03d}" for n in range(800, 900)]  # 999800..999899


def opaque_card_hash(substream: SubStream) -> str:
    """
    A 40-hex-char opaque token, identical format regardless of whether the
    caller is the baseline or attack model (Day-2 Plan §F anti-leakage
    checklist: "all card_hash from one opaque generator, identical
    format") -- carries no origin marker, no embedded index or sequence.
    """
    token = substream.getrandbits(160)
    return f"{token:040x}"


def pick_bin(substream: SubStream, pool: list) -> str:
    return pool[substream.below(len(pool))]
