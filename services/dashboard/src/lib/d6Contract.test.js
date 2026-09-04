// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.6 FE-T-CONTRACT-01..11 --
// the nine missing-value cases, the malformed fixtures, both schema versions,
// and the "no fabricated zero" invariant enforced at source.

import { describe, expect, it } from "vitest";

import contractSource from "./d6Contract.js?raw";
import real from "../__fixtures__/realArtifact.js";
import {
  malformedCurve,
  missingBlock,
  missingProvenance,
  wrongSchemaVersion,
} from "../__fixtures__/malformed.js";
import { ArtifactContractError, normaliseMetric, parseArtifact } from "./d6Contract.js";

const unavailable = (m) => {
  expect(m.available).toBe(false);
  expect(typeof m.reason).toBe("string");
  expect(m.reason.length).toBeGreaterThan(0);
  expect(m.value).toBeNull();
};

describe("FE-T-CONTRACT-01..09: nine missing-value shapes never become a number", () => {
  it("01 resolvable:false -> unavailable, reason 'unresolvable', keeps n_neg", () => {
    const m = normaliseMetric({ value: 0.97, n_neg: 221, resolvable: false, ci_low: 0, ci_high: 0.017 });
    unavailable(m);
    expect(m.reason).toBe("unresolvable");
    expect(m.detail.n_neg).toBe(221);
  });

  it("02 constant feature reason survives via the Unavailable envelope", () => {
    const m = normaliseMetric({ value: null, available: false, reason: "constant 0.0 -- un-fed slot" });
    unavailable(m);
    expect(m.reason).toContain("un-fed");
  });

  it("03 an absent optional key -> unavailable, reason 'absent'", () => {
    unavailable(normaliseMetric(undefined));
    expect(normaliseMetric(undefined).reason).toBe("absent");
  });

  it("04 an explicit null -> unavailable, reason 'unspecified'", () => {
    unavailable(normaliseMetric(null));
    expect(normaliseMetric(null).reason).toBe("unspecified");
  });

  it("05 an empty dataset (empty object) -> unavailable", () => {
    unavailable(normaliseMetric({}));
  });

  it("06 a mathematically undefined metric (recall value null, resolvable true) -> 'unreachable'", () => {
    const m = normaliseMetric({ value: null, n_neg: 400, resolvable: true });
    unavailable(m);
    expect(m.reason).toBe("unreachable");
  });

  it("07 a missing backend metric (Unavailable envelope, available:false) -> its reason", () => {
    const m = normaliseMetric({ value: null, available: false, reason: "harness run without --model-dir" });
    unavailable(m);
    expect(m.reason).toContain("model-dir");
  });

  it("08 a malformed value (a string) -> unavailable, never coerced", () => {
    unavailable(normaliseMetric("lots"));
  });

  it("09 a non-finite number -> unavailable", () => {
    unavailable(normaliseMetric(Number.POSITIVE_INFINITY));
    unavailable(normaliseMetric(Number.NaN));
  });

  it("a genuinely available number passes through", () => {
    const m = normaliseMetric(0.789);
    expect(m.available).toBe(true);
    expect(m.value).toBe(0.789);
    expect(m.reason).toBeNull();
  });
});

describe("FE-T-CONTRACT-10: no fabricated zero anywhere in d6Contract.js", () => {
  it("the module source contains no `|| 0`, `?? 0`, or `Number(x) || 0`", () => {
    const code = contractSource.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(code).not.toMatch(/\|\|\s*0\b/);
    expect(code).not.toMatch(/\?\?\s*0\b/);
    expect(code).not.toMatch(/Number\([^)]*\)\s*\|\|\s*0/);
  });
});

describe("FE-T-CONTRACT-11: both schema versions parse; unsupported throws", () => {
  it("parses the committed v2 artifact", () => {
    expect(parseArtifact(real).schemaVersion).toBe(2);
  });

  it("parses a v1-shaped artifact", () => {
    expect(parseArtifact({ ...real, schema_version: 1 }).schemaVersion).toBe(1);
  });

  it("throws a typed, named error for schema_version 99", () => {
    expect(() => parseArtifact(wrongSchemaVersion)).toThrow(ArtifactContractError);
    try {
      parseArtifact(wrongSchemaVersion);
    } catch (e) {
      expect(e.message).toContain("99");
      expect(e.message).toContain("python -m eval.harness");
      expect(e.path).toBe("schema_version");
    }
  });
});

describe("malformed fixtures each throw a distinct, named ArtifactContractError", () => {
  it("missing provenance names 'provenance'", () => {
    expect(() => parseArtifact(missingProvenance)).toThrow(/provenance/);
  });
  it("missing block names 'block3_audit'", () => {
    expect(() => parseArtifact(missingBlock)).toThrow(/block3_audit/);
  });
  it("empty curve_pi0 names 'block4_cost.curve_pi0'", () => {
    let err;
    try {
      parseArtifact(malformedCurve);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ArtifactContractError);
    expect(err.path).toBe("block4_cost.curve_pi0");
  });
  it("a non-object raw throws, not a TypeError", () => {
    expect(() => parseArtifact(null)).toThrow(ArtifactContractError);
    expect(() => parseArtifact(42)).toThrow(ArtifactContractError);
  });
});
