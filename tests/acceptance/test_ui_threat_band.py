"""
Source: Day-8 Plan Step 3 -- a Python source-contract test (the idiom
`test_simulator_safety.py` established; no JS test runner is added on Day 8,
Risk R7). Scans `ThreatBand.jsx` + `lib/labels.js` and asserts:

  * all four `threat_state` values (calm / elevated / under_attack / resolved)
    map to a NON-EMPTY UPPERCASE text label AND a DISTINCT glyph;
  * no state is distinguished by colour alone -- ThreatBand renders both the
    text label and a shape glyph keyed on the state.

This pins UIUX v2 SS2.5's accessibility floor: "Colour is never load-bearing.
Every threat state carries a text label AND a shape."
"""

from __future__ import annotations

import re
from pathlib import Path

DASH_SRC = Path(__file__).resolve().parents[2] / "services" / "dashboard" / "src"
LABELS = DASH_SRC / "lib" / "labels.js"
THREAT_BAND = DASH_SRC / "components" / "ThreatBand.jsx"

STATES = ("calm", "elevated", "under_attack", "resolved")


def _object_literal(text: str, name: str) -> dict:
    m = re.search(rf"{name}\s*=\s*\{{(.*?)\}}", text, re.DOTALL)
    assert m, f"{name} object literal not found"
    body = m.group(1)
    out = {}
    for km, vm in re.findall(r'(\w+)\s*:\s*"([^"]*)"', body):
        out[km] = vm
    return out


class TestUiThreatBand:
    def test_four_states_have_non_empty_uppercase_labels(self):
        labels = _object_literal(LABELS.read_text(encoding="utf-8"), "THREAT_LABELS")
        for state in STATES:
            assert state in labels, f"THREAT_LABELS missing {state!r}"
            v = labels[state]
            assert v.strip(), f"THREAT_LABELS[{state!r}] is empty"
            assert v == v.upper(), f"THREAT_LABELS[{state!r}] = {v!r} is not uppercase"

    def test_four_states_have_distinct_glyphs(self):
        glyphs = _object_literal(LABELS.read_text(encoding="utf-8"), "THREAT_GLYPHS")
        for state in STATES:
            assert state in glyphs, f"THREAT_GLYPHS missing {state!r}"
        values = [glyphs[s] for s in STATES]
        assert len(set(values)) == len(values), f"glyphs are not all distinct: {values}"

    def test_threat_band_renders_label_and_glyph_not_colour_alone(self):
        src = THREAT_BAND.read_text(encoding="utf-8")
        # imports and uses the label map
        assert "THREAT_LABELS" in src
        # renders a shape glyph keyed on the state (not just a colour style)
        assert "THREAT_GLYPHS" in src
        assert "ThreatGlyph" in src, "no glyph component -- state would be colour-only"
        # the four glyph variants the spec names
        for variant in ("hollow", "half", "filled", "check"):
            assert variant in src, f"glyph variant {variant!r} not drawn"

    def test_threat_state_is_rendered_verbatim_not_derived(self):
        src = THREAT_BAND.read_text(encoding="utf-8")
        # the component takes threat_state as a prop; it must not re-derive it
        # from rules_fired / decision the way the Day-2 stand-in warned against.
        assert "threatState" in src
        assert "rules_fired" not in src and "decision" not in src, (
            "ThreatBand appears to derive the state locally instead of rendering it"
        )
