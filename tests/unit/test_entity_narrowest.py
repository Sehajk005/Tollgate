"""
Source: Day-6 Plan §4 (tests/unit, advisory) -- resolve_entity picks the
NARROWEST key that covers the evidence: card -> ipua -> ip, never asn.
"""

from __future__ import annotations

import inspect

import pytest

from packages.detect.policy import EntityKey, resolve_entity


def test_card_scope_resolves_to_the_card_hash():
    e = resolve_entity(scope="card", ip="1.2.3.4", ua_class="desktop_browser", card_hash="c-abc", bin="411111")
    assert e == EntityKey("card", "c-abc")


def test_ipua_scope_resolves_to_the_hashed_ip_ua_pair_not_the_raw_ua():
    e = resolve_entity(scope="ipua", ip="1.2.3.4", ua_class="mobile_browser", card_hash="c", bin="4")
    assert e.entity_type == "ipua"
    assert e.entity_key != "1.2.3.4"
    assert "mobile_browser" not in e.entity_key


def test_ip_scope_resolves_to_the_ip():
    e = resolve_entity(scope="ip", ip="203.0.113.9", ua_class="desktop_browser", card_hash="c", bin="4")
    assert e == EntityKey("ip", "203.0.113.9")


def test_bin_scope_is_available_for_issuer_wide_evidence():
    e = resolve_entity(scope="bin", ip="1.2.3.4", ua_class="desktop_browser", card_hash="c", bin="424242")
    assert e == EntityKey("bin", "424242")


def test_asn_is_not_even_an_argument():
    assert "asn" not in set(inspect.signature(resolve_entity).parameters)


def test_card_scope_without_a_card_hash_narrows_to_ipua():
    e = resolve_entity(scope="card", ip="1.2.3.4", ua_class="desktop_browser", card_hash=None, bin="4")
    assert e.entity_type == "ipua"


def test_entitykey_rejects_store_wide_and_bad_types():
    with pytest.raises(ValueError):
        EntityKey("store", "everything")
    with pytest.raises(ValueError):
        EntityKey("ip", "   ")
    with pytest.raises(ValueError):
        EntityKey("ip", "")
