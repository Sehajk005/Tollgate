"""
Source: Day-4 Plan (rev. 2) §6 test 23 -- "NRI tripwire." `nri_traffic` is
inert on Day 4 (F11): foreign BINs appear only in the negative control,
negative controls never train, and `attack.py` emits none, so
`bin_is_foreign_issued` has zero variance in the measured (attack-tier)
population today. This test fails the moment that stops being true --
`bin_is_foreign_issued` going live while attack-side foreign share is
still zero -- so the deferral cannot be silently forgotten.
"""

from __future__ import annotations

from packages.features.compute import FEATURE_NAMES, FeatureContext, classify_ua, compute_features
from packages.features.memory_store import InMemoryWindowStore
from packages.simulator.generate import build_stream


class TestNriControlTripwire:
    def test_bin_is_foreign_issued_is_in_the_feature_set(self):
        assert "bin_is_foreign_issued" in FEATURE_NAMES

    def test_attack_side_foreign_share_is_still_zero_so_the_control_stays_inert(self):
        """
        Source: Day-4 Plan Step 3 -- the tripwire itself. If a future change
        makes `attack.py` draw BINs with non-zero foreign share (or
        `compute_features` starts reading real bin_metadata), this test
        must start failing -- that is its entire purpose. Today, every
        attack-tier event's computed `bin_is_foreign_issued` is 0.0.
        """
        store = InMemoryWindowStore()
        observed_nonzero = False
        for tier in ("easy", "medium", "hard"):
            result = build_stream(seed=42, tier=tier, hours=1)
            for event in result.events:
                ctx = FeatureContext(
                    merchant_id="m-tripwire",
                    attempt_uid=f"a-{event.event_id}",
                    ingest_ms=event.t_ms,
                    payload_digest=f"pd-{event.event_id}",
                    event_id=event.event_id,
                    ip=event.ip,
                    ua_class=classify_ua("Mozilla/5.0"),
                    card_hash=event.card_hash,
                    bin=event.bin,
                    amount_minor=event.amount_minor,
                    session_id=event.session_id,
                )
                features = compute_features(store, ctx)
                if features.values["bin_is_foreign_issued"] != 0.0:
                    observed_nonzero = True
                    break
            if observed_nonzero:
                break

        assert not observed_nonzero, (
            "bin_is_foreign_issued is non-zero on attack-tier traffic -- the nri_traffic "
            "negative control is no longer inert (F11) and its report marker/deferral note "
            "must be revisited, not silently left as 'inert -- becomes live on Day 5'"
        )
