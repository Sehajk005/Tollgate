"""
Source: Day-8 Plan Step 3 -- a Python source-contract test. Pins UIUX v2 SS7
("The Stream Rail switches to a static snapshot under reduced motion") and
the verbatim media block:

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important; }
  }

  * base.css contains that media block;
  * StreamRail.jsx guards its requestAnimationFrame loop on
    `prefers-reduced-motion` (renders a static snapshot, never schedules a frame);
  * EventTicker motion is CSS-only (no JS animation), so the media block covers it.
"""

from __future__ import annotations

import re
from pathlib import Path

DASH_SRC = Path(__file__).resolve().parents[2] / "services" / "dashboard" / "src"
BASE_CSS = DASH_SRC / "styles" / "base.css"
STREAM_RAIL = DASH_SRC / "components" / "StreamRail.jsx"
EVENT_TICKER = DASH_SRC / "components" / "EventTicker.jsx"


class TestUiReducedMotion:
    def test_base_css_has_the_reduced_motion_media_block(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        assert "@media (prefers-reduced-motion: reduce)" in css
        block = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        assert "animation-duration" in block and "!important" in block
        assert "transition-duration" in block

    def test_stream_rail_guards_its_raf_loop_on_prefers_reduced_motion(self):
        src = STREAM_RAIL.read_text(encoding="utf-8")
        assert "requestAnimationFrame" in src, "the rail should animate normally"
        assert "matchMedia" in src and "prefers-reduced-motion" in src, (
            "the rail does not check prefers-reduced-motion"
        )
        # the reduced-motion branch must return BEFORE any requestAnimationFrame
        # is scheduled -- a static snapshot, never a frame.
        idx_reduce = src.index("prefers-reduced-motion")
        idx_first_raf = src.index("requestAnimationFrame")
        assert idx_reduce < idx_first_raf, (
            "prefers-reduced-motion is checked after the rAF loop is set up"
        )
        reduce_tail = src[idx_reduce:idx_first_raf]
        assert re.search(r"if\s*\(\s*reduce\s*\)", src), "no `if (reduce)` guard"
        assert "return" in reduce_tail

    def test_event_ticker_motion_is_css_only(self):
        src = EVENT_TICKER.read_text(encoding="utf-8")
        assert "@keyframes" in src, "the ticker fade should be a CSS keyframe"
        for banned in ("requestAnimationFrame", "setInterval", "setTimeout", "framer-motion"):
            assert banned not in src, (
                f"{banned} in EventTicker -- motion must be CSS-only so the "
                "prefers-reduced-motion media block covers it"
            )
