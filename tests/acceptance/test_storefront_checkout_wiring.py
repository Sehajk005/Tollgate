"""
Day 9 -- DEF-D9-010 regression guard (P1).

The storefront's normal checkout was broken: `S2Checkout.jsx` wired the primary
"Pay" button as `onClick={pay}`. React then passes the click `SyntheticEvent`
as the first positional argument of `pay(extraHeaders = {})`, and `pay` spreads
`extraHeaders` straight into the `fetch` request `headers`:

    headers: { "Content-Type": ..., "X-Tollgate-Key": API_KEY, ...extraHeaders }

so the event's enumerable props (`nativeEvent`, `target`, `getModifierState`,
...) become header entries -> `fetch` throws
`TypeError: Failed to execute 'fetch' on 'Window': Invalid value` -> `pay()`
catches it -> `resolveClientOutcome({error})` -> `"fail_open"` -> the customer
sees a false "Order confirmed" (S5) with NO `/v1/score` request, NO scored
attempt and NO dashboard event. App Flow J6 step 1 (normal checkout) was dead.

The storefront has no JS test runner (only Vite); the established pattern for
guarding its source is a Python source-contract test (see
`test_storefront_routing.py`). This guard pins the two structural facts whose
combination caused the defect:

  1. `pay(extraHeaders = {})` still spreads `...extraHeaders` into the `fetch`
     headers  -- i.e. passing `pay` a non-object still corrupts the request, so
     the wiring below genuinely matters;
  2. the primary Pay button does NOT hand `pay` the React event -- it is wired
     `onClick={() => pay()}`, a zero-argument call, never the bare
     `onClick={pay}`.

End-to-end proof that a real DOM click now reaches the scorer and persists an
`attempt_score` row is recorded in `evidence/day-9/` (Demo Rehearsal #1).
"""

from __future__ import annotations

import re
from pathlib import Path

SF_SRC = Path(__file__).resolve().parents[2] / "services" / "storefront" / "src"
S2_CHECKOUT = SF_SRC / "screens" / "S2Checkout.jsx"


class TestStorefrontCheckoutWiring:
    def _src(self) -> str:
        return S2_CHECKOUT.read_text(encoding="utf-8")

    def test_pay_still_spreads_extra_headers_into_the_fetch_headers(self):
        """Guard-meaningfulness: the wiring below only matters while `pay`
        forwards its first arg into the request headers."""
        src = self._src()
        assert re.search(r"function pay\(\s*extraHeaders\s*=\s*\{\}\s*\)", src), (
            "pay() no longer takes `extraHeaders = {}` as its first parameter -- "
            "revisit this guard and the DEF-D9-010 reasoning."
        )
        # `...extraHeaders` appears inside the fetch `headers:` object literal.
        headers_block = re.search(r"headers:\s*\{(.*?)\}", src, re.DOTALL)
        assert headers_block, "could not locate the fetch `headers:` object in pay()"
        assert "...extraHeaders" in headers_block.group(1), (
            "pay() no longer spreads `...extraHeaders` into the request headers -- "
            "revisit this guard and the DEF-D9-010 reasoning."
        )

    def test_pay_button_does_not_hand_react_event_to_pay(self):
        """DEF-D9-010: `onClick={pay}` passes the SyntheticEvent as
        `pay`'s `extraHeaders` -> spread into fetch headers -> request throws ->
        false 'Order confirmed'."""
        src = self._src()
        assert not re.search(r"onClick=\{\s*pay\s*\}", src), (
            "DEF-D9-010 regression: the Pay button is wired `onClick={pay}`, so "
            "React passes the click event as pay()'s `extraHeaders` and it is "
            "spread into the /v1/score fetch headers -- the request throws, the "
            "checkout is never scored, and the customer sees a false confirmation. "
            "Wire it `onClick={() => pay()}`."
        )

    def test_pay_button_is_wired_as_a_zero_argument_call(self):
        src = self._src()
        assert re.search(r"onClick=\{\s*\(\)\s*=>\s*pay\(\)\s*\}", src), (
            "the primary Pay button must be wired `onClick={() => pay()}` so the "
            "React event cannot reach pay()'s `extraHeaders` (DEF-D9-010)."
        )

    def test_demo_readout_surfaces_a_non_2xx_transport_status(self):
        """DEF-D9-012: a `/v1/score` 401 used to render only as `tier: fail_open`
        + S5 'Order confirmed'. The `?demo=1` readout must also show the HTTP
        status so a misconfigured demo is visible."""
        src = self._src()
        assert "setNetStatus(" in src, "pay() must record the transport status"
        assert re.search(r"netStatus\s*!==?\s*200|netStatus\s*!=\s*null", src), (
            "the demo readout must render the transport status when it is not 200"
        )
        assert "HTTP {netStatus}" in src or "HTTP ${netStatus}" in src, (
            "the demo readout must show `HTTP <code>` for a non-2xx /v1/score"
        )
