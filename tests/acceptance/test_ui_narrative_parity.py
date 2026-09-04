"""
Source: Day-8 Plan Step 7 -- a Python source-contract test. Pins UIUX v2 SS6.5
requirement 4 ("Template and LLM output render identically. No badge
distinguishing them, no layout shift") and Threat Model SS5 (no HTML
injection path into the narrative).

  * `NarrativeBlock.jsx` contains NO reference to `narrative_source` and NO
    `dangerouslySetInnerHTML`;
  * the 600-char cap is applied IN the component;
  * `narrative_source` appears NOWHERE under `services/dashboard/src/` -- the
    frontend never receives it, so "identical with template and LLM" is
    structurally true, not merely tested.
"""

from __future__ import annotations

from pathlib import Path

DASH_SRC = Path(__file__).resolve().parents[2] / "services" / "dashboard" / "src"
NARRATIVE = DASH_SRC / "components" / "NarrativeBlock.jsx"


class TestUiNarrativeParity:
    def test_narrative_block_has_no_source_dependency_and_no_html_injection(self):
        src = NARRATIVE.read_text(encoding="utf-8")
        assert "narrative_source" not in src, "NarrativeBlock must not depend on narrative_source"
        assert "narrativeSource" not in src
        assert "dangerouslySetInnerHTML" not in src, "no HTML injection path"

    def test_600_char_cap_is_applied_in_the_component(self):
        src = NARRATIVE.read_text(encoding="utf-8")
        assert "600" in src, "the 600-character cap is not in the component"
        assert ".slice(0" in src or ".substring(0" in src, "no hard truncation applied"

    def test_narrative_source_appears_nowhere_in_the_dashboard_frontend(self):
        offenders = []
        for path in DASH_SRC.rglob("*"):
            if path.suffix not in (".js", ".jsx"):
                continue
            if "narrative_source" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(DASH_SRC)))
        assert not offenders, f"`narrative_source` leaked into the frontend: {offenders}"

    def test_no_dangerouslysetinnerhtml_anywhere_in_the_dashboard_frontend(self):
        offenders = []
        for path in DASH_SRC.rglob("*"):
            if path.suffix not in (".js", ".jsx"):
                continue
            if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(DASH_SRC)))
        assert not offenders, f"dangerouslySetInnerHTML present: {offenders}"
