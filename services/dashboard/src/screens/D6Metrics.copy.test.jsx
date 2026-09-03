// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §20.4 (M-032 / M-033) + §23.6.
//
// M-032 -- no build-log / internal spec-ID copy in the RENDERED page. The audit
// found `UIUX v2`, `SS6.13`, `Eval Protocol §...` in visible text. Those IDs are
// allowed to live in code COMMENTS (they document intent); they must not be
// authored into JSX text or string literals a user sees. The check mirrors
// AuditBars.test.jsx: strip comments from each composed component's source, then
// scan what is left. (A faithfully RENDERED artifact field -- a flagged
// feature's `reason` -- may itself cite the spec; FIX-M-006 requires printing
// it. So this is a SOURCE scan, not a DOM scan.)
//
// M-033 -- identifiers render as the artifact spells them (`l1-lgbm-v1`), never
// force-uppercased by `.tg-label { text-transform: uppercase }`.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import D6Metrics from "./D6Metrics.jsx";

import d6Screen from "./D6Metrics.jsx?raw";
import block1 from "../components/metrics/Block1PerTier.jsx?raw";
import block2 from "../components/metrics/Block2NegativeControls.jsx?raw";
import block5 from "../components/metrics/Block5Calibration.jsx?raw";
import block6 from "../components/metrics/Block6Baselines.jsx?raw";
import prov from "../components/metrics/ProvenanceHeader.jsx?raw";
import method from "../components/metrics/MethodologyPanel.jsx?raw";
import unavailable from "../components/metrics/UnavailableGroup.jsx?raw";
import opTable from "../components/metrics/OperatingPointTable.jsx?raw";
import scrollRegion from "../components/metrics/ScrollableTableRegion.jsx?raw";
import auditBars from "../components/charts/AuditBars.jsx?raw";
import costCurve from "../components/charts/CostCurve.jsx?raw";
import reliability from "../components/charts/ReliabilityDiagram.jsx?raw";

const SOURCES = {
  "D6Metrics.jsx": d6Screen,
  "Block1PerTier.jsx": block1,
  "Block2NegativeControls.jsx": block2,
  "Block5Calibration.jsx": block5,
  "Block6Baselines.jsx": block6,
  "ProvenanceHeader.jsx": prov,
  "MethodologyPanel.jsx": method,
  "UnavailableGroup.jsx": unavailable,
  "OperatingPointTable.jsx": opTable,
  "ScrollableTableRegion.jsx": scrollRegion,
  "AuditBars.jsx": auditBars,
  "CostCurve.jsx": costCurve,
  "ReliabilityDiagram.jsx": reliability,
};

const stripComments = (src) =>
  src.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");

// The audit's own examples, generalised: SS<n>, "UIUX v2", and any "<doc> §<n>"
// citation of an internal spec.
const SPEC_ID =
  /UIUX v2|\bSS\d|App Flow §|Eval Protocol §|Backend Schema §|Decisions\.md|§\s?\d/;

describe("FE-T-COPY (M-032): the composed components author no internal spec-ID copy", () => {
  for (const [name, src] of Object.entries(SOURCES)) {
    it(`${name} -- no spec ID outside comments`, () => {
      const code = stripComments(src);
      const hit = code.match(SPEC_ID);
      const ctx = hit
        ? code.slice(Math.max(0, hit.index - 40), hit.index + 40).replace(/\s+/g, " ")
        : "";
      expect(hit, hit ? `found "${hit[0]}" in ${name} (context: ${ctx})` : "").toBeNull();
    });
  }
});

describe("FE-T-COPY (M-033): identifiers are not force-uppercased", () => {
  for (const id of ["l1-lgbm-v1", "rules-only-v0"]) {
    it(`"${id}" renders lowercase, never inside a .tg-label`, () => {
      render(<D6Metrics />);
      const nodes = screen.getAllByText(
        (_, el) => el?.children.length === 0 && el.textContent?.includes(id),
      );
      expect(nodes.length).toBeGreaterThan(0);
      for (const n of nodes) {
        expect(n.textContent).toContain(id); // literal lowercase, not "L1-LGBM-V1"
        expect(n.closest(".tg-label")).toBeNull();
      }
    });
  }
});
