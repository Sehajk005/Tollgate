import { fileURLToPath } from "node:url";

import { mergeConfig } from "vite";
import { defineConfig } from "vitest/config";

import viteConfig from "./vite.config.js";

// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.4. Vitest reuses
// `vite.config.js` -- crucially `server.fs.allow: ["..","../.."]`, which is what
// lets the build-time `import d6 from "../../../../eval/outputs/d6.json"` resolve
// in tests EXACTLY as it does in the app (no JSON-import mock, no transform
// pipeline drift -- the gap this plan exists to close).
//
// jsdom over happy-dom: Block 4's chart tests read `<path d>` / `<circle cx>` /
// `<text x y>` attributes, and jsdom's SVG element/attribute fidelity is higher.
// jsdom does NOT lay out -- overlap / overflow / computed geometry live in
// Playwright (e2e/), never here (plan §23.3).
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: false,
      setupFiles: ["./src/test/setup.js"],
      include: ["src/**/*.test.{js,jsx}"],
      css: false,
      coverage: {
        provider: "v8",
        reporter: ["text", "text-summary"],
        include: [
          "src/lib/**",
          "src/components/metrics/**",
          "src/components/charts/**",
          "src/components/MetricsErrorBoundary.jsx",
          "src/components/LiveShell.jsx",
          "src/hooks/useHashRoute.js",
          "src/screens/D6Metrics.jsx",
        ],
        // Not part of the D6 remediation surface (§30 M-030: "coverage on D6
        // paths"): labels.js / featureLabels.js are D1/D3; BarRow.jsx is the
        // superseded shared-bar primitive, kept only until its grep tests are
        // deleted in Phase 6 (§26.2/§26.3 deviation -- the block components have
        // their own row renderers).
        exclude: [
          "src/lib/labels.js",
          "src/lib/featureLabels.js",
          "src/components/charts/BarRow.jsx",
        ],
        thresholds: { lines: 85, functions: 85, branches: 80 },
      },
    },
    resolve: {
      alias: {
        "@fixtures": fileURLToPath(new URL("./src/__fixtures__", import.meta.url)),
      },
    },
  }),
);
