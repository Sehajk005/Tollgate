// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §13 -- FIX-M-013, FIX-M-006, FIX-M-025.
//
// The discriminability audit is a TWO-SIDED question ("how separable is this
// feature alone"), so:
//   * bar length encodes separability = |AUC - 0.5| (0 -> 0.5), not raw AUC --
//     an inverted near-perfect discriminator gets a LONG bar, not a short one
//   * direction (↑ / ↓ inverted) is a separate, non-length channel; the raw
//     AUC is always printed so nothing is hidden
//   * the flag is read from `flagged_two_sided` in the artifact -- this
//     component performs NO threshold comparison of its own (M-012, and the
//     `>` vs `>=` drift found in planning). The threshold rule position is
//     derived from `univariate_auc_threshold`, never a `0.95` literal.
//
// Three groups, in order (FIX-M-006):
//   Flagged (6)   amber bars, ONE group header, each feature's own reason
//   Measured (4)  grey bars, separability encoding, direction glyph
//   Not fed (14)  NO bars -- the same null primitive as unresolvable recall,
//                 collapsed behind a disclosure; the string "0.500" never appears

import { useState } from "react";

import { auc as fmtAuc, separability as fmtSep } from "../../lib/format.js";
import UnavailableGroup from "../metrics/UnavailableGroup.jsx";

const NAME_COL = "minmax(clamp(10rem, 22ch, 16.25rem), max-content)";

function DirectionGlyph({ direction }) {
  if (direction !== "inverted" && direction !== "positive") return null;
  const inverted = direction === "inverted";
  return (
    <span
      className="tg-mono-caption"
      style={{ color: inverted ? "var(--viz-flag)" : "var(--tg-text-2)" }}
      aria-label={inverted ? "inverted direction" : "positive direction"}
    >
      {inverted ? "↓ inverted" : "↑"}
    </span>
  );
}

function AuditRow({ feature, threshold, flagged }) {
  const sep = feature.separability;
  const frac = sep == null ? 0 : Math.max(0, Math.min(1, sep / 0.5));
  const markerLeft = threshold == null ? null : `${((threshold - 0.5) / 0.5) * 100}%`;
  return (
    <div
      className="tg-metric-row"
      role="group"
      aria-label={
        `${feature.name}: separability ${fmtSep(sep)}, raw AUC ${fmtAuc(feature.auc)}` +
        (feature.direction === "inverted" ? ", inverted" : "") +
        (flagged ? ", flagged as a probable generator artifact" : "")
      }
      style={{
        display: "grid",
        gridTemplateColumns: `${NAME_COL} minmax(6rem, 1fr) minmax(7rem, max-content)`,
        alignItems: "center",
        gap: 12,
        padding: "2px 0",
      }}
    >
      <span
        className="tg-mono-caption"
        title={feature.name}
        style={{ color: "var(--tg-text-2)", overflowWrap: "anywhere", wordBreak: "break-word" }}
      >
        {feature.name}
      </span>
      <div
        aria-hidden="true"
        style={{
          position: "relative",
          height: 12,
          background: "var(--tg-surface-2)",
          borderRadius: 2,
        }}
      >
        {markerLeft != null && (
          <div
            data-threshold-marker="true"
            style={{
              position: "absolute",
              left: markerLeft,
              top: -2,
              bottom: -2,
              width: 1,
              background: "var(--viz-threshold)",
            }}
          />
        )}
        <div
          style={{
            width: `${frac * 100}%`,
            height: 12,
            borderRadius: 2,
            background: flagged ? "var(--viz-flag)" : "var(--viz-series)",
          }}
        />
      </div>
      <span
        className="tg-mono-data tg-num"
        style={{ textAlign: "right", display: "inline-flex", gap: 8, justifyContent: "flex-end" }}
      >
        <DirectionGlyph direction={feature.direction} />
        <span>AUC {fmtAuc(feature.auc)}</span>
      </span>
    </div>
  );
}

export default function AuditBars({ block3 }) {
  const { groups, threshold, separabilityThreshold, observedMax } = block3;
  const [notFedOpen, setNotFedOpen] = useState(false);

  // `statistic` and `training_set` are methodology detail -- they render in the
  // Methodology panel (d6FieldCoverage marks them RENDERED_IN_METHODOLOGY_PANEL),
  // not in this block's caption.
  return (
    <div>
      <p className="tg-caption" style={{ color: "var(--tg-text-mute)", margin: "0 0 8px" }}>
        Ranked by separability |AUC − 0.5| (0 to 0.5). The rule is the operating threshold, at
        separability {separabilityThreshold == null ? "n/a" : fmtSep(separabilityThreshold)}{" "}
        (from the artifact). Observed maximum separability{" "}
        {observedMax == null ? "n/a" : fmtSep(Math.abs(observedMax - 0.5))} · raw AUC{" "}
        {observedMax == null ? "n/a" : fmtAuc(observedMax)}.
      </p>

      {/* Flagged -- probable generator artifacts */}
      <h3 className="tg-label" style={{ color: "var(--viz-flag)", margin: "12px 0 2px" }}>
        {groups.flagged.length} features excluded as probable generator artifacts
      </h3>
      {groups.flagged.map((f) => (
        <div key={f.name}>
          <AuditRow feature={f} threshold={threshold} flagged />
          {f.reason && (
            <p
              className="tg-caption"
              style={{ color: "var(--tg-text-mute)", margin: "0 0 6px", paddingLeft: 4 }}
            >
              {f.reason}
            </p>
          )}
        </div>
      ))}

      {/* Measured */}
      <h3 className="tg-label" style={{ color: "var(--tg-text-2)", margin: "16px 0 2px" }}>
        {groups.measured.length} measured
      </h3>
      {groups.measured.map((f) => (
        <AuditRow key={f.name} feature={f} threshold={threshold} flagged={f.flaggedTwoSided} />
      ))}

      {/* Not fed -- no measurement */}
      <div style={{ marginTop: 16 }}>
        <button
          type="button"
          onClick={() => setNotFedOpen((v) => !v)}
          aria-expanded={notFedOpen}
          className="tg-label"
          style={{
            background: "transparent",
            border: "none",
            padding: "2px 0",
            cursor: "pointer",
            color: "var(--tg-text-2)",
          }}
        >
          {groups.notFed.length} not fed — no measurement {notFedOpen ? "▾" : "▸"}
        </button>
        {notFedOpen && (
          <UnavailableGroup
            testid="block3-not-fed"
            reason={
              `These ${groups.notFed.length} feature slots carry a constant 0.0 — they were ` +
              "never fed a value, so there is no measurement to report (Decision 43). They can " +
              "be reinstated when store-relative quantile transforms land."
            }
            rows={groups.notFed.map((f) => ({
              key: f.name,
              label: f.name,
              text: f.reason || "constant — un-fed slot",
              // A7: the accessible name must not read as a bare zero -- keep the
              // literal "constant 0.0" out of the aria-label (it stays in the
              // visible row text).
              ariaLabel: `${f.name}: not fed — this slot carries a constant value and was never given a measurement`,
            }))}
          />
        )}
      </div>
    </div>
  );
}
