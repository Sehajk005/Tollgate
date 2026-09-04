# Source: Day 9 Plan Phase 2 (reconciliation R-1) -- the TRD's stated
# `docker compose up` deployment path did not exist. This image runs the
# FastAPI scorer.
#
# Design (Plan Phase 2 table):
#   - Dependencies are installed into the image's SYSTEM site-packages, NOT a
#     venv. The repo is bind-mounted at /repo at runtime for dev-parity, and a
#     venv there would be shadowed by the host's Windows .venv. `models/`,
#     `config/`, `tollgate.db`, `spool/`, `data/corpus/` all arrive via that
#     bind mount and stay host-side (the LightGBM corpus is 18 MB and
#     gitignored -- a self-contained image cannot rebuild it).
#   - No source is COPYed in; only pyproject.toml / uv.lock, so the dependency
#     layer caches independently of code edits.

FROM python:3.13-slim-bookworm

# libgomp1: OpenMP runtime required by the LightGBM manylinux wheel
# (packages/detect/model.py imports lightgbm lazily inside load()).
# curl: scorer healthcheck hits /healthz.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /bin/uv

# Runtime dependency closure of services/scorer + packages/ (verified by an
# import scan in Day 9 Phase 2): fastapi/starlette, uvicorn, pydantic, pyyaml,
# httpx (Gemini narrator), python-dotenv (packages/config/env.py), redis
# (RedisWindowStore), lightgbm + numpy (Layer-1 model). Versions mirror
# pyproject.toml `dependencies` + the `dev` extras that the serving path needs
# (redis, lightgbm, numpy). pandas/openpyxl are TEST-ONLY and omitted.
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache \
        "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" "pyyaml>=6.0" \
        "httpx>=0.27" "python-dotenv>=1.0" "redis>=5.0" "lightgbm>=4.5" "numpy>=1.26"

# CWD must be the repo root: services/scorer/deps.py reads Path("config/...")
# and Path("schema.sql") relative to it.
WORKDIR /repo

EXPOSE 8080

# Container entrypoint (NOT the manual README path -- that runs uvicorn
# directly and is byte-identical):
#   * source deploy/compose.env if present -- the one-shot `bootstrap` writes
#     the merchant key / TOLLGATE_OUTCOME_SECRET / TG_CONFIG_HASH there before
#     the scorer starts. Compose resolves `env_file:` before bootstrap runs, so
#     on a fresh checkout that file would otherwise be missed. `set -a` exports
#     each KEY=VALUE; packages/config/env.py still loads .env after (override
#     =False -- a real env var and .env both still win).
#   * --factory: services.scorer.app:create_app is a factory. --host 0.0.0.0 so
#     the port is reachable. No --reload (unreliable over a Windows bind mount).
#   * --log-config: DEF-D9-002 -- surface the tollgate.scorer INFO lines (Redis
#     connect, model load, "loaded Layer 2 ...") so the Phase-2 exit gate can
#     verify Layer 2 from the container log.
# deploy/ + config/ + models/ arrive via the runtime bind mount.
CMD ["sh", "-c", "set -a; [ -f deploy/compose.env ] && . ./deploy/compose.env; set +a; exec python -m uvicorn services.scorer.app:create_app --factory --host 0.0.0.0 --port 8080 --log-config deploy/uvicorn-logging.json"]
