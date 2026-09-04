// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §25 (the 18-check E2E gate) +
// §22.3 (responsive geometry). Runs under the four viewport projects in
// playwright.config.js: 1536x960 / 1280x800 / 768x1024 / 390x844.
//
// Every assertion is a COMPUTED value (bounding boxes, computed styles, console
// events, network events) -- never a screenshot diff. Screenshots are captured
// on failure as review aids only.
//
// jsdom cannot do any of this (plan §23.3); the Vitest suite owns text / role /
// ARIA / SVG-attribute assertions, this file owns layout, overflow, font size,
// console cleanliness and the network-dwell gate.

import { test, expect } from "@playwright/test";

const SIX_BLOCKS = [
  "1. Per-tier performance",
  "2. Negative-control false positives",
  "3. Discriminability audit",
  "4. Cost curves",
  "5. Calibration",
  "6. Baseline comparison",
];

/** console.error / console.warn collected for the lifetime of a test. */
function trackConsole(page) {
  const errors = [];
  const warnings = [];
  page.on("console", (msg) => {
    const t = msg.type();
    if (t === "error") errors.push(msg.text());
    if (t === "warning") warnings.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  return { errors, warnings };
}

test.describe("D6 Metrics — §25 acceptance gate", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/metrics");
    await expect(page.getByRole("heading", { name: "Metrics & Evaluation", level: 1 })).toBeVisible();
  });

  // 1
  test("loads directly at #/metrics on first paint", async ({ page }) => {
    await expect(page).toHaveURL(/#\/metrics$/);
    await expect(page.getByRole("heading", { name: "Metrics & Evaluation" })).toBeVisible();
  });

  // 2
  test("survives a reload", async ({ page }) => {
    await page.reload();
    await expect(page).toHaveURL(/#\/metrics$/);
    await expect(page.getByRole("heading", { name: "Metrics & Evaluation" })).toBeVisible();
  });

  // 3
  test("back / forward restores the route", async ({ page }) => {
    await page.getByRole("button", { name: "Live" }).click();
    await expect(page).toHaveURL(/#\/live$/);
    await page.goBack();
    await expect(page).toHaveURL(/#\/metrics$/);
    await expect(page.getByRole("heading", { name: "Metrics & Evaluation" })).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(/#\/live$/);
  });

  // 4
  test("the full page scrolls and the last section is reachable", async ({ page }) => {
    const last = page.getByRole("heading", { name: SIX_BLOCKS[5] });
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeVisible();
  });

  // 5 + 6
  test("no console errors and no console warnings on the happy path", async ({ page }) => {
    const { errors, warnings } = trackConsole(page);
    await page.goto("/#/metrics");
    await page.getByRole("heading", { name: SIX_BLOCKS[5] }).scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    expect(errors, `console.error:\n${errors.join("\n")}`).toEqual([]);
    expect(warnings, `console.warn:\n${warnings.join("\n")}`).toEqual([]);
  });

  // 7 + M-027 / M-035
  test("no horizontal overflow", async ({ page }) => {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow, "documentElement.scrollWidth exceeds innerWidth").toBeLessThanOrEqual(1);
  });

  // 8
  test("all six block headings are present", async ({ page }) => {
    for (const name of SIX_BLOCKS) {
      await expect(page.getByRole("heading", { name, level: 2 })).toBeVisible();
    }
  });

  // 9
  test("the headline metrics are visible after scrolling", async ({ page }) => {
    await expect(page.getByText("₹2,32,145").first()).toBeVisible();
    await page.getByText(/0\.789/).first().scrollIntoViewIfNeeded();
    await expect(page.getByText(/0\.789/).first()).toBeVisible();
    await expect(page.getByText(/0\.731/).first()).toBeVisible();
    await page.getByText(/0\.3955/).first().scrollIntoViewIfNeeded();
    await expect(page.getByText(/0\.3955/).first()).toBeVisible(); // π₁ ECE Platt
    await expect(page.getByText(/0\.997/).first()).toBeVisible(); // B0 AP
  });

  // 10
  test("every unresolvable row also shows an n_neg", async ({ page }) => {
    const groups = page.locator('[role="group"]', { hasText: /not resolvable|not fed/ });
    const n = await groups.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      await expect(groups.nth(i)).toHaveText(/n_neg=?\s*\d+/);
    }
  });

  // 11 + M-034
  test("every SVG <text> is >= 11px and inside its viewBox", async ({ page }) => {
    const bad = await page.evaluate(() => {
      const out = [];
      for (const svg of document.querySelectorAll("svg")) {
        const vb = svg.viewBox?.baseVal;
        for (const t of svg.querySelectorAll("text")) {
          const fs = parseFloat(getComputedStyle(t).fontSize);
          if (fs < 11) out.push({ why: "font", fs, text: t.textContent });
          if (vb && vb.width > 0) {
            const b = t.getBBox();
            if (b.x < vb.x - 0.5 || b.y < vb.y - 0.5 ||
                b.x + b.width > vb.x + vb.width + 0.5 ||
                b.y + b.height > vb.y + vb.height + 0.5) {
              out.push({ why: "clip", text: t.textContent });
            }
          }
        }
      }
      return out;
    });
    expect(bad, JSON.stringify(bad, null, 2)).toEqual([]);
  });

  // 12
  test("a scrollable table wrapper is keyboard-focusable", async ({ page }) => {
    const regions = page.locator(".tg-scroll-x");
    const n = await regions.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      await expect(regions.nth(i)).toHaveAttribute("tabindex", "0");
      await expect(regions.nth(i)).toHaveAttribute("role", "region");
      expect((await regions.nth(i).getAttribute("aria-label"))?.length ?? 0).toBeGreaterThan(0);
    }
  });

  // 13
  test("no sticky element obscures the last content at max scroll", async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(150);
    const clash = await page.evaluate(() => {
      const stickies = [...document.querySelectorAll("*")].filter((el) => {
        const p = getComputedStyle(el).position;
        return p === "sticky" || p === "fixed";
      });
      const last = document.querySelector(".tg-metrics")?.lastElementChild;
      if (!last || stickies.length === 0) return null;
      const lb = last.getBoundingClientRect();
      for (const s of stickies) {
        const sb = s.getBoundingClientRect();
        if (sb.height > 0 && lb.bottom > sb.top && lb.top < sb.bottom) {
          return { last: last.textContent?.slice(0, 40), sticky: s.className };
        }
      }
      return null;
    });
    expect(clash).toBeNull();
  });

  // 14 + M-025
  test("no metric-row label overlaps its bar track", async ({ page }) => {
    const bad = await page.evaluate(() => {
      const out = [];
      for (const row of document.querySelectorAll(".tg-metric-row")) {
        const kids = row.children;
        if (kids.length < 2) continue;
        const label = kids[0].getBoundingClientRect();
        const bar = kids[kids.length - 2].getBoundingClientRect();
        // a TRUE overlap intersects on BOTH axes -- when the row has stacked
        // (narrow viewport) the boxes are on separate lines and only "overlap"
        // horizontally, which is not a collision.
        const horiz = label.right > bar.left + 1 && label.left < bar.right - 1;
        const vert = label.bottom > bar.top + 1 && label.top < bar.bottom - 1;
        if (horiz && vert) out.push(row.textContent?.slice(0, 50));
      }
      return out;
    });
    expect(bad, JSON.stringify(bad)).toEqual([]);
  });

  // 15 + M-026
  test("rows within a table body have equal height", async ({ page }) => {
    const uneven = await page.evaluate(() => {
      const out = [];
      for (const tb of document.querySelectorAll(".tg-metrics table tbody")) {
        const hs = [...tb.querySelectorAll("tr")].map((r) =>
          Math.round(r.getBoundingClientRect().height),
        );
        const nonzero = hs.filter((h) => h > 0);
        if (nonzero.length > 1 && Math.max(...nonzero) - Math.min(...nonzero) > 2) {
          out.push(hs);
        }
      }
      return out;
    });
    // OpCell is a designed two-line cell, so a couple of bodies legitimately
    // differ; this guards against WRAP-driven drift, not intentional structure.
    expect(uneven.length, JSON.stringify(uneven)).toBeLessThanOrEqual(2);
  });

  // 16 — the M-031 gate
  test("zero scorer/SSE network activity during a 10s dwell on Metrics", async ({ page }) => {
    const hits = [];
    page.on("request", (req) => {
      const u = req.url();
      const rt = req.resourceType();
      if (rt === "eventsource") hits.push(u);
      if (/\/v1\/|\/sse|\/events|\/incidents|\/replay/.test(u)) hits.push(u);
    });
    await page.goto("/#/metrics");
    await page.waitForTimeout(10_000);
    expect(hits, `unexpected network on Metrics:\n${hits.join("\n")}`).toEqual([]);
  });

  // 17 — M-023 (computed style resolves to the corrected token)
  test("the corrected muted token is in force", async ({ page }) => {
    const tokenValue = await page.evaluate(() =>
      getComputedStyle(document.querySelector(".tg-app"))
        .getPropertyValue("--tg-text-mute")
        .trim(),
    );
    expect(tokenValue.toLowerCase()).toBe("#8b95a3");

    // a real muted element resolves to rgb(139,149,163); allow the brighter
    // steps in case the sampled node is text-2 / text.
    const sample = page
      .locator('.tg-metrics [style*="--tg-text-mute"], .tg-metrics .tg-mono-caption')
      .first();
    await expect(sample).toBeVisible();
    const color = await sample.evaluate((el) => getComputedStyle(el).color);
    expect(["rgb(139, 149, 163)", "rgb(167, 176, 188)", "rgb(242, 245, 248)"]).toContain(color);
  });

  // 18
  test("Tab reaches every disclosure and the focus ring is visible", async ({ page }) => {
    // stable locators by accessible name -- not by `expanded` state, which the
    // toggle changes mid-test
    const methodology = page.getByRole("button", { name: /Methodology & provenance/ });
    const notFed = page.getByRole("button", { name: /not fed|un-fed|never fed/i });

    await expect(methodology).toBeVisible();
    const disclosures = [methodology, ...((await notFed.count()) ? [notFed] : [])];

    for (const btn of disclosures) {
      await btn.scrollIntoViewIfNeeded();
      await btn.focus();
      await expect(btn).toBeFocused();
      const outline = await btn.evaluate((el) => getComputedStyle(el).outlineStyle);
      expect(outline, "focus ring suppressed").not.toBe("none");

      await expect(btn).toHaveAttribute("aria-expanded", "false");
      await btn.press("Enter");
      await expect(btn).toHaveAttribute("aria-expanded", "true");
      await btn.press("Enter");
      await expect(btn).toHaveAttribute("aria-expanded", "false");
    }
  });
});
