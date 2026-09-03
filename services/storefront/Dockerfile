# Source: Day 9 Plan Phase 2. Runs the storefront Vite dev server (:5173).
# Same pattern as services/dashboard/Dockerfile -- see the notes there.
# Build context is the repo root (compose `context: .`).

FROM node:22-bookworm-slim

WORKDIR /repo/services/storefront

COPY services/storefront/package.json services/storefront/package-lock.json ./
RUN npm ci

EXPOSE 5173

# --host 0.0.0.0 (Plan Phase 2). vite.config.js reads TOLLGATE_SCORER_URL for
# the /v1 proxy target (default http://localhost:8080); compose sets
# http://scorer:8080.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
