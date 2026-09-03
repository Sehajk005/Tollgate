# Source: Day 9 Plan Phase 2. Runs the dashboard Vite dev server (:5174).
#
# The repo is bind-mounted at /repo at runtime: D6Metrics.jsx build-time
# `import`s eval/outputs/d6.json from the repo root and vite.config.js sets
# `fs.allow: ["..", "../.."]`, so the whole tree must be visible, not just this
# app. node_modules is the one path that must NOT come from the (Windows) host
# bind mount -- a named volume masks it and is seeded from this image's
# `npm ci` output.
#
# Build context is the repo root (compose `context: .`) so the COPY paths
# below resolve; .dockerignore keeps the context small.

FROM node:22-bookworm-slim

WORKDIR /repo/services/dashboard

COPY services/dashboard/package.json services/dashboard/package-lock.json ./
RUN npm ci

EXPOSE 5174

# --host 0.0.0.0 so the port is reachable from outside the container
# (Plan Phase 2). Proxy target is read from TOLLGATE_SCORER_URL by
# vite.config.js (default http://localhost:8080 keeps the manual path
# byte-identical); compose sets it to http://scorer:8080.
#
# DEF-D9-011: source deploy/compose.env at container start, exactly as
# services/scorer/Dockerfile does. Compose resolves `env_file:` at
# container-CREATE time, which is before the one-shot `bootstrap` service
# regenerates deploy/compose.env with a fresh VITE_TOLLGATE_API_KEY and seeds
# the merchant row with its hash. Without this shim the dashboard binds the
# previous run's key (or none on a first run) and every keyed call (Launch /
# Stop / Reset, incidents) 401s after `docker compose down -v && up`. `set -a`
# exports each KEY=VALUE so Vite picks VITE_* up from process.env.
CMD ["sh", "-c", "set -a; [ -f /repo/deploy/compose.env ] && . /repo/deploy/compose.env; set +a; exec npm run dev -- --host 0.0.0.0"]
