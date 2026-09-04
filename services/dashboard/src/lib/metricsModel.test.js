// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §7 / FIX-FE-03 -- the view
// model is a pure function of the parsed artifact; these pin the semantic
// decisions (B0-beats-model, separability sort, unresolvable recall,
// executive-summary numbers) without rendering anything.

import { describe, expect, it } from "vitest";

import real from "../__fixtures__/realArtifact.js";
import { withPriorCorrectionFailed, withResolvableRecall } from "../__fixtures__/synthetic.js";
import { parseArtifact } from "./d6Contract.js";
import { buildMetricsModel } from "./metricsModel.js";

const model = buildMetricsModel(parseArtifact(real));

describe("block 1", () => {
  it("carries π_eval and per-tier model + B0 metrics", () => {
    expect(model.block1.piEval).toBe(0.01);
    const easy = model.block1.tiers.easy;
    expect(easy.model.apRaw).toBeCloseTo(0.789228046757773, 12);
    expect(easy.model.prevalence).toBeCloseTo(0.730816077953715, 12);
    expect(easy.model.apAtEvalPrevalence).toBeCloseTo(0.01783008837101664, 12);
    expect(easy.b0.apRaw).toBeCloseTo(0.9998, 3);
  });

  it("flags that B0 beats the model on raw AP at every tier (M-002)", () => {
    expect(model.block1.b0BeatsModelOnAllApTiers).toBe(true);
    for (const t of ["easy", "medium", "hard", "evasive"]) {
      expect(model.block1.tiers[t].apRawWinner).toBe("b0");
    }
    expect(model.block1.verdict.toLowerCase()).toContain("weaker than b0");
  });

  it("marks the evasive tier as coming from a different split (M-016)", () => {
    expect(model.block1.tiers.evasive.model.split).toBe("tier_e");
    expect(model.block1.tiers.easy.model.split).toBe("temporal_test");
    expect(model.block1.tiersFromMixedSplits).toBe(true);
  });

  it("keeps unresolvable recall as unavailable, never a number", () => {
    const rec = model.block1.tiers.easy.model.recall;
    expect(rec.available).toBe(false);
    expect(rec.reason).toBe("unresolvable");
    expect(rec.value).toBeNull();
    expect(rec.detail.n_neg).toBe(221);
  });

  it("a synthetic resolvable recall becomes available with a value", () => {
    const m = buildMetricsModel(parseArtifact(withResolvableRecall("medium")));
    const rec = m.block1.tiers.medium.model.recall;
    expect(rec.available).toBe(true);
    expect(rec.value).toBe(0.812);
  });
});

describe("block 2", () => {
  it("carries theta_challenge and 6 rows per scenario", () => {
    expect(model.block2.thetaChallenge).toBeCloseTo(0.2571428571428571, 12);
    expect(model.block2.scenarios).toHaveLength(7);
    for (const s of model.block2.scenarios) {
      expect(s.rows.map((r) => r.scorer).slice(0, 2)).toEqual(["l1-lgbm-v1", "rules-only-v0"]);
    }
  });

  it("marks shared_ip_legit single-sample and retry_storm underpowered", () => {
    const sil = model.block2.scenarios.find((s) => s.name === "shared_ip_legit");
    const rs = model.block2.scenarios.find((s) => s.name === "retry_storm");
    const fs = model.block2.scenarios.find((s) => s.name === "flash_sale");
    expect(sil.singleSample).toBe(true);
    expect(rs.underpowered).toBe(true);
    expect(fs.underpowered).toBe(false);
    expect(fs.rows[0].showInterval).toBe(true);
  });

  it("episode_flagged is a boolean, never a 0/1 rate", () => {
    for (const s of model.block2.scenarios) {
      for (const r of s.rows) expect(typeof r.episodeFlagged).toBe("boolean");
    }
  });
});

describe("block 3", () => {
  it("sorts each group by |AUC - 0.5| descending (M-013)", () => {
    const names = model.block3.groups.measured.map((f) => f.name);
    expect(names.indexOf("card_seen_24h")).toBeLessThan(names.indexOf("bin_entropy_5m"));
    expect(model.block3.groups.measured[0].separability).toBeGreaterThanOrEqual(
      model.block3.groups.measured[1].separability,
    );
  });

  it("groups 14 not-fed, 4 measured, 6 flagged", () => {
    expect(model.block3.groups.notFed).toHaveLength(14);
    expect(model.block3.groups.measured).toHaveLength(4);
    expect(model.block3.groups.flagged).toHaveLength(6);
  });

  it("threshold and observed maximum come from the artifact, distinct", () => {
    expect(model.block3.threshold).toBe(0.95);
    expect(model.block3.separabilityThreshold).toBeCloseTo(0.45, 12);
    expect(model.block3.observedMax).toBeCloseTo(0.9975874252835037, 12);
  });

  it("card_seen_24h keeps its raw AUC and an inverted direction", () => {
    const f = model.block3.groups.measured.find((x) => x.name === "card_seen_24h");
    expect(f.auc).toBeCloseTo(0.22475071225071225, 12);
    expect(f.direction).toBe("inverted");
  });
});

describe("block 5", () => {
  it("exposes raw + Platt + Platt+prior for Brier AND ECE, both regimes", () => {
    const p1 = model.block5.regimes.pi1;
    expect(p1.brierRaw).toBeCloseTo(0.1403, 4);
    expect(p1.eceRaw).toBeGreaterThan(0);
    expect(p1.ecePlatt).toBeCloseTo(0.39547724058805567, 12);
    expect(p1.ecePlattPrior).toBeCloseTo(0.2806765620747161, 12);
    expect(p1.eceGap).toBeCloseTo(p1.ecePlatt - p1.ecePlattPrior, 12);
  });

  it("verdict states the π₁ result and the direction convention", () => {
    expect(model.block5.priorCorrectionHelpedAtPi1).toBe(true);
    expect(model.block5.verdict).toContain("0.3955");
    expect(model.block5.verdict).toContain("0.2807");
    expect(model.block5.verdict.toLowerCase()).toContain("lower is better");
  });

  it("a failing-prior fixture flips the verdict", () => {
    const m = buildMetricsModel(parseArtifact(withPriorCorrectionFailed()));
    expect(m.block5.priorCorrectionHelpedAtPi1).toBe(false);
    expect(m.block5.verdict.toLowerCase()).toContain("broken");
  });

  it("reliability points drop empty bins and count them", () => {
    expect(model.block5.reliability.pi0.length + model.block5.emptyBins.pi0).toBe(10);
    for (const p of model.block5.reliability.pi0) expect(p.weight).toBeGreaterThan(0);
  });
});

describe("block 6", () => {
  it("has a model row, a B3 floor with a reason on the null, and 4 per-tier rows", () => {
    expect(model.block6.model.apRaw).toBeGreaterThan(0);
    expect(model.block6.b1SanityFloor.always_positive.available).toBe(false);
    expect(model.block6.b1SanityFloor.always_positive.reason).toMatch(/unreachable/i);
    expect(Object.keys(model.block6.perTier).sort()).toEqual(["easy", "evasive", "hard", "medium"]);
    expect(model.block6.caveats.b2).toContain("B0");
  });
});

describe("executive summary is generated from the model", () => {
  it("contains the B0-beats-model claim and the exact headline numbers", () => {
    const text = model.summary.map((x) => x.text).join(" ");
    expect(text.toLowerCase()).toContain("b0 outperforms the learned model");
    expect(text).toContain("₹2,32,145");
    expect(text).toContain("0.3955");
    expect(text).toContain("0.2807");
    const cost = model.summary.find((x) => x.id === "cost");
    expect(cost.numbers.regimeSwitchSavingMinor).toBeCloseTo(23214508.206055675, 3);
  });
});

describe("freshness", () => {
  it("is 'unknown' with no injected hash, 'current' on a match, 'config-mismatch' otherwise", () => {
    expect(buildMetricsModel(parseArtifact(real)).freshness.state).toBe("unknown");
    const hash = real.provenance.config_hash;
    expect(buildMetricsModel(parseArtifact(real), { currentConfigHash: hash }).freshness.state).toBe("current");
    expect(
      buildMetricsModel(parseArtifact(real), { currentConfigHash: "deadbeef" }).freshness.state,
    ).toBe("config-mismatch");
  });
});
