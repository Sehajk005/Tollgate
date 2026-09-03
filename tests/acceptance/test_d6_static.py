"""
Source: Day-8 Plan Step 5, narrowed by METRICS-REMEDIATION-PLAN-2026-09-02.md
§26.2 -- **architectural invariants only**.

D6 is a static render (App Flow v2 SS5 D6: "Static render. No live computation
on stage."). Two invariants survive here; everything that used to grep the JSX
for rendered content is now a real React rendering test under
`services/dashboard/src/` (FE-T-B1..B6, FE-T-GEOM, FE-T-CONTRACT, ...):

  * `D6Metrics.jsx` reaches `eval/outputs/d6.json` by a STATIC `import`, not a
    fetch;
  * neither `D6Metrics.jsx` nor anything under `components/charts/` contains
    `fetch(`, `EventSource`, or `XMLHttpRequest` -- there is no runtime data
    path to remove.
"""

from __future__ import annotations

from pathlib import Path

DASH_SRC = Path(__file__).resolve().parents[2] / "services" / "dashboard" / "src"
D6 = DASH_SRC / "screens" / "D6Metrics.jsx"
CHARTS = DASH_SRC / "components" / "charts"

BANNED = ("fetch(", "EventSource", "XMLHttpRequest", "axios", "WebSocket")


class TestD6Static:
    def test_d6metrics_reaches_the_artifact_by_static_import(self):
        src = D6.read_text(encoding="utf-8")
        assert 'import d6 from "../../../../eval/outputs/d6.json"' in src, (
            "D6Metrics.jsx must static-import the committed artifact"
        )

    def test_no_runtime_data_path_in_d6_or_its_charts(self):
        files = [D6, *sorted(CHARTS.glob("*.jsx"))]
        assert len(files) >= 4, f"expected D6Metrics + 3 chart files, found {files}"
        for f in files:
            src = f.read_text(encoding="utf-8")
            for token in BANNED:
                assert token not in src, f"{f.name} contains a runtime data path: {token!r}"
