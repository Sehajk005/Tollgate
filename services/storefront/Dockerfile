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
#
# DEF-D9-011: source deploy/compose.env at container start, exactly as
# services/scorer/Dockerfile does. Compose resolves `env_file:` at
# container-CREATE time, which is before the one-shot `bootstrap` service
# regenerates deploy/compose.env with a fresh VITE_TOLLGATE_API_KEY and seeds
# the merchant row with its hash. Without this shim the frontend binds the
# previous run's key (or none on a first run) and every keyed call to the
# scorer 401s after `docker compose down -v && up`. `set -a` exports each
# KEY=VALUE so Vite picks VITE_* up from process.env.
CMD ["sh", "-c", "set -a; [ -f /repo/deploy/compose.env ] && . /repo/deploy/compose.env; set +a; exec npm run dev -- --host 0.0.0.0"]
