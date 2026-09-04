"""
Source: Day-8 Plan Step 5 -- a Python source-contract test. D6 renders from
the COMMITTED artifact with zero live computation (App Flow v2 SS5 D6:
"Static render. No live computation on stage.").

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

    def test_all_six_blocks_are_referenced(self):
        src = D6.read_text(encoding="utf-8")
        for block in (
            "block1_per_tier",
            "block2_negative_controls",
            "block3_audit",
            "block4_cost",
            "block5_calibration",
            "block6_baselines",
        ):
            assert block in src, f"D6Metrics.jsx does not render {block}"

    def test_cost_curve_renders_both_regimes_both_optima_ribbon_and_gap(self):
        src = (CHARTS / "CostCurve.jsx").read_text(encoding="utf-8")
        assert "curve_pi0" in src and "curve_pi1" in src, "both prevalence regimes"
        assert "f1_optimal" in src and "cost_optimal" in src, "both optima markers"
        assert "ribbon" in src, "the sensitivity ribbon"
        assert "rupee_gap_minor" in src, "the rupee gap"
        # both pi values printed on the axis label, not hunted for in a caption
        assert "π₀" in src and "π₁" in src
