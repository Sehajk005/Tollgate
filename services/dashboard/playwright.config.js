import { defineConfig, devices } from "@playwright/test";

// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §22.3 / §25. Playwright is the
// ONLY tool that can verify the responsive + visual-geometry half of the
// acceptance gate (jsdom does not lay out). Four viewport projects; every
// assertion is a computed value, never a screenshot diff.
const VIEWPORTS = [
  { name: "desktop-1536", width: 1536, height: 960 },
  { name: "laptop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
];

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: "http://localhost:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: VIEWPORTS.map((vp) => ({
    name: vp.name,
    use: { ...devices["Desktop Chrome"], viewport: { width: vp.width, height: vp.height } },
  })),
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
