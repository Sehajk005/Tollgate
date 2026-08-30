import { useEffect, useRef } from "react";
import { TIER_TOKENS } from "../lib/labels.js";

// Day 8, Step 3 -- the Stream Rail (UIUX v2 SS5). A 28px band directly under
// the nav, on EVERY dashboard screen, rendering the live authorisation stream
// as one 2px tick per scored attempt, scrolling right to left, coloured by
// decision tier.
//
// Two degraded marks (UIUX v2 SS5.1) -- an unscored attempt must never render
// as a confident tier:
//   fully scored -> solid 2px tick, tier-coloured
//   shed         -> HOLLOW tick: 2px outline in --tg-text-mute, no fill
//   fail_open    -> a GAP: 2px of --tg-canvas + a 1px --tg-system-edge stub
//
// Under `prefers-reduced-motion: reduce` it renders a STATIC snapshot and
// never schedules a frame (UIUX v2 SS7). Pinned by
// tests/acceptance/test_ui_reduced_motion.py.

const RAIL_HEIGHT = 28;
const TICK_W = 2;
const GAP = 2;
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

function paint(ctx, width, events, offset) {
  ctx.clearRect(0, 0, width, RAIL_HEIGHT);
  const edge = cssVar("--tg-system-edge", "#38424F");
  const mute = cssVar("--tg-text-mute", "#6E7885");
  // newest on the right, marching left
  for (let i = 0; i < events.length; i += 1) {
    const x = width - offset - i * (TICK_W + GAP);
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
  const eventsRef = useRef(events);
  eventsRef.current = events;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    const width = canvas.clientWidth || 800;
    canvas.width = width;
    canvas.height = RAIL_HEIGHT;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce) {
      // Static snapshot -- no animation frame is ever scheduled.
      paint(ctx, width, eventsRef.current, 0);
      return undefined;
    }

    function frame(ts) {
      if (startRef.current == null) startRef.current = ts;
      const offset = ((ts - startRef.current) * SPEED_PX_PER_MS) % (TICK_W + GAP);
      paint(ctx, width, eventsRef.current, offset);
      rafRef.current = requestAnimationFrame(frame);
    }
    rafRef.current = requestAnimationFrame(frame);
    return () => {
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
    if (reduce) paint(canvas.getContext("2d"), canvas.width, events, 0);
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
