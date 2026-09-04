// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §14 -- FIX-M-003/004/005/034.
//
// PURE geometry, deliberately extracted from CostCurve.jsx so it is
// unit-testable WITHOUT layout (§23.3: jsdom does not lay out). No React, no
// DOM. Every function here is exercised by costCurveGeometry.test.js
// (FE-T-GEOM-01..10) with independently derived expected values.
//
// The cost data (measured, §14.1):
//   * the decision-relevant region is FPR <= ~0.00198 -- 0.13% of a linear axis
//   * two distinct hull vertices sit at exactly FPR = 0 (the optimum really is
//     at 0) -- so markers are INSET points, never full-height rules
//   * dynamic range within curve_pi0 alone is 651x, and ~900x more against
//     curve_pi1 -- so each panel gets its own LOG y-axis (all costs are > 0,
//     so log is safe: no zero, no negative)

const EPS = 1e-9;

/** A linear scale on [d0, d1] -> [p0 + inset, p1], with a fixed pixel inset at
 *  the low end so a value at exactly d0 maps clear of the axis line. */
export function linScale(d0, d1, p0, p1, inset = 0) {
  const span = d1 - d0;
  const px = p1 - (p0 + inset);
  return (v) => {
    if (Math.abs(span) < EPS) return p0 + inset;
    return p0 + inset + ((v - d0) / span) * px;
  };
}

/** A base-10 log scale on [c0, c1] (both > 0, c0 < c1) -> [pBottom, pTop].
 *  c0 maps to pBottom, c1 to pTop (SVG y grows downward). */
export function logScale(c0, c1, pBottom, pTop) {
  const l0 = Math.log10(c0);
  const l1 = Math.log10(c1);
  const span = l1 - l0;
  return (v) => {
    if (v <= 0 || span < EPS) return pBottom;
    return pBottom + ((Math.log10(v) - l0) / span) * (pTop - pBottom);
  };
}

/** Decade tick values (powers of 10) lying within [c0, c1]. */
export function decadeTicks(c0, c1) {
  const out = [];
  const start = Math.floor(Math.log10(c0));
  const end = Math.ceil(Math.log10(c1));
  for (let e = start; e <= end; e += 1) {
    const t = 10 ** e;
    if (t >= c0 * 0.999 && t <= c1 * 1.001) out.push(t);
  }
  return out;
}

/** 1-2-5 mantissa ticks within [c0, c1] -- so a narrow log window (Panel A,
 *  where no power of 10 falls inside) still gets labelled gridlines. */
export function niceLogTicks(c0, c1) {
  const out = [];
  const start = Math.floor(Math.log10(c0));
  const end = Math.ceil(Math.log10(c1));
  for (let e = start; e <= end; e += 1) {
    for (const mant of [1, 2, 5]) {
      const t = mant * 10 ** e;
      if (t >= c0 * 0.999 && t <= c1 * 1.001) out.push(t);
    }
  }
  return out;
}

/**
 * Build one panel's pixel geometry from a hull curve.
 *
 * @param {Array<[fpr, tpr, cost]>} curve
 * @param {[number, number]} xDomain
 * @param {[number, number]} yDomain      cost domain, log-scaled; [min, max], > 0
 * @param {{width, height, margin:{top,right,bottom,left}, xInset}} size
 * @returns {{ x, y, linePath, points, yTicks, plot:{left,right,top,bottom} }}
 */
export function buildPanelGeometry(curve, xDomain, yDomain, size) {
  const { width, height, margin: m, xInset = 8 } = size;
  const left = m.left;
  const right = width - m.right;
  const top = m.top;
  const bottom = height - m.bottom;

  const x = linScale(xDomain[0], xDomain[1], left, right, xInset);
  const y = logScale(yDomain[0], yDomain[1], bottom, top);

  const visible = curve.filter((p) => p[0] >= xDomain[0] - EPS && p[0] <= xDomain[1] + EPS);
  const points = visible.map((p) => ({ fpr: p[0], tpr: p[1], cost: p[2], px: x(p[0]), py: y(p[2]) }));
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.px},${p.py}`)
    .join(" ");

  return {
    x,
    y,
    linePath,
    points,
    yTicks: niceLogTicks(yDomain[0], yDomain[1]).map((t) => ({ value: t, py: y(t) })),
    plot: { left, right, top, bottom },
  };
}

/** A cost domain padded by `padDecades` in log space, from a set of costs. */
export function costDomain(costs, padDecades = 0.15) {
  const positive = costs.filter((c) => typeof c === "number" && c > 0);
  const lo = Math.min(...positive);
  const hi = Math.max(...positive);
  return [10 ** (Math.log10(lo) - padDecades), 10 ** (Math.log10(hi) + padDecades)];
}

/**
 * Per-x min/max envelope across every ribbon prevalence.
 * Accepts EITHER the pre-computed `[[fpr, lo, hi], ...]` (returned after a
 * validity clamp) OR the raw `[{pi, curve:[[fpr,tpr,cost],...]}, ...]` form
 * (from which the envelope is computed). A crossing-curve input still yields a
 * valid, non-crossing envelope BY CONSTRUCTION (per-index min/max).
 *
 * @returns {Array<[fpr, lo, hi]>}  with hi >= lo at every index
 */
export function ribbonEnvelope(ribbon) {
  if (!Array.isArray(ribbon) || ribbon.length === 0) return [];

  if (Array.isArray(ribbon[0]) && ribbon[0].length === 3 && typeof ribbon[0][0] === "number") {
    return ribbon.map(([fpr, a, b]) => [fpr, Math.min(a, b), Math.max(a, b)]);
  }

  const curves = ribbon.map((r) => r.curve);
  const n = Math.min(...curves.map((c) => c.length));
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const fpr = curves[0][i][0];
    const costs = curves.map((c) => c[i][2]);
    out.push([fpr, Math.min(...costs), Math.max(...costs)]);
  }
  return out;
}

/**
 * The closed ribbon polygon path: forward along `lo`, reverse along `hi`, Z.
 * Because the envelope's x is monotone non-decreasing and hi >= lo at every
 * index, this polygon is simple.
 */
export function ribbonPath(envelope, x, y) {
  if (!envelope || envelope.length === 0) return "";
  const fwd = envelope
    .map(([fpr, lo], i) => `${i === 0 ? "M" : "L"}${x(fpr)},${y(lo)}`)
    .join(" ");
  const rev = [...envelope]
    .reverse()
    .map(([fpr, , hi]) => `L${x(fpr)},${y(hi)}`)
    .join(" ");
  return `${fwd} ${rev} Z`;
}

// ---- segment intersection (for the "polygon is simple" test) ---------------

function orient(a, b, c) {
  const v = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]);
  if (Math.abs(v) < 1e-9) return 0;
  return v > 0 ? 1 : 2;
}

function onSeg(a, b, c) {
  return (
    Math.min(a[0], c[0]) - 1e-9 <= b[0] &&
    b[0] <= Math.max(a[0], c[0]) + 1e-9 &&
    Math.min(a[1], c[1]) - 1e-9 <= b[1] &&
    b[1] <= Math.max(a[1], c[1]) + 1e-9
  );
}

/** Proper-or-collinear segment intersection. */
export function segmentsIntersect(p1, p2, p3, p4) {
  const o1 = orient(p1, p2, p3);
  const o2 = orient(p1, p2, p4);
  const o3 = orient(p3, p4, p1);
  const o4 = orient(p3, p4, p2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSeg(p1, p3, p2)) return true;
  if (o2 === 0 && onSeg(p1, p4, p2)) return true;
  if (o3 === 0 && onSeg(p3, p1, p4)) return true;
  if (o4 === 0 && onSeg(p3, p2, p4)) return true;
  return false;
}

/** TRANSVERSAL crossing only: the two open segments cross at a single interior
 *  point. Shared endpoints and collinear overlap do NOT count -- those are
 *  boundary features of a valid fill (the ribbon's left edge is a vertical
 *  segment because two hull vertices share FPR = 0), not a bowtie. */
export function properSegmentsCross(p1, p2, p3, p4) {
  const o1 = orient(p1, p2, p3);
  const o2 = orient(p1, p2, p4);
  const o3 = orient(p3, p4, p1);
  const o4 = orient(p3, p4, p2);
  return o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0 && o1 !== o2 && o3 !== o4;
}

/** Parse an `M x,y L x,y ... Z` path into a point array. */
export function parsePathPoints(d) {
  return (d.match(/-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?/g) || []).map((pair) => {
    const [a, b] = pair.split(",").map(Number);
    return [a, b];
  });
}

/**
 * True if the closed polygon described by `d` has a pair of NON-ADJACENT edges
 * that TRANSVERSALLY cross -- a bowtie. Adjacent edges, shared endpoints and
 * collinear boundary overlap are excluded: those are legitimate features of a
 * valid ribbon fill (its left edge is a vertical segment because two hull
 * vertices share FPR = 0), not a self-intersection.
 */
export function pathHasSelfIntersection(d) {
  const pts = parsePathPoints(d);
  if (pts.length < 4) return false;
  const n = pts.length;
  const edges = [];
  for (let i = 0; i < n; i += 1) edges.push([pts[i], pts[(i + 1) % n]]);
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 1; j < n; j += 1) {
      if (j === i || j === (i + 1) % n || i === (j + 1) % n) continue; // adjacent
      if (properSegmentsCross(edges[i][0], edges[i][1], edges[j][0], edges[j][1])) return true;
    }
  }
  return false;
}

// ---- marker layout (collision-avoided callouts) ---------------------------

/**
 * Place callout boxes for optimum markers so they never overlap.
 *
 * @param {Array<{id, cx, cy, lines:string[]}>} markers
 * @param {{ calloutW?, lineH?, gap?, plotTop?, plotBottom?, plotLeft?, plotRight?, mergeEps? }} opts
 * @returns {Array<{id, cx, cy, lines, anchor:"start"|"end", callout:{x,y}, box:{x,y,w,h}}>}
 *
 * Markers whose (cx, cy) coincide within `mergeEps` are collapsed to ONE
 * (their lines concatenated). Remaining callouts are stacked downward from
 * their natural y so no two boxes intersect. A callout that would overflow
 * `plotRight` is flipped to the LEFT of its marker (anchor "end"); one that
 * would then overflow `plotLeft` is clamped inside.
 */
export function markerLayout(markers, opts = {}) {
  const {
    calloutW = 150,
    lineH = 12,
    gap = 6,
    plotTop = 0,
    plotBottom = 10000,
    plotLeft = -Infinity,
    plotRight = Infinity,
    mergeEps = 2,
  } = opts;

  const merged = [];
  for (const m of markers) {
    const hit = merged.find(
      (x) => Math.abs(x.cx - m.cx) <= mergeEps && Math.abs(x.cy - m.cy) <= mergeEps,
    );
    if (hit) {
      for (const line of m.lines) if (!hit.lines.includes(line)) hit.lines.push(line);
    } else {
      merged.push({ ...m, lines: [...m.lines] });
    }
  }

  merged.sort((a, b) => a.cy - b.cy);
  let cursor = plotTop;
  return merged.map((m) => {
    const h = m.lines.length * lineH + 4;
    let y = Math.max(m.cy - h / 2, cursor);
    if (y + h > plotBottom) y = plotBottom - h;
    y = Math.max(y, cursor);
    cursor = y + h + gap;

    // default: callout to the right of the marker
    let anchor = "start";
    let textX = m.cx + 10;
    let boxX = m.cx + 10;
    if (boxX + calloutW > plotRight) {
      // flip left of the marker
      anchor = "end";
      textX = m.cx - 10;
      boxX = m.cx - 10 - calloutW;
      if (boxX < plotLeft) {
        // clamp inside; text stays right-anchored at the box's right edge
        boxX = plotLeft;
        textX = plotLeft + calloutW;
      }
    }

    return {
      ...m,
      anchor,
      callout: { x: textX, y: y + lineH },
      box: { x: boxX, y, w: calloutW, h },
    };
  });
}

/** True if two axis-aligned boxes overlap (strictly). */
export function boxesOverlap(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}
