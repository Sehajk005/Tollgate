// Day 8, Step 7 -- the confirm-with-consequence button (UIUX v2 SS6.11).
// `block` and `step_up` require a human, so the button carries the cost
// inline rather than opening a modal -- "a number is a better confirmation
// dialogue than a question". Destructive variant.
//
//   Est. cost if wrong: ₹{C_FP(tier) × entity_count / 100}
//
// C_FP(block)   = aov_minor 120000 × margin_pct 0.30 × P(abandon|block) 1.00 = 36000 minor  -> ₹360/entity
// C_FP(step_up) = aov_minor 120000 × margin_pct 0.30 × P(abandon|step_up) 0.15 = 5400 minor  -> ₹54/entity
// (SS6.11's worked example: ₹720 for two entities at block.)

const C_FP_MINOR = { step_up: 5400, block: 36000 };

export default function ConfirmButton({ tier, entityCount = 1, onConfirm, disabled }) {
  const costRupees = ((C_FP_MINOR[tier] || 0) * entityCount) / 100;
  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <button
        onClick={onConfirm}
        disabled={disabled}
        className="tg-body-strong"
        style={{
          background: "transparent",
          color: "var(--tg-attack)",
          border: "1px solid var(--tg-attack)",
          borderRadius: "var(--tg-radius-sm)",
          padding: "8px 16px",
          cursor: disabled ? "default" : "pointer",
        }}
      >
        Confirm {tier} · {entityCount} {entityCount === 1 ? "entity" : "entities"}
      </button>
      <span className="tg-caption" style={{ color: "var(--tg-text-mute)" }}>
        Est. cost if wrong: ₹{costRupees.toLocaleString()}
      </span>
    </div>
  );
}
