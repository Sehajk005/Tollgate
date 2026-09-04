import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Source: Implementation Plan v2.1 Day 1 / decisions.md decision 11 -- same
// proxy pattern as services/dashboard/vite.config.js.
//
// Day 9 Plan Phase 2: the proxy target is parameterized. Unset (the README
// manual path) it stays byte-identical at http://localhost:8080; the Compose
// stack sets TOLLGATE_SCORER_URL=http://scorer:8080.
const SCORER_URL = process.env.TOLLGATE_SCORER_URL || "http://localhost:8080";

// Day 9 Plan Phase 3 step 6: this Vite proxy IS the merchant's declared trusted
// edge (its container IP is in the scorer's TOLLGATE_TRUSTED_EDGE_HOSTS). The
// browser cannot set X-Forwarded-For, so the demo "co-tenant checkout" button
// sends `x-tg-demo-xff: <ip>` and -- only when TOLLGATE_DEMO_CONTROLS is on --
// the proxy promotes it to X-Forwarded-For. Off the demo path this hook is
// inert and the proxy is byte-identical to before.
const DEMO_CONTROLS = ["1", "true", "yes", "on"].includes(
  String(process.env.TOLLGATE_DEMO_CONTROLS || "").toLowerCase()
);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: SCORER_URL,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            if (!DEMO_CONTROLS) return;
            const xff = req.headers["x-tg-demo-xff"];
            if (xff) {
              proxyReq.setHeader("X-Forwarded-For", xff);
              proxyReq.removeHeader("x-tg-demo-xff");
            }
          });
        },
      },
    },
  },
});
