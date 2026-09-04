// Day 8, Step 8 -- a DIRECT PORT of packages/contracts/decision.py's
// `resolve_client_outcome()` + `UI_ROUTING_TABLE` (the sole authority for App
// Flow v2 SS4's 8-row table). The routing semantics are already specified in
// Python; this mirrors them, it does not re-derive them. Pinned equal to the
// Python table by tests/acceptance/test_storefront_routing.py.
//
// `fail_open` is never on the wire (TRD SS5.2) -- it is the ABSENCE of a
// decision, signalled by a timeout / connection error / 5xx. `shed` is
// signalled by the `X-Tollgate-Shed` response header, not a body field.

export const UI_ROUTING_TABLE = {
  allow: "S5",
  monitor: "S5",
  throttle: "S7",
  challenge: "S3",
  step_up: "S4",
  block: "S6",
  shed: "S5",
  fail_open: "S5",
};

export const CLIENT_OUTCOMES = [
  "allow",
  "monitor",
  "throttle",
  "challenge",
  "step_up",
  "block",
  "shed",
  "fail_open",
];

/**
 * @param statusCode number | null   -- null on a timeout / connection error
 * @param headers     {get?: fn} | object   -- response headers
 * @param body        object | null
 * @param error       any | null
 * @returns one of CLIENT_OUTCOMES
 */
export function resolveClientOutcome({ statusCode, headers, body, error }) {
  const header = (name) => {
    if (!headers) return null;
    if (typeof headers.get === "function") return headers.get(name);
    return headers[name] ?? null;
  };

  if (error != null || statusCode == null || statusCode >= 500) {
    return "fail_open";
  }
  if (header("X-Tollgate-Shed") === "1") {
    return "shed";
  }
  if (body == null || !("decision" in body)) {
    return "fail_open";
  }
  return body.decision;
}

export function screenForOutcome(outcome) {
  return UI_ROUTING_TABLE[outcome] || "S5";
}
