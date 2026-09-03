// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §10 FIX-FE-02 / M-014 / M-033.
// ONE authoritative number/currency policy for the Metrics page. No scattered
// `.toFixed()`, no browser-locale-dependent INR (the audit found the ₹ headline
// rendering `₹2,32,145` for an en-IN viewer and `₹232,145` for en-US -- the
// same artifact, a different headline).
//
// Every function returns the string `NA` for null / undefined / NaN / non-finite
// input -- it NEVER throws and NEVER coerces a missing value to `0`.

export const NA = "n/a";

const _isNum = (x) => typeof x === "number" && Number.isFinite(x);

// Constructed ONCE, with an explicit locale, so the output is deterministic
// regardless of the host's default locale or timezone.
const _inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const _grouped = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Integer rupees from MINOR units (paise), en-IN digit grouping, pinned. */
export function inr(minorUnits) {
  if (!_isNum(minorUnits)) return NA;
  return _inr.format(Math.round(minorUnits / 100));
}

const _fixed = (x, digits) => (_isNum(x) ? x.toFixed(digits) : NA);

/** AP / AUC / TPR / recall / precision / prevalence / separability -- 3 dp. */
export const ap = (x) => _fixed(x, 3);
export const auc = (x) => _fixed(x, 3);
export const rate = (x) => _fixed(x, 3);
export const prevalence = (x) => _fixed(x, 3);
export const separability = (x) => _fixed(x, 3);

/** ECE / Brier -- 4 dp (values reach 7e-4; 3 dp would round to 0.001). */
export const ece = (x) => _fixed(x, 4);
export const brier = (x) => _fixed(x, 4);

/** FPR -- 4 dp, or `1.3e-3` scientific notation for a non-zero value below 1e-3
 *  (the decision region lives at 1e-3). */
export function fpr(x) {
  if (!_isNum(x)) return NA;
  if (x > 0 && x < 1e-3) return x.toExponential(1);
  return x.toFixed(4);
}

/** Counts / denominators -- integer, grouped only at or above 10 000. */
export function count(n) {
  if (!_isNum(n)) return NA;
  const r = Math.round(n);
  return Math.abs(r) >= 10000 ? _grouped.format(r) : String(r);
}

/** A fraction in [0,1] as a 1-dp percentage, e.g. 0.0753 -> "7.5%". */
export function pct(x) {
  if (!_isNum(x)) return NA;
  return `${(x * 100).toFixed(1)}%`;
}

/** π value, e.g. 0.001 / 0.9 -- shown exactly as the artifact spells it, no
 *  trailing-zero padding. Used for regime / axis labels (M-021). */
export function pi(x) {
  if (!_isNum(x)) return NA;
  return String(x);
}
