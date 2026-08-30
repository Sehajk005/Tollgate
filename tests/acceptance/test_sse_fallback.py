"""
Source: Day-8 Plan Step 3 -- a Python source-contract test over
`hooks/useEventStream.js` (the backend half is `test_stream_recent.py`).
Pins App Flow v2 SS7: "Native reconnect; 5 s polling fallback."

  * a 5000 ms poll is INSTALLED on the EventSource `error` and CLEARED on
    `open`;
  * the poll targets `/v1/stream/recent`;
  * the hook never surfaces an error page -- it degrades to last-known-good.
"""

from __future__ import annotations

from pathlib import Path

HOOK = (
    Path(__file__).resolve().parents[2]
    / "services" / "dashboard" / "src" / "hooks" / "useEventStream.js"
)


class TestSseFallback:
    def test_hook_uses_eventsource_and_the_recent_polling_endpoint(self):
        src = HOOK.read_text(encoding="utf-8")
        assert "new EventSource(" in src
        assert '"/v1/stream"' in src
        assert "/v1/stream/recent" in src

    def test_five_second_poll_installed_on_error_and_cleared_on_open(self):
        src = HOOK.read_text(encoding="utf-8")
        assert "5000" in src, "the poll interval is not 5000 ms"
        assert "setInterval(" in src and "clearInterval(" in src

        # onerror -> starts polling (setInterval)
        assert "onerror" in src
        err_idx = src.index("onerror")
        after_err = src[err_idx:err_idx + 400]
        assert "startPolling" in after_err or "setInterval" in after_err, (
            "the error handler does not install the polling fallback"
        )

        # onopen -> stops polling (clearInterval)
        assert "onopen" in src
        open_idx = src.index("onopen")
        after_open = src[open_idx:open_idx + 400]
        assert "stopPolling" in after_open or "clearInterval" in after_open, (
            "the open handler does not clear the polling fallback"
        )

    def test_hook_exposes_a_connection_mode_and_never_throws_to_the_ui(self):
        src = HOOK.read_text(encoding="utf-8")
        assert "connectionMode" in src
        for mode in ("live", "polling", "reconnecting"):
            assert f'"{mode}"' in src, f"connection mode {mode!r} not represented"
        # the poll body swallows fetch errors rather than surfacing them
        assert "catch" in src
