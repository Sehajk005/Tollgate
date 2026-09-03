import { execFileSync } from "node:child_process";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// METRICS-REMEDIATION-PLAN-2026-09-02.md §17.2 -- inject the CURRENT working
// tree's config_hash at build time so the Metrics page can honestly disclose
// whether the committed evaluation snapshot is stale. The single source of
// truth is `eval.provenance.config_hash()` -- we shell out to it rather than
// reimplement the domain-separated YAML hash in JS (which would drift). On any
// failure (a bare production build with no Python) the value is null and the
// page renders "freshness not verifiable in this build" -- never a false
// "current".
function currentConfigHash() {
  // Day 9 Plan Phase 2 ("D6 freshness under Docker"): a node image has no
  // Python, so the shell-out below returns null and D6 would silently degrade
  // to "freshness not verifiable". The Compose `bootstrap` service computes the
  // same eval.provenance.config_hash() and passes it as TG_CONFIG_HASH; honour
  // it first. The manual path (no TG_CONFIG_HASH) is unchanged.
  const injected = (process.env.TG_CONFIG_HASH || "").trim();
  if (/^[0-9a-f]{64}$/.test(injected)) return injected;
  try {
    const out = execFileSync(
      "python",
      ["-c", "from eval.provenance import config_hash; print(config_hash())"],
      { cwd: "../..", encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
    return /^[0-9a-f]{64}$/.test(out) ? out : null;
  } catch {
    return null;
  }
}

// Source: Implementation Plan v2.1 Day 1 / decisions.md decision 11 -- the
// dev-server proxy makes browser -> :5174 -> :8080 same-origin, and
// genuinely surfaces SSE-through-proxy behavior. CORS middleware is also
// enabled on the scorer (services/scorer/app.py) so the cross-origin path
// stays independently testable.
export default defineConfig({
  define: {
    __TG_CONFIG_HASH__: JSON.stringify(currentConfigHash()),
  },
  plugins: [react()],
  server: {
    port: 5174,
    // Day 8, Step 4 -- D6Metrics.jsx build-time `import`s eval/outputs/d6.json
    // from the repo root, above this app's own directory. No fetch, no runtime
    // data path (App Flow v2 SS5 D6: "Static render. No live computation").
    fs: { allow: ["..", "../.."] },
    proxy: {
      "/v1": {
        // Day 9 Plan Phase 2: parameterized. Unset (README manual path) stays
        // byte-identical; Compose sets TOLLGATE_SCORER_URL=http://scorer:8080.
        target: process.env.TOLLGATE_SCORER_URL || "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
