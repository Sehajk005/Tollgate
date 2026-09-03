import { useMemo, useState } from "react";
import { resolveClientOutcome, screenForOutcome } from "../lib/outcome.js";

// Day 8, Step 8 -- S2 Checkout. Standard card form. This screen owns the
// routing: POST /v1/score -> resolveClientOutcome(status, headers, body, error)
// -> screenForOutcome -> the next screen. S2 is the checkout/routing STATE,
// preserved (not one of the five new screens, but they are unreachable
// without it).
//
// `?demo=1` additions (App Flow SS5 S2): a live /v1/score latency readout and
// a tier badge that INCLUDES `shed` and `fail_open` -- the two states a judge
// asks about. Both demo-gated; the default checkout shows neither.
//
// Day 9 Plan Phase 3 step 6 -- `?demo=1` also gains a "Checkout as CGNAT
// co-tenant" button: it GETs /v1/demo/cotenant-ip (one IP currently under
// enforcement) then re-runs the checkout tagged so the Vite proxy -- the
// declared trusted edge -- stamps X-Forwarded-For with that IP (the browser
// cannot set XFF itself). The customer then hits the REAL (ip, ua_class)
// entity and the REAL challenge auto-ceiling: one checkbox, order goes
// through. Nothing about the decision is special-cased.
//
// Remediation plan FIX-021 (AUDIT-019) -- THE CARD FIELDS ARE REAL NOW. The
// inputs were uncontrolled `defaultValue`s that nothing ever read: `pay()` sent
// a RANDOM `card_hash` and a hardcoded `bin: "999001"` on every submit. So the
// storefront could not demonstrate card testing at all -- every attempt looked
// like a brand-new card no matter what was typed, and the one screen whose job
// is to show a real attempt was theatre.
//
// The fields are now controlled and drive the request:
//
//   bin        = first 6 digits
//   last4      = last 4 digits
//   exp_month  / exp_year from the expiry field
//   card_hash  = hex(SHA-256(digits)), computed IN THE BROWSER via
//                crypto.subtle.digest
//
// THE PAN NEVER LEAVES THE BROWSER. Only the BIN (an industry-standard,
// non-identifying issuer prefix), the last four, the expiry and an opaque
// digest are sent -- exactly the M-class fields `ScoreRequest` already accepts.
// `test_no_pan.py` and the trust boundary are unaffected. Malformed input shows
// inline validation and blocks the request; it is never silently substituted.

const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";

function digitsOf(value) {
  return (value || "").replace(/\D/g, "");
}

async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function parseExpiry(value) {
  const digits = digitsOf(value);
  if (digits.length < 4) return null;
  const month = Number(digits.slice(0, 2));
  const yearPart = digits.slice(2, digits.length >= 6 ? 6 : 4);
  const year = yearPart.length === 4 ? Number(yearPart) : 2000 + Number(yearPart);
  if (!(month >= 1 && month <= 12)) return null;
  if (!(year >= 2000 && year <= 2099)) return null;
  return { month, year };
}

export function validateCard(pan, expiry) {
  const digits = digitsOf(pan);
  if (digits.length < 12 || digits.length > 19) {
    return "Enter a card number of 12-19 digits.";
  }
  if (!parseExpiry(expiry)) {
    return "Enter an expiry as MM / YY.";
  }
  return null;
}

const inputStyle = {
  display: "block",
  width: "100%",
  padding: 10,
  marginTop: 4,
  border: "1px solid var(--st-hairline)",
  borderRadius: 6,
};

export default function S2Checkout({ demo, onRoute }) {
  const [submitting, setSubmitting] = useState(false);
  const [latencyMs, setLatencyMs] = useState(null);
  const [outcome, setOutcome] = useState(null);
  // DEF-D9-012: the `?demo=1` readout only showed `tier` (the routed outcome),
  // so a misconfigured key (`/v1/score` -> 401) rendered as `tier: fail_open`
  // and S5 "Order confirmed" -- a green check with no visible sign of the
  // failure, which cost rehearsal time to diagnose. Surface the transport
  // status here (demo-only; the plain storefront still fails open silently, per
  // TRD SS5.2). `null` code + an error -> "no response".
  const [netStatus, setNetStatus] = useState(null);
  const [pan, setPan] = useState("9990 0100 0000 0000");
  const [expiry, setExpiry] = useState("04 / 28");
  const [cvv, setCvv] = useState("123");
  const [validationError, setValidationError] = useState(null);
  const [cotenantIp, setCotenantIp] = useState(null);

  const digits = useMemo(() => digitsOf(pan), [pan]);

  async function pay(extraHeaders = {}) {
    const problem = validateCard(pan, expiry);
    if (problem) {
      setValidationError(problem);
      return;
    }
    setValidationError(null);
    setSubmitting(true);
    setOutcome(null);
    setNetStatus(null);
    const started = performance.now();
    let statusCode = null;
    let headers = null;
    let body = null;
    let error = null;
    try {
      const parsed = parseExpiry(expiry);
      // Derived here, in the browser. `digits` -- the PAN -- is used only as
      // the hash input and is never placed in the request body.
      const cardHash = await sha256Hex(digits);
      const resp = await fetch("/v1/score", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tollgate-Key": API_KEY,
          ...extraHeaders,
        },
        body: JSON.stringify({
          event_id: `evt-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          card_hash: cardHash,
          bin: digits.slice(0, 6),
          last4: digits.slice(-4),
          exp_month: parsed.month,
          exp_year: parsed.year,
          amount_minor: 120000,
          currency: "INR",
        }),
      });
      statusCode = resp.status;
      headers = resp.headers;
      body = await resp.json().catch(() => null);
    } catch (err) {
      error = err;
    }
    setLatencyMs(Math.round(performance.now() - started));
    setNetStatus(statusCode == null ? (error ? "no response" : null) : statusCode);
    const co = resolveClientOutcome({ statusCode, headers, body, error });
    setOutcome(co);
    setSubmitting(false);
    onRoute(screenForOutcome(co), co);
  }

  // Day 9 Plan Phase 3 step 6 -- the CGNAT co-tenant checkout.
  async function payAsCotenant() {
    setValidationError(null);
    let ip = null;
    try {
      const r = await fetch("/v1/demo/cotenant-ip", { headers: { "X-Tollgate-Key": API_KEY } });
      if (!r.ok) {
        setValidationError(
          r.status === 404
            ? "No IP is under enforcement yet — run the attack replay first."
            : `Co-tenant lookup failed (HTTP ${r.status}).`
        );
        return;
      }
      ip = (await r.json()).ip;
    } catch (err) {
      setValidationError("Cannot reach the scorer.");
      return;
    }
    setCotenantIp(ip);
    // The Vite proxy (the declared trusted edge) turns this into
    // X-Forwarded-For: <ip>; the browser is not allowed to set XFF itself.
    await pay({ "x-tg-demo-xff": ip });
  }

  return (
    <div style={{ maxWidth: 460, margin: "0 auto", padding: "80px 24px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 400, marginBottom: 4 }}>Checkout</h1>
      <p style={{ color: "var(--st-ink-mute)", fontSize: 13, marginTop: 0 }}>
        Kesar &amp; Co. &middot; Saffron Kurta &middot; &#8377;1,200
      </p>

      <label style={{ display: "block", fontSize: 13, color: "var(--st-ink-2)", marginTop: 20 }}>
        Card number
        <input
          value={pan}
          onChange={(e) => setPan(e.target.value)}
          inputMode="numeric"
          autoComplete="cc-number"
          style={inputStyle}
        />
      </label>
      <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
        <label style={{ flex: 1, fontSize: 13, color: "var(--st-ink-2)" }}>
          Expiry
          <input
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            inputMode="numeric"
            autoComplete="cc-exp"
            style={inputStyle}
          />
        </label>
        <label style={{ flex: 1, fontSize: 13, color: "var(--st-ink-2)" }}>
          CVV
          <input
            value={cvv}
            onChange={(e) => setCvv(e.target.value)}
            inputMode="numeric"
            autoComplete="cc-csc"
            style={inputStyle}
          />
        </label>
      </div>

      {validationError && (
        <p role="alert" style={{ color: "#B4232C", fontSize: 13, marginBottom: 0 }}>
          {validationError}
        </p>
      )}

      <button
        onClick={() => pay()}
        disabled={submitting}
        style={{
          marginTop: 20,
          width: "100%",
          background: "var(--st-accent)",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: 12,
          fontSize: 15,
          cursor: submitting ? "default" : "pointer",
        }}
      >
        {submitting ? "Processing..." : "Pay ₹1,200"}
      </button>

      {demo && (
        <div style={{ marginTop: 16, fontSize: 12, color: "var(--st-ink-mute)", fontFamily: "ui-monospace, monospace" }}>
          <span>/v1/score latency: {latencyMs == null ? "—" : `${latencyMs} ms`}</span>
          {" · "}
          <span>tier: {outcome || "—"}</span>
          {netStatus != null && netStatus !== 200 && (
            <>
              {" · "}
              <span style={{ color: "#B4232C" }}>HTTP {netStatus}</span>
            </>
          )}
          {" · "}
          <span>bin: {digits.slice(0, 6) || "—"} &middot; last4: {digits.slice(-4) || "—"}</span>
          {cotenantIp && (
            <>
              {" · "}
              <span>via co-tenant IP: {cotenantIp}</span>
            </>
          )}
          <div style={{ marginTop: 10 }}>
            <button
              type="button"
              onClick={payAsCotenant}
              disabled={submitting}
              style={{
                border: "1px solid var(--st-hairline)",
                borderRadius: 6,
                padding: "6px 12px",
                background: "transparent",
                color: "var(--st-ink-2)",
                cursor: submitting ? "default" : "pointer",
                fontFamily: "inherit",
                fontSize: 12,
              }}
              title="DEMO: fetch an IP currently under enforcement, then check out from it. The proxy stamps X-Forwarded-For; real entity resolution, real challenge ceiling."
            >
              Checkout as CGNAT co-tenant
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
