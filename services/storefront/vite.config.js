import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Source: Implementation Plan v2.1 Day 1 / decisions.md decision 11 -- same
// proxy pattern as services/dashboard/vite.config.js.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
