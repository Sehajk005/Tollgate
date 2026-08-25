"""
Source: Threat Model v2 §2 -- trust boundary partition (rule TB-1: "Only S
and M fields may produce model features or enforcement keys. C-class
fields are logged, displayed as evidence... and are invisible to the
model."). §2's own footer: "Test: tests/acceptance/test_trust_boundary.py
asserts the trained model's feature list intersected with the C-class
field set is empty. This test is the mechanism; the table above is only
documentation." Day-3 Plan Step 5 test list, item 9.

C_CLASS_FIELDS is transcribed directly from the Threat Model §2 table's
"C" rows: event_id, ts, user_agent, device_id, fingerprint_hash,
checkout_path, time_on_site_ms, is_guest, cart_item_count, email_hash,
phone_hash.
"""

from __future__ import annotations

from packages.features.compute import FEATURE_NAMES

C_CLASS_FIELDS = frozenset(
    {
        "event_id",
        "ts",
        "user_agent",
        "device_id",
        "fingerprint_hash",
        "checkout_path",
        "time_on_site_ms",
        "is_guest",
        "cart_item_count",
        "email_hash",
        "phone_hash",
    }
)


def test_feature_names_never_intersect_c_class_fields():
    overlap = set(FEATURE_NAMES) & C_CLASS_FIELDS
    assert not overlap, f"C-class fields leaked into FEATURE_NAMES: {overlap}"


def test_feature_names_are_the_documented_24():
    assert len(FEATURE_NAMES) == 24
    assert len(set(FEATURE_NAMES)) == 24  # no duplicates
