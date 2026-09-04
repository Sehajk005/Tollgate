"""
Source: Day-8 Plan Step 8 -- a Python source-contract test. The storefront's
`lib/outcome.js` is a DIRECT PORT of `packages/contracts/decision.py`'s
`resolve_client_outcome()` + `UI_ROUTING_TABLE`; this pins the two equal.

  * the routing map parsed out of `lib/outcome.js` is EXACTLY `UI_ROUTING_TABLE`;
  * all eight `ClientOutcome` values are handled;
  * every screen id in the map except `S4` has a component file
    (S4 -- 3DS step-up -- is not built: unreachable without a confirmed step_up).
"""

from __future__ import annotations

import re
from pathlib import Path

from packages.contracts.decision import UI_ROUTING_TABLE, ClientOutcome

SF_SRC = Path(__file__).resolve().parents[2] / "services" / "storefront" / "src"
OUTCOME_JS = SF_SRC / "lib" / "outcome.js"
SCREENS = SF_SRC / "screens"


def _js_routing_table() -> dict:
    text = OUTCOME_JS.read_text(encoding="utf-8")
    m = re.search(r"UI_ROUTING_TABLE\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert m, "UI_ROUTING_TABLE literal not found in lib/outcome.js"
    return {k: v for k, v in re.findall(r'(\w+)\s*:\s*"(S\d)"', m.group(1))}


class TestStorefrontRouting:
    def test_js_routing_table_is_exactly_the_python_one(self):
        py = {k.value: v for k, v in UI_ROUTING_TABLE.items()}
        js = _js_routing_table()
        assert js == py, f"storefront routing drifted from the Python table:\n js={js}\n py={py}"

    def test_all_eight_client_outcomes_are_handled(self):
        js = _js_routing_table()
        expected = {o.value for o in ClientOutcome}
        assert set(js) == expected
        assert len(expected) == 8

    def test_every_mapped_screen_except_s4_has_a_component_file(self):
        js = _js_routing_table()
        for outcome, screen_id in js.items():
            if screen_id == "S4":
                # deliberately NOT built (App Flow cut candidate #2)
                assert not list(SCREENS.glob("S4*.jsx")), "S4 must not be built"
                continue
            files = list(SCREENS.glob(f"{screen_id}*.jsx"))
            assert files, f"no component for screen {screen_id} (outcome {outcome})"

    def test_resolve_client_outcome_mirrors_the_python_precedence(self):
        src = OUTCOME_JS.read_text(encoding="utf-8")
        # error / null status / 5xx -> fail_open
        assert 'error != null || statusCode == null || statusCode >= 500' in src
        assert '"fail_open"' in src
        # X-Tollgate-Shed header -> shed  (never a body field)
        assert 'X-Tollgate-Shed' in src and '"shed"' in src
        # missing decision -> fail_open
        assert '"decision" in body' in src
