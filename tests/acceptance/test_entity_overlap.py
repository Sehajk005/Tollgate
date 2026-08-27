"""
Source: Day-4 Plan (rev. 2) §6 test 16 -- "Entity-key selectivity is
measured." On an attack-free control run, false-linkage rate: `bin`
EXCEEDS the bound (so it is excluded), `ip` and `card_hash` fall under it.
Overlap window extends ended_at + 30 min (F10). This is the "measured, not
asserted" property that justifies eval/dataset.py's compute_entity_overlap
excluding BIN as an entity key.

Population: ordinary (non-attack, non-negative-control) baseline traffic
at a large-enough scale (300 simulated hours) that pool-size structure
dominates over small-sample noise -- `card_hash` is a 160-bit opaque token
(unbounded cardinality by construction) while `bin` is drawn from the
fixed, locked-size 200-entry FICTIONAL_BIN_POOL (Decision: pool length is
untouched -- shifts every downstream draw and breaks golden.jsonl's SHA).
`ip` sits in between at this scale: this simulator's baseline IPs are
themselves drawn from an RFC 5737 /24 test range (254 addresses), a Day-2
locked generator detail, so ip's measured rate is not as low as a real
deployment's would be -- but it is still measurably, reproducibly lower
than bin's at this population size, which is the property this test
exists to measure rather than assert.
"""

from __future__ import annotations

from packages.simulator.baseline import generate_baseline_events
from packages.simulator.profile import load_baseline_profile, load_store_profile

FALSE_LINKAGE_BOUND = 0.0045
HOURS = 300


def _false_linkage_rate(values: list) -> float:
    """
    Source: Day-4 Plan §6 test 16 -- for a candidate key type, the expected
    fraction of the population any given member shares its key value with
    (excluding itself): a direct, independent measurement of key
    cardinality/popularity, computed separately from eval/dataset.py's
    actual compute_entity_overlap() implementation so this is a genuine
    measurement, not a restatement of the code under test.
    """
    n = len(values)
    if n <= 1:
        return 0.0
    counts: dict = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    total_shared_pairs = sum(c * (c - 1) for c in counts.values())
    total_possible_pairs = n * (n - 1)
    return total_shared_pairs / total_possible_pairs


class TestEntityKeySelectivityIsMeasured:
    def test_bin_exceeds_bound_ip_and_card_fall_under_it(self):
        store_profile = load_store_profile()
        baseline_profile = load_baseline_profile()
        items = generate_baseline_events(
            seed=42, hours=HOURS, store_profile=store_profile, baseline_profile=baseline_profile,
        )
        assert items, "baseline control run produced no events"

        bins = [i.bin for i in items]
        ips = [i.ip for i in items]
        cards = [i.card_hash for i in items]

        bin_rate = _false_linkage_rate(bins)
        ip_rate = _false_linkage_rate(ips)
        card_rate = _false_linkage_rate(cards)

        assert bin_rate > FALSE_LINKAGE_BOUND, f"bin false-linkage rate {bin_rate!r} did not exceed the bound"
        assert ip_rate <= FALSE_LINKAGE_BOUND, f"ip false-linkage rate {ip_rate!r} exceeded the bound"
        assert card_rate <= FALSE_LINKAGE_BOUND, f"card_hash false-linkage rate {card_rate!r} exceeded the bound"
        assert bin_rate > ip_rate > card_rate, (
            f"expected bin({bin_rate}) > ip({ip_rate}) > card_hash({card_rate})"
        )

    def test_false_linkage_helper_detects_a_planted_high_collision_key(self):
        # Proves the statistic isn't vacuously passing: a key with only 2
        # distinct values across 100 samples must show near-total linkage.
        planted = (["A"] * 50) + (["B"] * 50)
        assert _false_linkage_rate(planted) > 0.4
        distinct = [str(i) for i in range(100)]
        assert _false_linkage_rate(distinct) == 0.0
