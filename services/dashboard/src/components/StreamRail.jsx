import { useEffect, useRef } from "react";
import { TIER_TOKENS } from "../lib/labels.js";

// Day 8, Step 3 -- the Stream Rail (UIUX v2 SS5). A 28px band directly under
// the nav, on EVERY dashboard screen, rendering the live authorisation stream
// as one tick per scored attempt, scrolling right to left, coloured by
// decision tier.
//
// Two degraded marks (UIUX v2 SS5.1) -- an unscored attempt must never render
// as a confident tier:
//   fully scored -> solid tick, tier-coloured
//   shed         -> HOLLOW tick: outline in --tg-text-mute, no fill
//   fail_open    -> a GAP: --tg-canvas + a 1px --tg-system-edge stub
//
// Under `prefers-reduced-motion: reduce` it renders a STATIC snapshot and
// never schedules a frame (UIUX v2 SS7). Pinned by
// tests/acceptance/test_ui_reduced_motion.py.
//
// Remediation plan FIX-017 (AUDIT-016) -- SIZING. `canvas.width` was set once,
// in an effect with an empty dependency array, from whatever `clientWidth`
// happened to be at first paint; the pitch was a fixed 2px tick + 2px gap. So
// the 200-event buffer could only ever cover 800 CSS pixels: on a 1536px
// viewport the rail was 52% empty, and a resize stretched the bitmap instead of
// repainting it. Three changes:
//
//   * a ResizeObserver repaints on every size change, in both motion modes;
//   * the backing store is scaled by devicePixelRatio, so ticks are crisp on a
//     HiDPI display instead of interpolated;
//   * the pitch is derived from the width, so the buffer spans the canvas at
//     any viewport.

const RAIL_HEIGHT = 28;
const TICK_W = 2;
const MIN_PITCH = 3;
const SPEED_PX_PER_MS = 0.03; // right-to-left drift

function cssVar(name, fallback) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name);
  return (v && v.trim()) || fallback;
}

function markFor(evt) {
  const a = evt && evt.availability;
  if (a && a.fail_open) return { kind: "gap" };
  if (a && a.shed) return { kind: "hollow" };
  const token = TIER_TOKENS[evt && evt.decision] || "--tg-calm";
  return { kind: "solid", token };
}

// FIX-017: the buffer must span the canvas. `pitch` is the centre-to-centre
// distance between ticks, floored at MIN_PITCH so a tick is never sub-pixel.
export function tickPitch(width, count) {
  if (!count || count <= 0) return MIN_PITCH;
  return Math.max(MIN_PITCH, width / count);
}

function paint(ctx, width, events, offset) {
  ctx.clearRect(0, 0, width, RAIL_HEIGHT);
  const edge = cssVar("--tg-system-edge", "#38424F");
  const mute = cssVar("--tg-text-mute", "#6E7885");
  const pitch = tickPitch(width, events.length);
  // newest on the right, marching left
  for (let i = 0; i < events.length; i += 1) {
    const x = width - offset - i * pitch;
    if (x < -TICK_W) break;
    const m = markFor(events[i]);
    if (m.kind === "gap") {
      ctx.fillStyle = edge;
      ctx.fillRect(x, RAIL_HEIGHT - 1, TICK_W, 1); // 1px baseline stub only
    } else if (m.kind === "hollow") {
      ctx.strokeStyle = mute;
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 0.5, 6.5, TICK_W - 1, RAIL_HEIGHT - 13);
    } else {
      ctx.fillStyle = cssVar(m.token, "#6E7885");
      ctx.fillRect(x, 4, TICK_W, RAIL_HEIGHT - 8);
    }
  }
}

export default function StreamRail({ events = [] }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const startRef = useRef(null);
  const widthRef = useRef(0);
  const eventsRef = useRef(events);
  eventsRef.current = events;

  // Size the backing store to the CSS box x devicePixelRatio and scale the
  // context to match, so one canvas unit is one CSS pixel at any DPR.
  function resize(canvas) {
    const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
    const width = Math.max(1, Math.round(canvas.clientWidth || 800));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(RAIL_HEIGHT * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    widthRef.current = width;
    return ctx;
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let ctx = resize(canvas);

    // Repaint on every size change, in BOTH motion modes -- a resize that only
    // stretches the bitmap is exactly the defect being fixed.
    let observer = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => {
        ctx = resize(canvas);
        if (reduce) paint(ctx, widthRef.current, eventsRef.current, 0);
      });
      observer.observe(canvas);
    }

    if (reduce) {
      // Static snapshot -- no animation frame is ever scheduled.
      paint(ctx, widthRef.current, eventsRef.current, 0);
      return () => {
        if (observer) observer.disconnect();
      };
    }

    function frame(ts) {
      if (startRef.current == null) startRef.current = ts;
      const pitch = tickPitch(widthRef.current, eventsRef.current.length);
      const offset = ((ts - startRef.current) * SPEED_PX_PER_MS) % pitch;
      paint(ctx, widthRef.current, eventsRef.current, offset);
      rafRef.current = requestAnimationFrame(frame);
    }
    rafRef.current = requestAnimationFrame(frame);
    return () => {
      if (observer) observer.disconnect();
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      startRef.current = null;
    };
  }, []);

  // Repaint immediately on new data when motion is reduced (no rAF running).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) paint(canvas.getContext("2d"), widthRef.current || canvas.clientWidth, events, 0);
  }, [events]);

  return (
    <canvas
      ref={canvasRef}
      aria-label="live authorisation stream"
      style={{
        display: "block",
        width: "100%",
        height: RAIL_HEIGHT,
        background: "var(--tg-canvas)",
        borderBottom: "1px solid var(--tg-hairline)",
      }}
    />
  );
}
