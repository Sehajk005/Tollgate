# Day 9 — Phase 0 Baseline Snapshot

**Captured:** 2026-09-03
**Executed by:** Day 9 Session 1 (Phases 0–3), executing `09-DAY-9-QA-AND-DEMO-PLAN.md`
**Purpose:** freeze the exact state of the repository and machine before any Day 9
change, so the baseline SHA describes the code actually under test (Plan §0, Phase 0).

---

## 1. Git

| Item | Value |
|---|---|
| Branch before Day 9 | `day-2` |
| HEAD before Day 9 | `8cf17d9121d76ba22b42975bcbc88dfde5cc0eac` (`spec: Day 8 implementation complete`) |
| New branch | `day-9` (created from `day-2` HEAD) |
| **Day 9 baseline SHA** | **`5a43e0c61fc19f497ce739d4053cfd16d186d55d`** (`spec: Day 9 baseline -- untested Day-8 + remediation working tree`) |
| Working tree after baseline commit | clean |

### Working-tree contents committed unmodified into the baseline

55 modified tracked files + 64 untracked entries → **137 files changed, +25,488 / −1,162**.

Categories:
- Day 1–8 implementation as left at `day-2` HEAD (55 modified tracked files: `eval/`,
  `packages/`, `services/scorer/`, `services/dashboard/`, `services/storefront/`,
  `tests/acceptance/`, `Decisions.md`, `Flow.md`, `README.md`, `.gitignore`).
- **AUDIT-001..024** remediation of `QA-AUDIT-2026-09-01.md`.
  Source: `~/.claude/plans/https-claude-ai-code-artifact-c352b401-a-sprightly-seal.md`
  (outside the repo; 146 `FIX-0` references; `FIX-003 (AUDIT-001)`, `FIX-016 (AUDIT-017)`,
  `FIX-020 (AUDIT-023)` visible as source comments).
- **M-001..040** D6 metrics remediation.
  Source: `METRICS-REMEDIATION-PLAN-2026-09-02.md` (in-repo, now tracked).
  Evidence: `METRICS-IMPLEMENTATION-LOG-2026-09-02.md`,
  `METRICS-AUDIT-VERIFICATION-2026-09-02.md` (claims 40 FIXED / 0 retained).
- New scripts: `scripts/verify_60x.py`, `scripts/diff_d6.py`, `eval/d6_schema.py`.
- ~60 new dashboard components / tests / fixtures (`services/dashboard/src/components/metrics/*`,
  `src/lib/*`, `src/__fixtures__/*`, `e2e/`, `playwright.config.js`, `vitest.config.js`) and
  new acceptance tests (`tests/acceptance/test_replay_*`, `test_d6_*`, `test_layer2_*`, …).

### `.gitignore` delta (non-substantive)

```diff
+*.timestamp-*.mjs          # transient Vite/Vitest ESM shim, never source
+.verify60x/                # scripts/verify_60x.py scratch output
```

### Commit-message hook note

Repo enforces (`Impl Plan v2.1 §1.8`): any change under `tests/acceptance/**` needs a
`spec:` commit-message prefix. Baseline commit therefore titled
`spec: Day 9 baseline -- …`. Hook respected, not bypassed (`--no-verify` is also blocked
by a `PreToolUse` guard). Every prior repo commit uses the same `spec:` convention.

---

## 2. Machine / toolchain (matches Plan §3 "Verified present")

| Tool | Version | Plan §3 expected |
|---|---|---|
| Python | 3.13.3 | 3.13.3 ✓ |
| Node | v22.14.0 | v22.14.0 ✓ |
| npm | 11.7.0 | 11.7.0 ✓ |
| uv | 0.11.0 | 0.11.0 ✓ |
| Docker | 29.1.3 (build f52814d) | 29.1.3 ✓ |
| Docker Compose | v2.40.3-desktop.1 | v2.40.3-desktop.1 ✓ |

OS: Windows 11 Home Single Language 10.0.26200. Shell: Git Bash + PowerShell.

---

## 3. `.env` (secrets redacted)

| Key | Value |
|---|---|
| `NARRATOR_BACKEND` | `template` |
| `GEMINI_API_KEY` | `<set>` (redacted) |
| `GEMINI_MODELS` | `gemini-2.0-flash,gemini-1.5-flash` |
| `NARRATOR_ENABLED` | `true` |
| `TOLLGATE_REDIS_URL` | `redis://localhost:6379` |
| `TOLLGATE_OUTCOME_SECRET` | `<set>` (redacted) |

`.env` is gitignored (`# Environment / secrets` block). Not committed. Both frontend
`.env` files and all three `node_modules` present (Plan §3).

---

## 4. Redis state

| Instance | Port | Ping | Notes |
|---|---|---|---|
| `tollgate-redis-1` (`redis:7-alpine`) | 6379 | `PONG` | up ~2 h, from existing `docker-compose.yml`; db0 `dbsize` = 2004 (leftover keys from prior manual runs); **db9 `dbsize` = 0** (clean — `verify_60x` target) |
| `tollgate-redis-small-1` (`redis:7-alpine`) | 6380 | `PONG` | up ~2 h; 2 MB maxmemory, `allkeys-lru` — eviction test only |

Other containers on host (unrelated, all `Exited`): `charming_dewdney`, `cosdata-server`,
`my-redis`.

Existing `docker-compose.yml` defines **only** `redis` + `redis-small` — no `scorer`,
`dashboard`, `storefront`, or `bootstrap` service; **zero `Dockerfile*` in the repo**
(reconciliation finding R-1; Phase 2 builds these).

---

## 5. `tollgate.db` (host-side, gitignored — 14,110,720 bytes)

| Table | Rows |
|---|---|
| `merchant` | 1 |
| `attempt_score` | 6,340 |
| `incident` | 8 |
| `policy_config` | 7 |
| `store_baseline` | 1 |
| `episode_truth` | 0 |
| `attempt_label` | 0 |

All 17 schema tables present: `attempt_label, attempt_score, auth_attempt, auth_outcome,
bin_metadata, cost_model_config, enforcement_action, episode_truth, eval_run, incident,
incident_entity, merchant, narrator_call, outcome_nonce, policy_config, store_baseline,
tier_transition`.

`merchant`=1 + `store_baseline`=1 + `policy_config`=7 ⇒ Layer 2 state exists on the host
DB. The `seed_merchant` `INSERT OR IGNORE` footgun (Plan Phase 2 bootstrap row) is live
here — a re-`seed_merchant` would print a dead key. Relevant to Phase 2 bootstrap design,
not Phase 0.

---

## 6. Frozen artifact SHA-256 (stop condition S-6 on any change)

| File | SHA-256 | Size |
|---|---|---|
| `eval/outputs/d6.json` | `29edcb2256c2fd744ca40fdec5198a28cbdf5ef2ab3c80279c0614a5a9989737` | (tracked) |
| `models/audit.json` | `ce75cb7fa41a209df9f0e373b6640c976c28fb99d714703fb064f8e091f0b53c` | 5,967 B |
| `models/l1-lgbm-v1.json` | `7cb7fa8a187129bb300147d97ca97354cf52b9d944065da8a4669f42de5b66cc` | 1,844 B |
| `models/platt-v1.json` | `22dc48f0a47db1447862781d241d641d7e5145c6ea94bc9fd1f64d5c7b508864` | 188 B |

Plan §Phase 0 "SHAs to honour": `d6.json` = `29edcb22…` ✓, `models/audit.json` =
`ce75cb7f…` ✓ — both confirmed matching.

`models/l1-lgbm-v1.txt` (221,683 B) also present. `data/corpus/tollgate.db` =
**18,374,656 bytes** (~18 MB, gitignored — Plan §3 "18 MB"). `data/corpus/spool/` present.

`config/`: `attack_tiers.yaml, cost_model.yaml, features.yaml, policy.yaml, rules.yaml,
store_profile.yaml`.

---

## 7. Reconciliation items confirmed against the repo (Plan §0)

| ID | Plan claim | Confirmed at baseline |
|---|---|---|
| R-1 | `docker compose up` unimplemented; no Dockerfiles | ✓ `docker-compose.yml` = redis + redis-small only; `find -iname 'Dockerfile*'` → 0 |
| R-2 | J6 steps 6–8 unbuilt | pending Phase 3 inspection |
| R-3 | AUDIT-001..024 remediation has no in-repo evidence log | ✓ remediation-plan source is outside the repo; no in-repo verification doc |
| R-4 | D6 remediation more complete than brief assumes | ✓ `METRICS-AUDIT-VERIFICATION-2026-09-02.md` present, claims 40/40 |
| R-5 | `/v1/stream` unauthenticated; outcome-derived features read 0.0 | pending Phase 6 / Phase 5 verification |

---

## 8. Phase 0 status

**COMPLETE.**

- [x] Baseline data recorded (this file)
- [x] `git checkout -b day-9` from `day-2`
- [x] Working tree committed unmodified → baseline SHA `5a43e0c`
- [x] `09-DAY-9-QA-AND-DEMO-PLAN.md` written to repo root (byte-identical to
      `~/.claude/plans/day-9-idempotent-lemur.md`, SHA-256 `51bb6607…`)
- [x] `evidence/day-9/` created

**Next:** Phase 1 — baseline test matrix, README manual path, nothing modified.
