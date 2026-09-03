// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §11 -- FIX-M-001, FIX-M-002,
// FIX-M-015, FIX-M-016, FIX-M-028.
//
// Eval Protocol §2.1 sets TWO rules and they are implemented as two distinct
// things:
//   * cross-tier comparison uses recall @ fixed FPR (default 1e-3) -- and it is
//     UNRESOLVABLE at every tier here (221-316 negatives vs the 1000 a 1e-3 FPR
//     needs). That fact is a headline finding, not a footnote -- 1a.
//   * PR-AUC is reported within a tier with that tier's prevalence printed
//     beside it, and every tier is resampled to a common eval prevalence
//     (π_eval = 0.01). Both raw and resampled appear -- 1b (π_eval, the primary
//     rendered cross-tier comparable) and 1c (tier-own prevalence, NOT
//     cross-tier).
//
// No `lift` metric is minted (brief: "Do not invent another metric"). The
// trivial-classifier floor is drawn as a reference marker instead, so the lift
// is visible as geometry: the π_eval=0.01 floor in 1b, the tier's own
// prevalence in 1c.
//
// The evasive tier's 390 samples come from the `tier_e` split, not
// `temporal_test`; the row is LABELLED with its split but the bar gets no
// special treatment (UIUX §6.13: "simply the fourth bar, at whatever height it
// is").

import { ap as fmtAp, count as fmtCount, pi as fmtPi } from "../../lib/format.js";
import UnavailableGroup from "./UnavailableGroup.jsx";

const TIERS = ["easy", "medium", "hard", "evasive"];
const SERIES = [
  { key: "model", label: "model", hatch: false },
  { key: "b0", label: "B0", hatch: true },
];

// A hatched fill, SAME hue -- distinguished by texture not colour (UIUX §2.4:
// no categorical rainbow; CostCurve distinguishes π₀/π₁ by dash, not hue).
const HATCH =
  "repeating-linear-gradient(45deg, var(--viz-series) 0 3px, transparent 3px 6px)";

function splitSuffix(split) {
  if (split === "tier_e") return "tier_e — adversarial split";
  return split || "";
}

function Bar({ frac, hatch }) {
  const w = Math.max(0, Math.min(1, frac == null ? 0 : frac));
  return (
    <div
      aria-hidden="true"
      style={{
        position: "relative",
        height: 12,
        background: "var(--tg-surface-2)",
        borderRadius: 2,
      }}
    >
      <div
        style={{
          width: `${w * 100}%`,
          height: 12,
          borderRadius: 2,
          background: hatch ? HATCH : "var(--viz-series)",
        }}
      />
    </div>
  );
}

function ReferenceMarker({ value, max, label }) {
  if (value == null || max <= 0) return null;
  const left = `${(value / max) * 100}%`;
  return (
    <div
      aria-hidden="true"
      data-ref-marker={label}
      data-ref-value={value}
      style={{
        position: "absolute",
        left,
        top: -2,
        bottom: -2,
        width: 1,
        background: "var(--viz-threshold)",
      }}
    />
  );
}

/**
 * One tier's paired model/B0 AP bars for a given AP flavour.
 * `flavour` is "eval" (1b, marker = π_eval) or "raw" (1c, marker = tier prevalence).
 */
function TierApRows({ tier, tm, flavour, piEval }) {
  const markerValue =
    flavour === "eval" ? piEval : (tm.model && tm.model.prevalence) ?? null;
  const markerLabel = flavour === "eval" ? "π_eval" : "prevalence";
  return (
    <>
      {SERIES.map((s, si) => {
        const row = tm[s.key];
        if (!row) return null;
        const value = flavour === "eval" ? row.apAtEvalPrevalence : row.apRaw;
        const shownValue = fmtAp(value);
        const condition =
          flavour === "eval"
            ? `π_eval ${fmtPi(piEval)}`
            : `prevalence ${fmtAp(row.prevalence)} · n=${fmtCount(row.n)}`;
        const isFirst = si === 0;
        const tierLabel = isFirst ? (
          <>
            {tier}{" "}
            <span className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
              {splitSuffix(row.split)}
            </span>
          </>
        ) : (
          <span style={{ color: "var(--tg-text-mute)" }}>{tier}</span>
        );
        return (
          <div
            key={`${tier}-${s.key}`}
            className="tg-metric-row"
            role="group"
            aria-label={`${tier}, ${s.label}, average precision ${shownValue}, ${condition}`}
            style={{
              display: "grid",
              gridTemplateColumns:
                "minmax(9rem, 15rem) 4rem minmax(6rem, 1fr) minmax(9rem, max-content)",
              alignItems: "center",
              gap: 12,
              padding: "3px 0",
            }}
          >
            <span className="tg-body" style={{ color: "var(--tg-text-2)" }}>
              {tierLabel}
            </span>
            <span className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
              {s.label}
            </span>
            <div style={{ position: "relative" }}>
              <ReferenceMarker value={markerValue} max={1} label={markerLabel} />
              <Bar frac={value} hatch={s.hatch} />
            </div>
            <span
              className="tg-mono-data tg-num"
              style={{ textAlign: "right", color: "var(--tg-text)" }}
            >
              {shownValue}
              <span style={{ color: "var(--tg-text-mute)" }}> · {condition}</span>
            </span>
          </div>
        );
      })}
    </>
  );
}

export default function Block1PerTier({ block1 }) {
  const { tiers, piEval, verdict, tiersFromMixedSplits, splitsPresent } = block1;

  // 1a -- the spec-designated cross-tier comparator, unresolvable everywhere.
  const recallRows = [];
  for (const s of SERIES) {
    for (const tier of TIERS) {
      const tm = tiers[tier];
      const rec = tm && tm[s.key] ? tm[s.key].recall : null;
      if (!rec) continue;
      const nNeg = rec.detail && rec.detail.n_neg != null ? rec.detail.n_neg : null;
      recallRows.push({
        key: `${tier}-${s.key}`,
        label: `${tier} · ${s.label === "model" ? "l1-lgbm-v1" : "rules-only-v0"}`,
        detail: { n_neg: nNeg },
        text: `not resolvable · n_neg=${nNeg}`,
        ariaLabel:
          `${tier}, ${s.label}, recall at false-positive rate 1e-3: not resolvable, ` +
          `${nNeg} negatives against the 1000 required`,
      });
    }
  }

  const temporalCount = splitsPresent.filter((x) => x !== "tier_e").length;

  return (
    <div>
      <p className="tg-body" style={{ margin: "0 0 12px", color: "var(--tg-text)" }}>
        {verdict}
      </p>

      {tiersFromMixedSplits && (
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 12px" }}>
          {temporalCount} tier{temporalCount === 1 ? "" : "s"} from temporal_test · 1 from
          tier_e (the adversarial split).
        </p>
      )}

      {/* 1a -- cross-tier comparator (spec-designated) */}
      <section style={{ marginTop: 8 }}>
        <h3 className="tg-label" style={{ margin: "0 0 4px", color: "var(--tg-text-2)" }}>
          1a. Cross-tier comparator — recall @ FPR 1e-3
        </h3>
        <UnavailableGroup
          testid="block1-recall-unavailable"
          reason={
            "recall @ FPR 1e-3 — the spec's designated cross-tier comparator — is not " +
            "resolvable on these splits: 221–316 negatives against the 1,000 a 1e-3 " +
            "false-positive rate requires. Per-tier negative counts are shown in each row."
          }
          rows={recallRows}
        />
      </section>

      {/* 1b -- prevalence-normalised AP, the primary rendered cross-tier comparable */}
      <section style={{ marginTop: 16 }}>
        <h3 className="tg-label" style={{ margin: "0 0 4px", color: "var(--tg-text-2)" }}>
          1b. Prevalence-normalised AP — π_eval = {fmtPi(piEval)} — comparable across tiers
        </h3>
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 6px" }}>
          Every tier resampled to a common evaluation prevalence, so the four values sit on one
          footing. The marker is the trivial-classifier floor at π_eval = {fmtPi(piEval)}.
        </p>
        {TIERS.map((tier) => (
          <TierApRows
            key={`1b-${tier}`}
            tier={tier}
            tm={tiers[tier]}
            flavour="eval"
            piEval={piEval}
          />
        ))}
      </section>

      {/* 1c -- within-tier AP at the tier's own prevalence, NOT cross-tier */}
      <section style={{ marginTop: 16 }}>
        <h3 className="tg-label" style={{ margin: "0 0 4px", color: "var(--tg-text-2)" }}>
          1c. Within-tier AP — at each tier's own prevalence — not cross-tier
        </h3>
        <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 6px" }}>
          Each tier sits on its own prevalence floor (0.43–0.73), drawn as the marker on its own
          bar. These values must not be read across tiers.
        </p>
        {TIERS.map((tier) => (
          <TierApRows
            key={`1c-${tier}`}
            tier={tier}
            tm={tiers[tier]}
            flavour="raw"
            piEval={piEval}
          />
        ))}
      </section>
    </div>
  );
}
