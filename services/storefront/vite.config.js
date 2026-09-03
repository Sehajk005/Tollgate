import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Source: Implementation Plan v2.1 Day 1 / decisions.md decision 11 -- same
// proxy pattern as services/dashboard/vite.config.js.
//
// Day 9 Plan Phase 2: the proxy target is parameterized. Unset (the README
// manual path) it stays byte-identical at http://localhost:8080; the Compose
// stack sets TOLLGATE_SCORER_URL=http://scorer:8080.
const SCORER_URL = process.env.TOLLGATE_SCORER_URL || "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: SCORER_URL,
        changeOrigin: true,
      },
    },
  },
});
