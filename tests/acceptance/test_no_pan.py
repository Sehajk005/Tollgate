"""
Source: Implementation Plan v2.1 Day 1 acceptance test 5 -- "No raw PAN field
exists on any model" (Threat Model v2 section 2 / section 8: no PAN, no CVV,
no Luhn construction anywhere).
"""

from __future__ import annotations

import re

from packages.contracts import records, wire

FORBIDDEN_FIELD_NAME = re.compile(r"pan|card_?number|primary_account", re.IGNORECASE)

MODEL_MODULES = [wire, records]


def _pydantic_field_names(model_cls) -> set:
    return set(getattr(model_cls, "model_fields", {}).keys())


def _dataclass_field_names(cls) -> set:
    return set(getattr(cls, "__dataclass_fields__", {}).keys())


def test_no_wire_model_has_a_pan_shaped_field():
    for name in dir(wire):
        obj = getattr(wire, name)
        if isinstance(obj, type) and hasattr(obj, "model_fields"):
            for field_name in _pydantic_field_names(obj):
                assert not FORBIDDEN_FIELD_NAME.search(field_name), (
                    f"{obj.__name__}.{field_name} looks like a raw PAN field"
                )


def test_no_record_dataclass_has_a_pan_shaped_field():
    for name in dir(records):
        obj = getattr(records, name)
        if isinstance(obj, type) and hasattr(obj, "__dataclass_fields__"):
            for field_name in _dataclass_field_names(obj):
                assert not FORBIDDEN_FIELD_NAME.search(field_name), (
                    f"{obj.__name__}.{field_name} looks like a raw PAN field"
                )


def test_forbidden_pattern_actually_catches_a_planted_field():
    # Proves the regex isn't vacuously passing.
    assert FORBIDDEN_FIELD_NAME.search("card_number")
    assert FORBIDDEN_FIELD_NAME.search("pan")
    assert FORBIDDEN_FIELD_NAME.search("primary_account_number")
    assert not FORBIDDEN_FIELD_NAME.search("card_hash")
