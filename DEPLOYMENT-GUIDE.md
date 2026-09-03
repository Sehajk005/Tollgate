# Tollgate — Deployment Guide (local production-like validation → AWS)

**Scope.** How to (1) validate the **exact container artifacts** on your laptop
before they go anywhere, and (2) deploy *this* repository to AWS. Every command
is checked against the repository at `day-9` @ `ad86715`. Anything that cannot be
verified from the repo is marked **`VERIFY BEFORE DEPLOYMENT`**.

**This guide does not perform an AWS deployment.** It gets you to the point where
you can, with confidence that the image you tested is the image AWS runs.

**Companion documents:** `README.md` (architecture + local setup),
`PROJECT-PRESENTATION-SCRIPT.md` (the demo), `Decisions.md` Decision 109 (why the
containerized path is shaped the way it is), `QA-AUDIT-DAY-9-2026-09-03.md` (the
evidence).

---

## 1. Architecture overview

### The pipeline this guide implements

```
   Local Docker Compose  (docker compose up --build)
            |
            v
   Production-equivalent container validation  (this repo's docker-compose.yml
            |                                     IS the production stack --
            |                                     dev-parity by design, Decision 109)
            v
   Container image(s)  -- Route A: built on the AWS host from a git checkout
            |             Route B: baked + pushed to Amazon ECR (needs new
            |                       Dockerfiles -- see section 5, VERIFY BEFORE DEPLOYMENT)
            v
   AWS
            |
            v
   AWS services:  1 x EC2 instance running `docker compose` (the whole stack)
                  +  Caddy or an ALB for TLS
                  +  an EBS data volume for tollgate.db + spool
                  +  (optional) ElastiCache for Redis, Secrets Manager, CloudWatch
```

### The actual production architecture (recommended)

**One EC2 instance runs the identical `docker compose` stack from a git
checkout, behind TLS.**

```
Internet
  |  HTTPS :443
  v
Caddy (or ALB)  -- TLS termination, one vhost each for storefront + dashboard,
  |               long idle timeout for the dashboard's SSE stream
  |  HTTP
  +--> storefront container  :5173   (Vite dev server, proxies /v1 -> scorer)
  +--> dashboard  container  :5174   (Vite dev server, proxies /v1 -> scorer)
                                        |
                                        v
                              scorer   :8080  (FastAPI, ONE uvicorn worker)
                                |            |
                                v            v
                        redis :6379    /data on an EBS volume
                        (container      tollgate.db (WAL) + spool/
                         or ElastiCache)
  bootstrap container  -- runs once at `up`, exits 0, writes /repo/deploy/compose.env
```

Everything except Caddy/ALB is exactly what `docker-compose.yml` already
defines. `redis-small` starts too and is harmless (it exists only for
`tests/acceptance/test_redis_eviction.py`; the app never connects to it) -- you
may drop it from a prod override.

### Why this architecture fits -- and why not ECS Fargate

| Requirement (from the code) | Consequence for AWS |
|---|---|
| **The scorer is a single Uvicorn worker.** The token bucket, availability monitor, decision cache, `InMemoryWindowStore` fallback, replay driver, incident registry and policy engine are all in-process on `ScorerState` (Decision 71 / 87). | **Exactly one scorer task. No autoscaling, no target-tracking.** Fargate's core value -- horizontally scaling a stateless service -- is unused here. A second scorer instance would double-count windows-fallback state, run a second replay driver, and split the incident registry. |
| **A one-shot `bootstrap` must run to completion *before* the scorer starts**, and it **shares a writable filesystem** (`/data` and `/repo/deploy/compose.env`) with the scorer. | On a host with `docker compose`, `depends_on: service_completed_successfully` + a bind mount does this for free. On Fargate you need an `essential: false` init container in the same task (works) **and** a shared writable volume for `tollgate.db` -- which on Fargate means **EFS**. SQLite + WAL over EFS with NFS advisory locking is fragile and slow; it is the exact class of problem Decision 109 hit with Windows bind mounts. A single host with an EBS volume avoids it entirely. |
| **The repo is bind-mounted into every container** (dev-parity, Decision 109). `models/`, `config/`, `data/corpus/` and `eval/outputs/d6.json` all arrive that way; the Dockerfiles deliberately **COPY no source**. A self-contained image was **rejected** because the 18 MB corpus is gitignored and un-rebuildable without a LightGBM retrain. | On a host: `git clone` provides the tree, the bind mount just works, and "the image AWS runs == the image you tested" is trivially true (same Dockerfile, same build context). On Fargate you must **bake the repo into new images** (section 5) -- a real change to the repo's build model. |
| **The dashboard's SSE stream** is a long-lived HTTP connection. | Fine behind Caddy (default) or an ALB with `idle_timeout` raised well above 60 s. Nothing special on a single host. |
| **The frontends are Vite dev servers**, not built static bundles, and they need the repo tree visible (`fs.allow: ["..", "../.."]`, `D6Metrics.jsx` static-imports `eval/outputs/d6.json` from the repo root). | Keep running them as dev servers on the host (simplest, matches the demo) **or** do the static-bundle work in a prod override (section 12, VERIFY BEFORE DEPLOYMENT). |
| Traffic is a demo / evaluation workload, not high QPS (`/v1/score` compute p99 = 12 ms; the throughput ceiling is a *serial test harness* artefact, Decision 110). | A single `t3.medium` / `t3.large` is ample. There is no scaling problem to solve. |

**Conclusion:** the simplest AWS architecture that correctly supports every
actual requirement is **one EC2 instance running the committed `docker compose`
stack**, with TLS in front and the mutable DB on an EBS volume. ECS Fargate,
EKS, and App Runner all add machinery (EFS for the shared SQLite volume, image
re-baking, init-container orchestration) to run a workload that has **one**
instance of its stateful component. Use them only after the "production scale"
changes in section 9 -- externalized state and a managed database -- which are
out of scope here.

---

## 2. Prerequisites (on your laptop)

| Tool | Why | Verify |
|---|---|---|
| **Docker Desktop >= 29** with Compose v2 | build + run the stack | `docker version` ; `docker compose version` (expect `v2.x`) |
| **git** | check out the repo on the EC2 host | `git --version` |
| **AWS CLI v2** | create infra, ECR, SSH helper | `aws --version` (expect `aws-cli/2.x`) |
| **An AWS account** with permissions to create: EC2, EBS, VPC/subnet/security-group, an EC2 key pair, IAM instance profile, and (optional) Secrets Manager, ElastiCache, an ALB + ACM cert | | `aws sts get-caller-identity` returns your account/ARN |
| **An SSH client** | reach the EC2 host | `ssh -V` |
| ~2 GB free disk, ports `5173 5174 8080 6379 6380` free | local validation | -- |
| (optional) **`uv` >= 0.11** + Python 3.13 + Node 22 | only if you also run the manual path / the full pytest suite outside containers | `uv --version` |

You do **not** need Python or Node on the laptop for the container validation in
section 4 -- `docker compose up --build` is self-contained.

---

## 3. Environment variables

Every one is read by real code. `local value/source` = where it comes from in
`docker-compose.yml` / the bootstrap; `AWS value/source` = what to set on the
EC2 host.

| Name | Purpose | Required | Local value / source | AWS value / source | Secret? | Must differ per env? |
|---|---|---|---|---|---|---|
| `VITE_TOLLGATE_API_KEY` | merchant API key; both frontends send it as `X-Tollgate-Key`; injected into the Vite build | yes | **written by `bootstrap`** into `deploy/compose.env`; frontends source it at container start | same mechanism (bootstrap writes it); **or** pre-seed `deploy/compose.env` from Secrets Manager | **yes** | yes -- regenerate on a fresh DB |
| `TOLLGATE_OUTCOME_SECRET` | HMAC secret for `POST /v1/outcome`; unset -> that route 503s, rest of the service unaffected | no (route-only) | written by `bootstrap` into `deploy/compose.env` | Secrets Manager -> env at container start | **yes** | yes |
| `TG_CONFIG_HASH` | 64-hex D6 `config_hash` of the working tree; passed to the dashboard so Metrics can disclose evaluation-snapshot freshness | no (cosmetic) | computed + written by `bootstrap` | same (bootstrap) | no | no (it's a hash of committed config) |
| `TOLLGATE_REDIS_URL` | window-store backend; unset/unreachable -> `InMemoryWindowStore` (single-process, not restart-durable) | no (recommended) | `redis://redis:6379` (compose `environment:`) | `redis://redis:6379` (container) **or** `redis://<elasticache-endpoint>:6379` | no | maybe (endpoint) |
| `TOLLGATE_TRUSTED_EDGE_HOSTS` | comma-separated hosts **added to** the built-in `{127.0.0.1, ::1, testclient}`; a peer in this set has its `X-Forwarded-For` honoured (Threat Model K8) | yes under a proxy | `172.28.0.11,172.28.0.12` (the two Vite proxy container IPs) | the container IPs of the frontends on the prod compose network -- **keep it to the frontend proxy IPs only** | no | **yes** -- must be the real edge IPs |
| `TOLLGATE_DB_PATH` | mutable demo DB location | yes (containerized) | `/data/tollgate.db` (compose) | `/data/tollgate.db` (EBS volume mounted at `/data`) | no | no |
| `TOLLGATE_SPOOL_DIR` | spool directory | yes (containerized) | `/data/spool` | `/data/spool` (same EBS volume) | no | no |
| `TOLLGATE_DEMO_CONTROLS` | `1` enables `/v1/demo/*` + the proxy's `x-tg-demo-xff -> X-Forwarded-For` promotion; default off -> those routes **404** | no | `1` for `scorer` + `storefront` (compose) -- **the demo needs it** | **decide deliberately.** `1` if the AWS box is a demo box; **unset** for anything resembling production | no | **yes** |
| `VITE_TOLLGATE_DEMO_CONTROLS` | `1` renders the FLOOD / KILL SCORER strip group in the dashboard | no | `1` for `storefront` + `dashboard` (compose) | match `TOLLGATE_DEMO_CONTROLS` | no | yes |
| `TOLLGATE_SCORER_URL` | Vite `/v1` proxy target | no (defaults) | `http://scorer:8080` (compose) | `http://scorer:8080` (same compose network) | no | no |
| `NARRATOR_BACKEND` | `template` (default, deterministic, no network) or `gemini` | no | unset -> `template` | `template` unless you deliberately want Gemini | no | no |
| `GEMINI_API_KEY` | Google AI Studio key; required only when `NARRATOR_BACKEND=gemini` | no | unset (the demo's `.env` may carry one, unused -> benign `config:` warning) | Secrets Manager, only if `NARRATOR_BACKEND=gemini` | **yes** | yes |
| `GEMINI_MODELS` | comma-separated fallback chain, default `gemini-2.0-flash,gemini-1.5-flash` | no | default | default | no | no |
| `NARRATOR_ENABLED` | `false` disables the narrator entirely | no | default (`true`) | default | no | no |
| `TG_BOOTSTRAP_ENV_FILE` | where `bootstrap` writes its output | no | `/repo/deploy/compose.env` (compose) | same | no | no |
| `TG_BOOTSTRAP_FORCE` | `1` re-runs `learn_store_baseline` / `tune_cusum` even if already done | no | unset | unset (set once if you deliberately re-tune) | no | no |
| `TOLLGATE_FAULTHANDLER` | `1` arms native-fault tracebacks + a periodic stack dump (diagnostic only) | no | unset | unset | no | no |

**Never** put a real secret value in Git, a Dockerfile, the frontend bundle, the
README, or this guide. `.gitignore` already excludes `.env`, `.env.*` (except
`.env.example`) and `deploy/compose.env`. Use placeholders like
`<MERCHANT_API_KEY>` everywhere.

---

## 4. LOCAL production-like validation

This is the point of the guide: prove the container artifacts are deployable
**before** they leave your laptop. The repo's `docker-compose.yml` **is** the
production-equivalent stack (dev-parity, Decision 109), so validating it here is
validating what AWS will run.

> A full run of this section was executed on `day-9` @ `ad86715` while writing
> this guide -- all steps below passed. Your run should match.

### Step 1 -- Build the production images

```bash
cd /path/to/Tollgate
docker compose build
```

Builds four images from three Dockerfiles (`services/scorer/Dockerfile` -- also
used for `bootstrap`; `services/storefront/Dockerfile`; `services/dashboard/Dockerfile`).
Expected image names: `tollgate-scorer`, `tollgate-bootstrap`,
`tollgate-storefront`, `tollgate-dashboard`.

Validate the compose file itself first:

```bash
docker compose config --quiet && echo "compose config: VALID"
docker compose config --services      # bootstrap redis scorer storefront dashboard redis-small
```

### Step 2 -- Start the production-equivalent stack

```bash
docker compose down -v                 # true clean slate: removes the tollgate_data + node_modules volumes
docker compose up --build -d           # detached; the one-shot `bootstrap` runs and exits 0
```

Dependency order (enforced by `depends_on` + healthchecks): `redis` healthy ->
`bootstrap` exits 0 -> `scorer` `/healthz` healthy -> `storefront` + `dashboard`
healthy. Expect all five long-running services `healthy` in ~20-90 s.

```bash
docker compose ps                      # all of redis, redis-small, scorer, storefront, dashboard = "healthy"
```

### Step 3 -- Verify every subsystem

```bash
# --- container health ---
docker compose ps                                     # 5 x healthy, bootstrap = exited (0)

# --- bootstrap ---
docker compose logs bootstrap --no-log-prefix | tail -20
#   expect: "[bootstrap] wrote env file (...)", "[bootstrap] TG_CONFIG_HASH=<64hex>", "[bootstrap] bootstrap complete"
sed -E 's/=.+/=<redacted>/' deploy/compose.env
#   expect three keys: VITE_TOLLGATE_API_KEY, TOLLGATE_OUTCOME_SECRET, TG_CONFIG_HASH

# --- scorer: Redis, Layer 1, Layer 2, narrator ---
docker compose logs scorer --no-log-prefix | grep -iE "Connected to Redis|loaded Layer|Application startup|Uvicorn running"
#   expect:
#     Connected to Redis at redis://redis:6379; using RedisWindowStore
#     loaded Layer-1 model l1-lgbm-v1 + calibrator platt-v1 from models
#     loaded Layer 2 for merchant_demo: policy v2, cusum_h=318.133, tau_flag=0.06475, drift_enabled=True

# --- health endpoint ---
curl -s http://localhost:8080/healthz
#   {"status":"ok","drainer_alive":true,"drainer_connects":1,"drainer_rows":<n>,"drainer_failures":0}

# --- storefront / dashboard / the dashboard's /v1 proxy ---
curl -s -o /dev/null -w "storefront %{http_code}\n" http://localhost:5173/
curl -s -o /dev/null -w "dashboard  %{http_code}\n" http://localhost:5174/
curl -s http://localhost:5174/v1/replay/status         # {"state":"idle",...,"terminal":true}

# --- SSE: headers must flush on subscribe (AUDIT-020) ---
curl -s -N --max-time 2 http://localhost:8080/v1/stream | head -c 20     # ": ping"

# --- normal checkout through the storefront proxy (uses the bootstrap key) ---
KEY=$(grep '^VITE_TOLLGATE_API_KEY=' deploy/compose.env | cut -d= -f2)
curl -s -X POST http://localhost:5173/v1/score \
  -H "Content-Type: application/json" -H "X-Tollgate-Key: $KEY" \
  -d '{"event_id":"validate-1","card_hash":"validatecardhash0001","bin":"411122","last4":"6677","exp_month":4,"exp_year":2028,"amount_minor":120000,"currency":"INR"}'
#   {"attempt_uid":"...","decision":"allow","latency_ms":<~15-80>}

# --- persisted? (drain lag ~1 s) ---
sleep 2
docker compose exec -T scorer python -c "import sqlite3;c=sqlite3.connect('/data/tollgate.db');print('auth_attempt',c.execute('SELECT COUNT(*) FROM auth_attempt').fetchone()[0]);print('attempt_score',c.execute('SELECT COUNT(*) FROM attempt_score').fetchone()[0])"
#   auth_attempt 1 / attempt_score 1  (on a fresh volume)

# --- demo controls gating ---
curl -s -o /dev/null -w "no key -> %{http_code}\n" http://localhost:8080/v1/demo/cotenant-ip          # 401 (route enabled by TOLLGATE_DEMO_CONTROLS=1)
curl -s -o /dev/null -w "with key, nothing enforced -> %{http_code}\n" -H "X-Tollgate-Key: $KEY" http://localhost:8080/v1/demo/cotenant-ip   # 404

# --- the full J6 attack flow ---
#   Open http://localhost:5173/?demo=1 and http://localhost:5174/ and walk
#   PROJECT-PRESENTATION-SCRIPT.md Act 6 (or DAY-9-DEMO-SCRIPT.md). Confirm:
#   Launch -> running -> finished 821/821; 2 ESCALATED drift incidents, TTD ~78 s;
#   D3 read model (no PAN/hash); co-tenant checkout -> allow; Kill scorer -> allow/fail_open;
#   Flood -> shed_responses climb; Reset -> idle + cleared map + Redis dbsize 0.
```

**Failure modes to catch here (each is a real Day-9 defect that is fixed):**

- First checkout returns **`HTTP 401`** -> the frontends booted before `bootstrap`
  wrote the key. `docker compose up -d --force-recreate storefront dashboard`.
  (DEF-D9-011 -- the compose `command:` shim makes this not recur, but check.)
- `docker compose logs scorer` shows **`falling back to InMemoryWindowStore`** ->
  Redis isn't reachable; fix before deploying (in-memory state is not
  restart-durable).
- `GET /v1/incidents` returns **500 `unable to open database file`** -> the demo
  DB is not on a real Linux filesystem (Decision 109). On AWS this is the EBS
  volume; locally it is the `tollgate_data` named volume -- do **not** bind-mount
  `tollgate.db` from a Windows host.

### Step 4 -- Run the full blocking test suite against the containerized environment

The tests run on the host (they need `uv` + Python + Node), pointed at the
containerized Redis. This is exactly what Day-9 Phase 15 did (section 20 of the
audit).

```bash
# backend -- against the running container's Redis
TOLLGATE_REDIS_URL=redis://localhost:6379 uv run pytest tests/ -q
#   expect: 643 passed / 1 failed / 2 xfailed
#   the 1 failure is test_d6_provenance::test_corpus_identity (DEF-D9-003 -- a
#   byte-hash on a gitignored corpus; ZERO metric impact, proven; see README "Testing")
#   the 2 xfails are the handmade_40 human-oracle gates (expected)

# frontend unit + coverage
npm --prefix services/dashboard ci
npm --prefix services/dashboard run test:run          # 205 passed / 21 files
npm --prefix services/dashboard run test:cov          # thresholds 85 / 85 / 80

# browser E2E (Playwright manages its own dev server; no scorer needed)
npm --prefix services/dashboard run test:e2e          # 68 passed (17 checks x 4 viewports)

# stability + time-crossing gates (quiet machine, only redis up)
uv run python -m scripts.verify_60x --gate 60x --faulthandler --redis redis://localhost:6379/9   # PASS 9/9
uv run python -m scripts.verify_60x --gate crossing                                              # PASS
uv run python -m scripts.verify_60x --gate throughput                                            # correctness sub-checks PASS;
#   throughput_ok is ADVISORY on this machine (~305 aps) per Decision 110 -- do NOT treat as a blocker
```

> Run `verify_60x` with **only `redis` up** (`docker compose stop scorer
> storefront dashboard`). Under the full stack + Playwright it hits the
> documented Redis-socket-pressure signature and fails on environment, not
> regression (audit section 20).

### Step 5 -- Inspect logs

```bash
docker compose logs scorer --no-log-prefix | grep -iE \
  "Connected to Redis|falling back to InMemory|loaded Layer-1|loaded Layer 2|config:|event loop lag|ERROR|Traceback|fail_open"
```

You want to see, once each: `Connected to Redis ... RedisWindowStore`,
`loaded Layer-1 model l1-lgbm-v1 + calibrator platt-v1`, `loaded Layer 2 for
merchant_demo: policy v2, ...`. You want to **not** see: `falling back to
InMemoryWindowStore`, any `Traceback`, any `event loop lag ... threshold`, any
unexplained `ERROR`. A single benign `config: GEMINI_API_KEY is set but
NARRATOR_BACKEND is 'template'` warning is fine.

`docker compose logs bootstrap` must end with `bootstrap complete` and no
`FATAL`.

### Step 6 -- Test restart behaviour

```bash
docker compose restart scorer
sleep 12
curl -s http://localhost:8080/healthz            # healthy again in ~8 s; drainer_alive:true, drainer_failures:0
docker compose logs scorer --no-log-prefix | tail -20   # drainer resumes from its persisted byte offset -- no re-drain
# a checkout still works, the replay is idle (not a phantom "running")
```

Also confirm a full stop/start preserves data (the volume persists):

```bash
docker compose down          # NOT -v
docker compose up -d
docker compose exec -T scorer python -c "import sqlite3;print(sqlite3.connect('/data/tollgate.db').execute('SELECT COUNT(*) FROM auth_attempt').fetchone()[0])"
# still shows the row count from before the restart
```

### Step 7 -- Test a completely clean startup

```bash
docker compose down -v
docker compose up --build
```

### Step 8 -- Verify behaviour after the fresh start

- All 5 long-running services reach `healthy`.
- `deploy/compose.env` holds a **freshly-minted** `VITE_TOLLGATE_API_KEY` whose
  hash equals `merchant.api_key_hash` (the DEF-D9-011 fix survives a fresh
  `down -v` + a new key -- verified twice in the Day-9 rehearsals).
- The first checkout returns `200 {"decision":"allow"}` -- **no 401**.
- `docker compose logs scorer` shows Redis connected + Layer 1 + Layer 2 loaded.
- Repeat the full J6 walkthrough from Step 3.

**Only when Steps 1-8 all pass is the artifact ready to go to AWS.**

---

## 5. Image build and tagging

### Route A (recommended) -- build on the AWS host from a git checkout

There is no separate "push an image" step. The AWS host runs
`docker compose build` against the **same Dockerfiles and the same build context
(the git tree)** you just validated. "The image I tested is the image AWS runs"
is true because both are `docker build` of `services/*/Dockerfile` with context
`.` at the same commit.

- **Pin the commit, not `latest`.** Deploy by checking out an **exact SHA or an
  annotated tag**, never a moving branch:

  ```bash
  # on the EC2 host
  git fetch --all --tags
  git checkout ad86715            # or: git checkout v-demo-2026-09-03
  docker compose build
  docker compose up -d
  ```

- **Record what you deployed.** Keep a one-line deploy log on the host:

  ```bash
  { date -u +%FT%TZ; git rev-parse HEAD; docker compose images --format '{{.Service}} {{.ID}}'; } >> /data/deploy.log
  ```

- **Avoid deploying a stale image.** `docker compose build` rebuilds any layer
  whose inputs changed; the Dockerfiles COPY only `pyproject.toml` / `uv.lock`
  (scorer) and the two `package.json` / `package-lock.json` pairs (frontends),
  so a code change alone does **not** invalidate the dependency layer -- which is
  fine because code arrives via the bind mount at runtime, not the image. If in
  doubt, `docker compose build --no-cache`.

- **Why `latest` alone is risky:** `latest` is whatever was pushed last. If a
  rollback, a CI job, or another operator moves it, your "known-good" is gone and
  there is no record of which build is actually running. A commit SHA or an
  immutable tag is a fact; `latest` is a race.

### Route B (immutable images in ECR) -- `VERIFY BEFORE DEPLOYMENT`

The repo's Dockerfiles **deliberately COPY no application source** and rely on a
runtime bind mount of the repo (Decision 109 rejected a self-contained image
because `data/corpus/tollgate.db` is 18 MB, gitignored, and un-rebuildable
without a LightGBM retrain). To ship immutable ECR images you must first add
production Dockerfiles that bake the tree in. **These do not exist in the repo --
create and validate them before using any ECR command in section 7/section 8.**

Minimum shape (**`VERIFY BEFORE DEPLOYMENT`** -- write, then re-run section 4 against them):

- `deploy/aws/Dockerfile.scorer` -- `FROM` the existing `services/scorer/Dockerfile`
  build, then `COPY . /repo` (respecting `.dockerignore`, which already excludes
  `.git/`, `data/`, `models/`, `*.md`, `evidence/`, `.venv/`, `node_modules/`).
  **`models/` and `eval/outputs/d6.json` are excluded by `.dockerignore` and
  must be added back** (either un-ignore them for this build or `COPY` them
  explicitly) -- the scorer loads `models/` and the dashboard imports
  `eval/outputs/d6.json`.
- `deploy/aws/Dockerfile.frontend` -- `FROM node:22-bookworm-slim`, `npm ci` per
  app, `COPY` the app + the repo tree it needs (`eval/outputs/d6.json`,
  `config/`), keep `npm run dev` **or** switch to `vite build` + a static server
  (section 12).
- `deploy/aws/docker-compose.prod.yml` -- an override that removes the
  `./:/repo` bind mounts, keeps the `tollgate_data`-equivalent as a host path on
  the EBS volume, and points `build:` at the new Dockerfiles.

Then tag and push (see section 7). Every section 7/section 8 command that
references an ECR image URI is **`VERIFY BEFORE DEPLOYMENT`** until those files
exist and pass section 4.

---

## 6. AWS account setup

### 6.1 AWS CLI + region

```bash
aws configure           # set an access key/secret for an IAM user or use `aws configure sso`
aws configure set region ap-south-1        # pick the region closest to you; ap-south-1 = Mumbai
aws sts get-caller-identity                 # confirms the identity + account id
```

Choose one region and use it consistently. This guide uses **`ap-south-1`** in
examples -- substitute `<REGION>` everywhere if different.

### 6.2 IAM requirements

The identity you run these commands as needs (attach AWS-managed policies or
scope down):

- `AmazonEC2FullAccess` (or scoped: run/stop instances, describe, create
  security groups, create/attach volumes, create key pairs)
- `IAMFullAccess` **or** the ability to create one instance role +
  instance profile (below)
- (Route B) `AmazonEC2ContainerRegistryFullAccess`
- (optional) `SecretsManagerReadWrite`, `AmazonElastiCacheFullAccess`,
  `ElasticLoadBalancingFullAccess`, `AWSCertificateManagerFullAccess`

**EC2 instance role** (so the host can read secrets + write logs) --
`VERIFY BEFORE DEPLOYMENT` the exact policy JSON for your account:

```bash
aws iam create-role --role-name tollgate-ec2 \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name tollgate-ec2 --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
# if using Secrets Manager (section 13): also attach a policy allowing secretsmanager:GetSecretValue on your secret ARNs
aws iam create-instance-profile --instance-profile-name tollgate-ec2
aws iam add-role-to-instance-profile --instance-profile-name tollgate-ec2 --role-name tollgate-ec2
```

### 6.3 Networking

Use the **default VPC** and a **public subnet** for simplicity (single host,
public HTTPS). Record:

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNET_ID=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID Name=map-public-ip-on-launch,Values=true --query 'Subnets[0].SubnetId' --output text)
echo "$VPC_ID $SUBNET_ID"
```

### 6.4 Security group

**Inbound:** `443` (HTTPS) from the world, `22` (SSH) **from your IP only**.
Do **not** open `5173 / 5174 / 8080 / 6379`.

```bash
SG_ID=$(aws ec2 create-security-group --group-name tollgate --description "Tollgate demo host" --vpc-id $VPC_ID --query GroupId --output text)
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22  --cidr ${MYIP}/32
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0
# also needed for the Let's Encrypt HTTP-01 challenge if you use Caddy:
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0
```

### 6.5 Key pair

```bash
aws ec2 create-key-pair --key-name tollgate --query KeyMaterial --output text > ~/.ssh/tollgate.pem
chmod 600 ~/.ssh/tollgate.pem
```

### 6.6 Persistent storage -- an EBS data volume

`tollgate.db` (WAL) + `spool/` must live on a real block filesystem that
survives an instance replacement. Create a dedicated `gp3` volume:

```bash
AZ=$(aws ec2 describe-subnets --subnet-ids $SUBNET_ID --query 'Subnets[0].AvailabilityZone' --output text)
VOL_ID=$(aws ec2 create-volume --availability-zone $AZ --size 20 --volume-type gp3 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=tollgate-data}]' --query VolumeId --output text)
echo $VOL_ID
```

(You attach it to the instance in section 8.)

### 6.7 (Optional) ECR repositories -- Route B only, `VERIFY BEFORE DEPLOYMENT`

```bash
for name in tollgate-scorer tollgate-storefront tollgate-dashboard; do
  aws ecr create-repository --repository-name $name --image-tag-mutability IMMUTABLE \
    --image-scanning-configuration scanOnPush=true
done
```

### 6.8 (Optional) Secrets -- see section 13.

### 6.9 (Optional) ElastiCache for Redis -- see section 9.

---

## 7. Push the verified image to AWS

### Route A -- nothing to push

The tree goes to the host via `git`, and the host builds. Skip to section 8.

```bash
# on the EC2 host, once:
git clone <YOUR_REPO_URL> /opt/tollgate
cd /opt/tollgate && git checkout <TESTED_SHA>
```

The build context and Dockerfiles are byte-identical to what you validated in
section 4, so the images are equivalent by construction. Record the SHA
(section 5).

### Route B -- ECR (`VERIFY BEFORE DEPLOYMENT`: requires the section 5 prod Dockerfiles)

1. **Authenticate Docker to ECR:**

   ```bash
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   REGION=ap-south-1
   aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
   ```

2. **Create/use the repositories** -- section 6.7.

3. **Tag the locally verified images** with an immutable tag (the git SHA):

   ```bash
   SHA=$(git rev-parse --short HEAD)
   REG=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
   # build the PROD images from the section 5 Dockerfiles first, then:
   docker tag tollgate-scorer:latest     $REG/tollgate-scorer:$SHA
   docker tag tollgate-storefront:latest $REG/tollgate-storefront:$SHA
   docker tag tollgate-dashboard:latest  $REG/tollgate-dashboard:$SHA
   ```

4. **Push:**

   ```bash
   docker push $REG/tollgate-scorer:$SHA
   docker push $REG/tollgate-storefront:$SHA
   docker push $REG/tollgate-dashboard:$SHA
   ```

5. **Verify the digest** you pushed matches the local image:

   ```bash
   docker inspect --format '{{index .RepoDigests 0}}' $REG/tollgate-scorer:$SHA
   aws ecr describe-images --repository-name tollgate-scorer --image-ids imageTag=$SHA \
     --query 'imageDetails[0].imageDigest' --output text
   # the two digests must be identical
   ```

6. **Ensure AWS runs that exact image:** reference images by **digest**, not tag,
   in the prod compose file / task definition:

   ```yaml
   image: <REG>/tollgate-scorer@sha256:<DIGEST_FROM_STEP_5>
   ```

> **The goal:** the image you smoke-tested in section 4 is the image AWS runs.
> Route A guarantees it by rebuilding the same context. Route B guarantees it by
> deploying the **digest** you verified in step 5 -- never a floating tag.

---

## 8. Deploy the application (Route A -- single EC2 host)

### 8.1 Launch the instance

Pick a current Amazon Linux 2023 AMI:

```bash
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query 'Parameter.Value' --output text)

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id $AMI --instance-type t3.large --key-name tollgate \
  --security-group-ids $SG_ID --subnet-id $SUBNET_ID --associate-public-ip-address \
  --iam-instance-profile Name=tollgate-ec2 \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=tollgate}]' \
  --query 'Instances[0].InstanceId' --output text)

aws ec2 wait instance-running --instance-ids $INSTANCE_ID
aws ec2 attach-volume --volume-id $VOL_ID --instance-id $INSTANCE_ID --device /dev/sdf
PUBIP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "ssh -i ~/.ssh/tollgate.pem ec2-user@$PUBIP"
```

- **`t3.large`** (2 vCPU / 8 GB) is comfortable for the single-worker scorer +
  Redis + two Vite dev servers + LightGBM. `t3.medium` (4 GB) is the practical
  minimum; watch memory.
- Common error: **instance stuck `pending` / no public IP** -> the subnet isn't
  auto-assigning public IPs; pass `--associate-public-ip-address` (above) or use
  an Elastic IP.

### 8.2 First-boot host setup (SSH in)

```bash
ssh -i ~/.ssh/tollgate.pem ec2-user@$PUBIP

sudo dnf -y install docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
# reconnect for the group to take effect, or `newgrp docker`

# docker compose v2 plugin
DOCKER_CONFIG=/usr/local/lib/docker
sudo mkdir -p $DOCKER_CONFIG/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" -o $DOCKER_CONFIG/cli-plugins/docker-compose
sudo chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
docker compose version

# mount the EBS data volume at /data
lsblk                                   # find the device name (e.g. nvme1n1)
sudo file -s /dev/nvme1n1               # if this says "data" it is BLANK -> safe to mkfs; if "ext4 filesystem" -> SKIP mkfs
sudo mkfs -t ext4 /dev/nvme1n1          # ONLY on a brand-new volume
sudo mkdir -p /data
echo '/dev/nvme1n1 /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
df -h /data
```

### 8.3 Get the code and the secrets in place

```bash
git clone <YOUR_REPO_URL> /opt/tollgate
cd /opt/tollgate
git checkout <TESTED_SHA>

# data/corpus/tollgate.db is gitignored and 18 MB -- it is NOT in the clone.
# ship it out of band, e.g.:
#   aws s3 cp s3://<your-bucket>/tollgate-corpus.db data/corpus/tollgate.db
# (or scp it from your laptop). Without it, bootstrap's learn/tune steps die.

# Provide deploy/compose.env if you want deterministic secrets (section 13). Otherwise
# the bootstrap will seed a fresh merchant + key on first `up` against the empty
# /data volume -- which is the simplest correct path for a fresh demo box.
```

The compose file mounts `tollgate_data` as a **named Docker volume**, not
`/data` directly. To put the mutable DB on the **EBS** volume, add a tiny
override (`deploy/aws/compose.override.yml`) -- **`VERIFY BEFORE DEPLOYMENT`**:

```yaml
# deploy/aws/compose.override.yml
services:
  bootstrap:
    volumes:
      - ./:/repo
      - /data:/data                 # replaces the tollgate_data named volume
  scorer:
    volumes:
      - ./:/repo
      - /data:/data
```

### 8.4 Bring the stack up

```bash
cd /opt/tollgate
docker compose -f docker-compose.yml -f deploy/aws/compose.override.yml up --build -d
docker compose ps                    # 5 x healthy, bootstrap exited 0
curl -s http://localhost:8080/healthz
```

Expected result: identical to section 4 Step 3 -- Redis connected, Layer 1 +
Layer 2 loaded, `/healthz` ok, checkout `200 allow`.

### 8.5 TLS + public routing (Caddy)

Point two DNS records at `$PUBIP` (e.g. `shop.example.com`,
`ops.example.com`). Then, on the host:

```bash
sudo dnf -y install 'dnf-command(copr)' || true
sudo dnf -y copr enable @caddy/caddy || true
sudo dnf -y install caddy || { sudo curl -sL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /usr/local/bin/caddy && sudo chmod +x /usr/local/bin/caddy; }
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
shop.example.com {
    reverse_proxy 127.0.0.1:5173
}
ops.example.com {
    reverse_proxy 127.0.0.1:5174 {
        flush_interval -1          # do not buffer the SSE stream
    }
}
EOF
sudo systemctl enable --now caddy
```

Caddy fetches Let's Encrypt certs automatically (needs `:80` and `:443` open --
section 6.4). `flush_interval -1` (or an ALB with a raised `idle_timeout`) is
what keeps `GET /v1/stream` alive.

> **CORS:** the frontends proxy `/v1` to the scorer, so the browser only ever
> talks to `shop.` / `ops.` -- same-origin. No CORS config is needed. (The scorer
> does add permissive CORS for `localhost:5173/5174` in `app.py`; it is inert in
> production because nothing calls the scorer cross-origin.)

### 8.6 `TOLLGATE_TRUSTED_EDGE_HOSTS` on AWS -- set it correctly

The scorer honours `X-Forwarded-For` **only** from a peer in this set. Under the
prod compose network the two frontends get container IPs on
`172.28.0.0/24` (`storefront` = `172.28.0.11`, `dashboard` = `172.28.0.12` -- the
compose file pins these). Keep the compose `environment:` value
(`172.28.0.11,172.28.0.12`) **unless** you change the subnet. Caddy -> frontend
-> scorer means the *frontend proxy* is the declared edge, which is correct.

> **`VERIFY BEFORE DEPLOYMENT`:** if you flatten the topology (Caddy -> scorer
> directly), the declared edge becomes Caddy's IP and you must set
> `TOLLGATE_TRUSTED_EDGE_HOSTS` to that, and ensure Caddy sets a trustworthy
> `X-Forwarded-For` and strips any client-supplied one.

### 8.7 Autostart on reboot

```bash
sudo tee /etc/systemd/system/tollgate.service >/dev/null <<'EOF'
[Unit]
Description=Tollgate stack
Requires=docker.service
After=docker.service network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/tollgate
ExecStart=/usr/local/lib/docker/cli-plugins/docker-compose -f docker-compose.yml -f deploy/aws/compose.override.yml up -d
ExecStop=/usr/local/lib/docker/cli-plugins/docker-compose -f docker-compose.yml -f deploy/aws/compose.override.yml down
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable tollgate
```

### 8.8 (Alternative) ECS Fargate -- not recommended; `VERIFY BEFORE DEPLOYMENT` throughout

If org policy forbids EC2: one **service**, `desired_count: 1`, **no**
autoscaling; one **task definition** with `bootstrap` as a non-essential
container ordered before `scorer` (`dependsOn: [{containerName: bootstrap,
condition: SUCCESS}]`); an **EFS** access point mounted at `/data` on both
`bootstrap` and `scorer` (accept the SQLite-on-NFS locking risk, or move to RDS
per section 9); an **ALB** with `idle_timeout >= 300` and a target group health
check on `GET /healthz` (200); images from ECR by **digest** (section 7 Route B,
which itself needs the section 5 prod Dockerfiles). This is materially more
moving parts than section 8.1-8.7 for a workload with one stateful instance --
see section 1.

---

## 9. Redis / persistent state

| Data | Where it lives | Must survive a restart? | Notes for AWS |
|---|---|---|---|
| **Sliding-window / CUSUM-bucket / idempotency / shed-counter keys** (Redis) | `redis` container, or ElastiCache | **No.** All TTL'd; the scorer tolerates a cold Redis (fails open mid-request, auto-recovers). Losing them = a brief window where counts restart from zero. | Container `redis:7-alpine` is fine for a demo. For less downtime on a node failure: **ElastiCache for Redis**, a replication group, Multi-AZ, automatic failover. Point `TOLLGATE_REDIS_URL` at the cluster endpoint. **No code change.** |
| **`tollgate.db`** (SQLite, WAL) + **`spool/`** | `/data` on the **EBS volume** | **Yes** -- `auth_attempt`, `attempt_score`, `incident`, `enforcement_action`, `narrator_call`, `eval_run`, the merchant row, `store_baseline`, `policy_config`. | Must be a **real block filesystem** (ext4 on EBS). **Not EFS/NFS** -- SQLite WAL `-shm` mmap + NFS advisory locking is exactly the failure class Decision 109 hit on Windows bind mounts. **Not** a bind mount from a non-Linux host. |
| **`deploy/compose.env`** (merchant key, outcome secret, config hash) | written by `bootstrap` into the repo checkout; gitignored | Effectively yes -- regenerating it against an existing merchant row triggers the `INSERT OR IGNORE` footgun. | Either let `bootstrap` seed once against the empty `/data` and then leave it, **or** pre-provision it from Secrets Manager (section 13) so a re-created instance reuses the same key. `compose_bootstrap.py` reuses a key that hashes to `merchant.api_key_hash` or **fails loudly** -- it never emits a dead key. |
| **In-process scorer state** (token bucket, availability monitor, decision cache, `InMemoryWindowStore` fallback, replay driver, incident registry, policy engine) | RAM of the one scorer process (Decision 71 / 87) | No | This is why there is **one** scorer and **no** horizontal scale-out. See below. |
| **`models/`, `config/`, `data/corpus/`, `eval/outputs/d6.json`** | the git checkout (bind-mounted) | Read-only; part of the code | Route A: they come with `git clone` (except `data/corpus/`, gitignored -- ship it). Route B: `.dockerignore` currently excludes `models/`, `data/`, `*.md`, `evidence/` -- you must add `models/` and `eval/outputs/d6.json` back for the baked image. |

**Local bind mounts vs AWS.** The local `tollgate_data` **named Docker volume**
exists because a Windows bind mount can't host SQLite WAL. On the AWS Linux host
that constraint is gone -- mount the **EBS volume at `/data`** and bind
`/data:/data` (the section 8.3 override). Do **not** copy the local `./:/repo`
bind mount blindly to a multi-host or Fargate deployment -- there it must become a
baked image (section 5).

**What must change for a multi-instance deployment** (out of scope, for
completeness):

1. Externalize the scorer's in-process state -- token bucket + availability
   monitor to Redis (or a small sidecar); the decision cache already has a Redis
   idempotency key backing it and just needs the cross-process read path; the
   replay driver / incident registry / policy engine to a shared store.
2. Move `tollgate.db` to **RDS** (PostgreSQL) -- replace `packages/storage/`'s
   SQLite connection + the spool->drainer with a real DB writer.
3. Build the frontends to static bundles behind CloudFront instead of running
   Vite dev servers (section 12).
4. Put everything behind an ALB with a long idle timeout and sticky routing for
   SSE.

---

## 10. Bootstrap / initialization

**What `bootstrap` (`scripts/compose_bootstrap.py`) does, in order:**

1. If `tollgate.db` is absent, initialize the schema (`schema.sql`).
2. **`ensure_merchant()`** -- if no `merchant_demo` row, run `seed_merchant`
   (creates the row, mints an API key + an outcome HMAC secret, writes them to
   `deploy/compose.env`). If the row **already exists**, find a key on file
   (`deploy/compose.env`, then `services/*/.env`, then `.env`) that hashes to
   `merchant.api_key_hash` and reuse it; if none matches, **`SystemExit(1)` with
   a loud message** -- it never prints a dead key (the `INSERT OR IGNORE`
   footgun).
3. **`ensure_corpus_working_copy()`** (containerized only) -- `shutil.copy2` the
   reference corpus to `/data/corpus.db` so `learn`/`tune` never write the
   bind-mounted reference file (DEF-D9-003 recurrence guard).
4. **`ensure_store_baseline()`** -- if no `store_baseline` row, run
   `learn_store_baseline` against the corpus working copy. **Layer 2 will not
   load without this row.** Idempotent (`INSERT ... ON CONFLICT DO UPDATE`).
5. **`ensure_tuned_policy()`** -- if the latest `policy_config` has an empty
   `thresholds` map, run `tune_cusum` (tunes `cusum_h` from the 7 negative
   controls to ARL0 >= 8,640 buckets; writes a new `policy_config` version with
   `thresholds = CostModel.tier_ladder()`). Guarded so repeated `up` does **not**
   sprawl policy versions.
6. **`write_config_hash()`** -- compute `eval.provenance.config_hash()` and write
   `TG_CONFIG_HASH` to `deploy/compose.env` (the dashboard needs it; a Node
   image has no Python to compute it).

**Idempotency:** a second `docker compose up` re-runs `bootstrap`; steps 2, 4, 5
are all no-ops when their work is already done. Set `TG_BOOTSTRAP_FORCE=1` to
force `learn`/`tune` to re-run.

**Configuration hashes:** `TG_CONFIG_HASH` is a domain-separated hash of the
committed config files (`eval/provenance.py`). The dashboard compares it to
`d6.json`'s `provenance.config_hash` and shows "configs unchanged since" /
"configs have changed". It does not affect scoring.

**First startup vs restart:** first `up` against an empty `/data` seeds
everything. A restart with data present: `bootstrap` sees the merchant +
baseline + tuned policy, does nothing but re-confirm and re-write
`TG_CONFIG_HASH`, exits 0.

**How to tell it succeeded:**

```bash
docker compose logs bootstrap --no-log-prefix | tail -5
#   [bootstrap] TG_CONFIG_HASH=<64 hex>
#   [bootstrap] bootstrap complete           <-- and NO "[bootstrap] FATAL:"
docker compose exec -T scorer python -c "import sqlite3;c=sqlite3.connect('/data/tollgate.db');print('merchant',c.execute('SELECT COUNT(*) FROM merchant').fetchone()[0]);print('store_baseline',c.execute('SELECT COUNT(*) FROM store_baseline').fetchone()[0]);print('policy thresholds',c.execute(\"SELECT thresholds FROM policy_config ORDER BY version DESC LIMIT 1\").fetchone()[0][:40])"
#   merchant 1 / store_baseline 1 / policy thresholds {"throttle": 0.0647...
docker compose logs scorer --no-log-prefix | grep "loaded Layer 2"
#   loaded Layer 2 for merchant_demo: policy v2, cusum_h=318.133, ...
```

If the scorer log says **`no store_baseline row ... Layer 2 disabled (Day-5
path)`**, bootstrap did not complete -- the scorer will still serve, but
rules + model only, no CUSUM/SPRT/incidents.

---

## 11. Health checks

| Check | What it is | Healthy looks like | If it fails |
|---|---|---|---|
| `GET /healthz` (scorer, `:8080`) | does **no work** on purpose -- a slow answer means the event loop is blocked (AUDIT-006) | `{"status":"ok","drainer_alive":true,"drainer_connects":<n>,"drainer_rows":<n>,"drainer_failures":0}` | `drainer_alive:false` -> the spool->DB writer died (data stops persisting; scoring continues). `drainer_failures>0` -> DB write errors -- check `/data` mount + disk. No response / slow -> event-loop block; check `docker compose logs scorer` for `event loop lag` warnings. |
| Compose `scorer` healthcheck | `curl -fsS http://localhost:8080/healthz` every 3 s, 20 retries, 20 s start period | `healthy` in `docker compose ps` | container marked `unhealthy`; `bootstrap`/frontends' `depends_on` will hold |
| Compose `storefront` / `dashboard` healthcheck | `node -e "require('net').connect(<port>,'127.0.0.1')..."` -- TCP-connect only | `healthy` | Vite failed to start; check `docker compose logs storefront` -- usually a `npm ci` / node_modules-volume issue |
| Compose `redis` / `redis-small` healthcheck | `redis-cli ping` | `healthy` | Redis down; the scorer will fall back to `InMemoryWindowStore` and log it |
| `bootstrap` | one-shot; the scorer waits for `service_completed_successfully` | exits `0`, log ends `bootstrap complete` | exits non-zero -> the whole stack does not come up; read `docker compose logs bootstrap` for the `FATAL` line |

**Healthy startup sequence:** `redis` healthy (~4 s) -> `bootstrap` runs
(~10-40 s: seed + learn + tune + hash) -> exits 0 -> `scorer` starts, logs Redis +
Layer 1 + Layer 2, `/healthz` healthy (~8-20 s) -> `storefront` + `dashboard`
start, healthy (~10-30 s). Total ~20-90 s.

For the EC2 host itself: a CloudWatch alarm on the instance status check, and
(if using an ALB) a target group health check on `GET /healthz` -> `200`.

---

## 12. Frontend / backend routing

**Local + Route A (single host):** the storefront and dashboard reach the scorer
**through their own Vite dev-server `/v1` proxy** (`vite.config.js` reads
`TOLLGATE_SCORER_URL`, default `http://localhost:8080`, compose sets
`http://scorer:8080`). The browser only ever talks to the storefront/dashboard
origin -> **same-origin, no CORS**. Caddy (or an ALB) terminates TLS and reverse-
proxies `shop.` -> `:5173` and `ops.` -> `:5174`.

- **API URL:** never configured in the browser. The frontend calls `/v1/...`
  relative; Vite proxies it.
- **SSE:** `GET /v1/stream` is a long-lived stream. Caddy must not buffer it
  (`flush_interval -1`); an ALB needs `idle_timeout` >= 300 s. The dashboard
  already falls back to 5 s polling of `/v1/stream/recent?after=<cursor>` if the
  stream drops, and back-fills on reconnect -- so a proxy hiccup degrades
  gracefully, it doesn't break the console.
- **TLS/HTTPS:** terminated at Caddy/ALB; the internal hops (`caddy -> vite ->
  scorer`) are plain HTTP on the private host/network.
- **Public/private:** only `443` (+ `80` for ACME) is public. `5173/5174/8080/6379`
  are host-local / private-network only (section 6.4).

**Do not** assume the local Vite proxy is a production web server. It is a **dev
server**. For a hardened deployment (`VERIFY BEFORE DEPLOYMENT`):

1. `npm --prefix services/dashboard run build` and
   `npm --prefix services/storefront run build` (note: the storefront
   `package.json` currently has **only** a `dev` script -- you'd add `"build":
   "vite build"` and `"preview"`), producing static bundles.
2. Serve the bundles from Caddy directly (or S3 + CloudFront).
3. Move the `/v1` proxy from Vite into Caddy/ALB: `reverse_proxy /v1/* scorer:8080`.
4. Inject `VITE_TOLLGATE_API_KEY` / `TG_CONFIG_HASH` at **build** time -- they are
   compiled into the bundle. This means a key rotation is a rebuild. (Weigh this
   against Route A, where the dev server picks the key up from the environment at
   start.)

---

## 13. Secrets

**What is secret:** `VITE_TOLLGATE_API_KEY` (merchant key),
`TOLLGATE_OUTCOME_SECRET` (HMAC), `GEMINI_API_KEY` (only if
`NARRATOR_BACKEND=gemini`). **Not secret:** `TG_CONFIG_HASH` (a hash of committed
config), everything else in section 3.

**Never** place a secret in: Git, a Dockerfile, the frontend bundle (Route A
keeps the key server-side; the section 12 static-bundle path compiles it in --
accept that trade or don't take that path), the README, or shell history you
keep.

**Options, simplest first:**

1. **Let `bootstrap` seed once** (demo box). The key + secret land in
   `deploy/compose.env` on the host (mode `600`, gitignored). Fine for a
   throwaway demo instance. Back it up if you care about key stability across
   instance replacement.

2. **AWS Secrets Manager** (recommended for anything that outlives a demo):

   ```bash
   aws secretsmanager create-secret --name tollgate/outcome-secret --secret-string '<GENERATE_A_STRONG_SECRET>'
   aws secretsmanager create-secret --name tollgate/merchant-key   --secret-string '<MERCHANT_API_KEY>'
   # GEMINI only if used:
   # aws secretsmanager create-secret --name tollgate/gemini-key --secret-string '<GEMINI_API_KEY>'
   ```

   On the host, fetch them at start (systemd `ExecStartPre`, or a small
   entrypoint wrapper) and write `deploy/compose.env` **before**
   `docker compose up`, so `compose_bootstrap.py` finds a key that hashes to the
   stored `merchant.api_key_hash` and reuses it instead of re-seeding:

   ```bash
   umask 077
   {
     echo "VITE_TOLLGATE_API_KEY=$(aws secretsmanager get-secret-value --secret-id tollgate/merchant-key   --query SecretString --output text)"
     echo "TOLLGATE_OUTCOME_SECRET=$(aws secretsmanager get-secret-value --secret-id tollgate/outcome-secret --query SecretString --output text)"
   } > /opt/tollgate/deploy/compose.env
   ```

   The instance role (section 6.2) must allow `secretsmanager:GetSecretValue` on
   those ARNs.

   > **First-time chicken-and-egg:** the merchant key must match
   > `merchant.api_key_hash`. On a brand-new `/data`, let `bootstrap` seed once,
   > read the generated key/secret back out of `deploy/compose.env`, and store
   > *those* in Secrets Manager. From then on the host reuses them.

3. **SSM Parameter Store SecureString** -- same pattern, `aws ssm get-parameter
   --with-decryption`. Cheaper; no rotation features.

**Rotation:** rotating `VITE_TOLLGATE_API_KEY` means updating
`merchant.api_key_hash` too (re-run `seed_merchant` against a fresh DB, or write
a one-off `UPDATE merchant SET api_key_hash = ?`). Rotating
`TOLLGATE_OUTCOME_SECRET` means updating `merchant.outcome_hmac_key_hash`
likewise. Both are `hash_api_key()` = plain SHA-256.

---

## 14. AWS smoke test

After deployment, from your laptop and (where noted) the host:

```
[ ] docker compose ps on the host -- 5 x healthy, bootstrap exited 0
[ ] curl -sk https://ops.example.com/v1/replay/status        -> {"state":"idle",...,"terminal":true}
[ ] curl on the host: curl -s http://localhost:8080/healthz  -> {"status":"ok","drainer_alive":true,"drainer_failures":0}
[ ] https://shop.example.com/                                -> 200, the Kesar & Co. product page
[ ] https://ops.example.com/                                 -> 200, the dashboard (threat band CALM, SSE: live)
[ ] API reachable: a checkout from https://shop.example.com/?demo=1 -> "Order confirmed", tier: allow
[ ] on the host: SELECT COUNT(*) FROM auth_attempt / attempt_score  -> incremented by 1, with the typed bin
[ ] replay works: dashboard Launch (easy/60/pace) -> running -> finished 821/821
[ ] threat detection: threat band CALM -> ELEVATED; ATTEMPTS/CARDS tiles climb
[ ] incident appears: Incidents badge; 2 ESCALATED drift incidents, TTD ~78 s event-time
[ ] co-tenant: storefront "Checkout as CGNAT co-tenant" -> allow, "via co-tenant IP: 198.51.100.x"
[ ] flood/shed: dashboard DEMO -> Flood -> shed_responses climbs (intermittent on a small box -- DEF-D9-004)
[ ] scorer fail-open: dashboard DEMO -> Kill scorer -> a checkout still confirms, tier: fail_open, never a 5xx; toggle off -> recovered
[ ] SSE works: the dashboard ticker updates live during the replay; chip reads "live" not "reconnecting"
[ ] reset works: dashboard Reset -> idle, threat CALM, incidents cleared, (host) Redis dbsize 0
[ ] no secrets exposed: curl -s https://shop.example.com/ | grep -i tollgate_key  -> nothing;
        grep the served JS bundle for the raw key value -> nothing (Route A); the ?demo=1 readout shows HTTP status, not the key
[ ] logs clean: docker compose logs scorer | grep -iE "Traceback|event loop lag|falling back to InMemory|ERROR"  -> nothing unexpected
```

If `TOLLGATE_DEMO_CONTROLS` is **unset** on the AWS box (a non-demo deployment),
the co-tenant / flood / kill-scorer checks are expected to be **absent** (the UI
group doesn't render) and `/v1/demo/*` returns **404** -- verify that instead.

---

## 15. Cloud-specific failure testing

**Safe against this deployment** (it's a demo box; all of these have Day-9
Phase-7 evidence that they fail safely):

| Test | How | Expected |
|---|---|---|
| **Scorer restart** | `docker compose restart scorer` | healthy in ~8 s; drainer resumes from byte offset (no re-drain); a checkout works; replay `idle`, not phantom `running` |
| **Redis interruption** | `docker compose restart redis` | mid-flight `/v1/score` -> `200 allow` `fail_open:window_store`, never 5xx; auto-recovers, no scorer restart |
| **Application restart** | `sudo systemctl restart tollgate` (or `docker compose down && up -d`) | all 5 healthy again; `/data` intact; `bootstrap` is a no-op |
| **Stale browser connection** | leave the dashboard open, `docker compose restart scorer`, watch the tab | chip -> `reconnecting`/`polling`, then `live`; state back-fills; no manual refresh needed |
| **SSE reconnect** | block `:5174` for 10 s (`sudo iptables -A INPUT -p tcp --dport 5174 -j DROP`, then delete the rule) | chip -> `polling`, ticker keeps updating via `/v1/stream/recent`; -> `live` on restore |
| **Bootstrap rerun** | `docker compose run --rm bootstrap` | exits 0, no new `policy_config` version, `TG_CONFIG_HASH` unchanged |
| **Container replacement** | `docker compose up -d --force-recreate scorer` | new container, same `/data`, `/healthz` healthy, no data loss |

**Do NOT perform against a shared/production instance:**

- `docker compose down -v` / `mkfs` on `/data` / detaching the EBS volume --
  **destroys all persisted incidents, enforcement history, and the merchant
  row**. Only on a box you own and intend to reset.
- The **Flood** demo control at sustained high concurrency on a small instance --
  it is a real load generator; it will saturate a `t3.medium`.
- Killing the instance while a replay is mid-run **and** you care about the
  scored rows for that run (they're spooled and survive, but the replay state is
  lost -- you re-Launch).
- Rotating `merchant.api_key_hash` without also updating every
  `deploy/compose.env` / secret store that feeds the frontends -- every keyed call
  then 401s (this is DEF-D9-011's failure mode).

---

## 16. Rollback

**Route A (host build):** rollback is a checkout + rebuild.

```bash
cd /opt/tollgate
git log --oneline -5                      # find the last known-good SHA (also in /data/deploy.log)
git checkout <LAST_GOOD_SHA>
docker compose -f docker-compose.yml -f deploy/aws/compose.override.yml up --build -d
docker compose ps && curl -s http://localhost:8080/healthz
```

`/data` (the DB + spool) is untouched by a code rollback -- the schema is
`CREATE TABLE IF NOT EXISTS` and the drainer resumes from its offset. If a
rollback crosses a schema change (none in Days 1-9, but for the future): take an
EBS snapshot of `/data` **before** any deploy, and restore the snapshot on
rollback.

```bash
# before every deploy:
aws ec2 create-snapshot --volume-id $VOL_ID --description "tollgate /data pre-deploy $(date -u +%F)"
```

**Route B (ECR):** redeploy the previous image **digest** (never a tag). Because
section 7 step 6 pins images by `@sha256:...`, rollback is: change the digest in
the prod compose file / task definition back to the prior one and `up -d` /
update the service. Keep a list of `{deploy time, git SHA, image digest}`.

**Make rollback easy = deploy immutable references.** Route A: a SHA. Route B: a
digest. Never "redeploy `latest` and hope".

---

## 17. Troubleshooting

| Symptom | Likely cause | How to diagnose | Fix |
|---|---|---|---|
| **`bootstrap` container exits non-zero; stack won't come up** | seed footgun (existing merchant, no matching key), or missing corpus | `docker compose logs bootstrap` -> the `[bootstrap] FATAL:` line | If "no VITE_TOLLGATE_API_KEY ... hashes to its api_key_hash": restore the original key to `deploy/compose.env`, or (fresh box) `rm /data/tollgate.db*` and re-`up`. If corpus missing: ship `data/corpus/tollgate.db` to the host (it is gitignored; `aws s3 cp` / `scp`). |
| **`scorer` unhealthy / `/healthz` no response** | event loop blocked, or crashed on startup | `docker compose logs scorer`; look for a `Traceback` or `event loop lag ... threshold` | If startup traceback: usually a missing `models/` or `config/` in the checkout, or `/data` not writable. If loop-lag: it's the AUDIT-006 class; check for a synchronous spin. |
| **Every keyed call returns `401`** (checkout, Launch, incidents) | frontends bound a stale/absent `VITE_TOLLGATE_API_KEY` (DEF-D9-011), or `merchant.api_key_hash` doesn't match | on the host: `python -c "import hashlib;print(hashlib.sha256(open('/dev/stdin').read().strip().encode()).hexdigest())" <<<"$(grep VITE_TOLLGATE_API_KEY deploy/compose.env|cut -d= -f2)"` vs `SELECT api_key_hash FROM merchant` | `docker compose up -d --force-recreate storefront dashboard` (re-sources `deploy/compose.env`). If the hash truly differs: re-seed against a fresh DB, or `UPDATE merchant SET api_key_hash=?`. |
| **Frontend loads but `/v1/...` calls fail** (network error, not 401) | Vite proxy target wrong, or the scorer isn't on the compose network | `docker compose exec storefront wget -qO- http://scorer:8080/healthz` | ensure `TOLLGATE_SCORER_URL=http://scorer:8080` and all services share the `tollgate` network |
| **SSE: dashboard chip stuck `reconnecting` / no live ticker** | a proxy is buffering the stream | `curl -N https://ops.example.com/v1/stream` from your laptop -- do you get `: ping` immediately? | Caddy: `flush_interval -1`. ALB: raise `idle_timeout`. Nginx (if added): `proxy_buffering off; proxy_cache off;`. |
| **`docker compose logs scorer` says `falling back to InMemoryWindowStore`** | Redis unreachable | `docker compose exec scorer python -c "import redis;redis.Redis.from_url('redis://redis:6379').ping()"` | fix the `redis` service / `TOLLGATE_REDIS_URL` / ElastiCache SG. In-memory works but isn't restart-durable. |
| **`GET /v1/incidents` -> 500 `unable to open database file`** | `tollgate.db` on a filesystem that can't host SQLite WAL | `docker compose exec scorer sh -c 'ls -la /data; touch /data/x && rm /data/x && echo writable'` | put `/data` on **ext4 on EBS**, not EFS/NFS, not a non-Linux bind mount (Decision 109). |
| **`scorer` log: `no store_baseline row ... Layer 2 disabled`** | `bootstrap` didn't finish `learn_store_baseline` | `docker compose exec scorer python -c "import sqlite3;print(sqlite3.connect('/data/tollgate.db').execute('SELECT COUNT(*) FROM store_baseline').fetchone())"` | `docker compose run --rm bootstrap`; check it exits 0. Ensure `data/corpus/tollgate.db` is present. |
| **`POST /v1/outcome` -> 503** | `TOLLGATE_OUTCOME_SECRET` unset | `docker compose exec scorer sh -c 'echo ${TOLLGATE_OUTCOME_SECRET:+set}'` | set it (Secrets Manager / `deploy/compose.env`); it must match `merchant.outcome_hmac_key_hash`. |
| **AWS task/service repeatedly restarting** (Fargate path) | health check failing, EFS mount failing, or the init container ordering wrong | ECS -> the task's stopped-reason; CloudWatch logs for the container | health check on `GET /healthz` expecting `200`; EFS access point perms; `dependsOn` SUCCESS on `bootstrap`. Consider section 8.1-8.7 (EC2) instead -- see section 1. |
| **Wrong image running after a deploy** | deployed a floating tag | Route A: `git rev-parse HEAD` on the host vs your intended SHA. Route B: `docker inspect` digest vs the one you pushed. | redeploy by SHA (A) / digest (B); stop using `latest`. |
| **TLS handshake fails / cert not issued** | DNS not pointing at the instance yet, or `:443`/`:80` not open | `dig shop.example.com`; `aws ec2 describe-security-groups --group-ids $SG_ID` | point DNS at `$PUBIP`; open `443` **and** `80` (ACME HTTP challenge) in the SG; `sudo journalctl -u caddy`. |
| **Out of memory / instance sluggish** | `t3.medium` too small for scorer + LightGBM + 2 Vite servers + Redis | `docker stats` on the host | move to `t3.large`; or run the frontends as static bundles (section 12) to drop two node processes. |

---

## 18. Final deployment checklist

### Local

```
[ ] docker compose config --quiet passes
[ ] docker compose down -v && docker compose up --build  -> 5 services healthy, bootstrap exit 0
[ ] production images built (tollgate-scorer / -storefront / -dashboard / -bootstrap)
[ ] scorer log: Redis connected + Layer 1 loaded + Layer 2 loaded
[ ] /healthz ok; storefront 200; dashboard 200; dashboard /v1 proxy 200
[ ] normal checkout -> 200 allow; auth_attempt + attempt_score persisted with the typed bin
[ ] full J6 walkthrough passes (launch/detect/incident/co-tenant/fault/flood/reset)
[ ] pytest tests/  -> 643 passed / 1 known-red (DEF-D9-003) / 2 xfail
[ ] vitest 205 ; playwright 68
[ ] verify_60x --gate 60x --faulthandler  9/9 ; --gate crossing PASS ; --gate throughput correctness sub-checks PASS (throughput_ok advisory)
[ ] diff_d6.py -> 0 substantive diffs
[ ] restart behaviour verified (drainer resumes, no double-write)
[ ] clean-start verified (fresh key aligns to merchant.api_key_hash, no 401)
[ ] image reference recorded: git SHA (Route A) or image digest (Route B)
```

### AWS

```
[ ] region set; aws sts get-caller-identity ok
[ ] IAM instance role + profile created (Secrets Manager read, CloudWatch)
[ ] VPC/subnet chosen; security group: 443 + 80 world, 22 my-IP only; nothing else public
[ ] key pair created; EBS data volume created
[ ] (Route B only) ECR repos created; prod Dockerfiles written + re-validated via section 4 [VERIFY BEFORE DEPLOYMENT]
[ ] EC2 instance launched (t3.large); EBS volume attached + mounted ext4 at /data
[ ] docker + compose v2 + git installed on the host
[ ] repo cloned; checked out at the TESTED SHA; data/corpus/tollgate.db shipped to the host
[ ] secrets provisioned (bootstrap-seeded once, or Secrets Manager -> deploy/compose.env before `up`)
[ ] deploy/aws/compose.override.yml maps /data:/data [VERIFY BEFORE DEPLOYMENT]
[ ] TOLLGATE_DEMO_CONTROLS set deliberately (1 = demo box; unset = production-like)
[ ] TOLLGATE_TRUSTED_EDGE_HOSTS matches the real edge (the frontend proxy container IPs)
[ ] docker compose ... up --build -d  -> 5 healthy, bootstrap exit 0
[ ] scorer log on the host: Redis connected + Layer 1 + Layer 2 loaded
[ ] Caddy/ALB: TLS issued; shop. -> :5173, ops. -> :5174; SSE not buffered (flush_interval -1 / idle_timeout >= 300)
[ ] AWS smoke test (section 14) all boxes ticked
[ ] logs inspected (section 5) -- no Traceback / loop-lag / InMemory fallback / unexpected ERROR
[ ] EBS snapshot taken (rollback baseline); systemd autostart enabled
[ ] rollback path known: `git checkout <prev SHA> && docker compose up --build -d` (A) / redeploy prior digest (B)
```

---

### What you must verify yourself before the real deployment

- **`data/corpus/tollgate.db`** (18 MB, gitignored) must reach the host by some
  means -- `git clone` will not bring it, and `bootstrap`'s `learn`/`tune` steps
  `die` without it.
- **`deploy/aws/compose.override.yml`** and any **Route B prod Dockerfiles** do
  **not** exist in the repo yet -- the shapes in section 5 and section 8.3 are
  starting points; write them and re-run section 4 against them.
- **`TOLLGATE_TRUSTED_EDGE_HOSTS`** -- the correct value depends on your exact
  proxy topology (section 8.6). Get it wrong open and XFF is spoofable; get it
  wrong closed and every storefront request collapses to one IP.
- **DNS names**, **ACM/Let's Encrypt**, **instance type**, **VPC/subnet IDs**,
  **security-group IDs**, **volume/instance IDs** -- every `<PLACEHOLDER>` and
  every shell variable in section 6-section 8 is account-specific.
- **`TOLLGATE_DEMO_CONTROLS`** -- leaving it `1` on an internet-facing box exposes
  the flood + fault-injection controls to any holder of the merchant key.
- Whether to run the **Vite dev servers** in production (Route A, simplest,
  matches the demo) or do the **static-bundle** work in section 12.

**This guide does not conclude "AWS deployment complete."** It concludes: the
container artifacts are validated locally, and the path to run that same
artifact on AWS is written and, where the repo can't back a step, marked.
