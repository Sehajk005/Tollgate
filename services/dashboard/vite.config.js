import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Source: Implementation Plan v2.1 Day 1 / decisions.md decision 11 -- the
// dev-server proxy makes browser -> :5174 -> :8080 same-origin, and
// genuinely surfaces SSE-through-proxy behavior. CORS middleware is also
// enabled on the scorer (services/scorer/app.py) so the cross-origin path
// stays independently testable.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/v1": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
