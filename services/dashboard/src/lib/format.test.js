// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.6 FE-T-FMT-01..08 -- the
// number/currency policy, including the MANDATORY headline test.

import { describe, expect, it } from "vitest";

import {
  NA, ap, auc, brier, count, ece, fpr, inr, pct, pi, prevalence, rate, separability,
} from "./format.js";

describe("FE-T-FMT-01: the ₹2,32,145 headline", () => {
  it("formats regime_switch_saving_minor to the exact rupee string", () => {
    // 23214508.206055675 paise -> ₹232145 -> en-IN grouping "2,32,145"
    expect(inr(23214508.206055675)).toBe("₹2,32,145");
  });
});

describe("FE-T-FMT-02: INR is locale-independent", () => {
  it("uses en-IN digit grouping at every magnitude", () => {
    expect(inr(100000000)).toBe("₹10,00,000"); // 10 lakh
    expect(inr(1234567890)).toBe("₹1,23,45,679");
    expect(inr(999)).toBe("₹10"); // 999 paise -> ₹10 (rounded)
  });
});

describe("FE-T-FMT-03..08: precision policy per quantity", () => {
  it("AP / AUC / rate / prevalence / separability are 3 dp", () => {
    expect(ap(0.789228046757773)).toBe("0.789");
    expect(ap(0.9998)).toBe("1.000"); // pinned: 0.9998 formats to 1.000
    expect(auc(0.2247507)).toBe("0.225");
    expect(rate(0.0753474762253109)).toBe("0.075");
    expect(prevalence(0.730816077953715)).toBe("0.731");
    expect(separability(0.27524928774928775)).toBe("0.275");
  });

  it("ECE / Brier are 4 dp", () => {
    expect(ece(0.0007305349387266664)).toBe("0.0007");
    expect(ece(0.39547724058805567)).toBe("0.3955");
    expect(brier(0.1193)).toBe("0.1193");
  });

  it("FPR is 4 dp, or scientific below 1e-3", () => {
    expect(fpr(0)).toBe("0.0000");
    expect(fpr(0.0013192612137203166)).toBe("0.0013");
    expect(fpr(0.00045)).toBe("4.5e-4");
  });

  it("counts group only at or above 10 000", () => {
    expect(count(720)).toBe("720");
    expect(count(1)).toBe("1");
    expect(count(9999)).toBe("9999");
    expect(count(23214)).toBe("23,214");
  });

  it("pct is a 1-dp percentage of a fraction", () => {
    expect(pct(0.0753474762253109)).toBe("7.5%");
    expect(pct(1)).toBe("100.0%");
  });

  it("pi renders the value verbatim", () => {
    expect(pi(0.001)).toBe("0.001");
    expect(pi(0.9)).toBe("0.9");
  });
});

describe("missing / non-finite input never becomes a number", () => {
  it("returns NA for null / undefined / NaN / Infinity / string", () => {
    for (const fn of [inr, ap, auc, rate, prevalence, separability, ece, brier, fpr, count, pct, pi]) {
      expect(fn(null)).toBe(NA);
      expect(fn(undefined)).toBe(NA);
      expect(fn(NaN)).toBe(NA);
      expect(fn(Infinity)).toBe(NA);
      expect(fn("0.5")).toBe(NA);
    }
  });
});
