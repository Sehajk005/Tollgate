// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.6 FE-T-COVERAGE-01..03.
// The frontend must never silently discard an artifact field.

import { describe, expect, it } from "vitest";

import real from "../__fixtures__/realArtifact.js";
import { deepSet } from "../__fixtures__/mutate.js";
import { FIELD_COVERAGE, checkCoverage } from "./d6FieldCoverage.js";

describe("FE-T-COVERAGE-01: no unlisted leaf in the real artifact", () => {
  it("every leaf pattern of the committed artifact has a coverage entry", () => {
    const { unlisted } = checkCoverage(real);
    expect(unlisted, `unlisted leaf patterns:\n${unlisted.join("\n")}`).toEqual([]);
  });
});

describe("FE-T-COVERAGE-02: no stale entry", () => {
  it("every coverage entry corresponds to a real artifact leaf", () => {
    const { stale } = checkCoverage(real);
    expect(stale, `stale coverage entries:\n${stale.join("\n")}`).toEqual([]);
  });
});

describe("FE-T-COVERAGE-03: every OMITTED carries a >= 20-char reason", () => {
  it("no escape-hatch OMITTED entries", () => {
    const { badReason } = checkCoverage(real);
    expect(badReason).toEqual([]);
    for (const [path, v] of Object.entries(FIELD_COVERAGE)) {
      if (v.kind === "OMITTED") {
        expect(v.reason.trim().length, `${path} reason too short`).toBeGreaterThanOrEqual(20);
      }
    }
  });
});

describe("the contract actually bites", () => {
  it("adding an undeclared leaf produces an `unlisted` entry", () => {
    const mutated = deepSet(real, "block4_cost.a_brand_new_field", 1);
    expect(checkCoverage(mutated).unlisted).toContain("block4_cost.a_brand_new_field");
  });

  it("removing a declared leaf produces a `stale` entry", () => {
    const mutated = { ...real, block4_cost: { ...real.block4_cost } };
    delete mutated.block4_cost.decision_region_fpr_max;
    expect(checkCoverage(mutated).stale).toContain("block4_cost.decision_region_fpr_max");
  });
});
