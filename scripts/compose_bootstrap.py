"""
python -m scripts.compose_bootstrap

Source: Day 9 Plan Phase 2 -- the one-shot `bootstrap` service. It performs the
three real bootstrap steps the scorer needs before it can serve the full path:

    1. seed_merchant          -- merchant row + API key + outcome HMAC secret
    2. learn_store_baseline   -- store_baseline row (Layer 2 will not load without it)
    3. tune_cusum             -- policy_config with populated `thresholds` + tuned cusum_h

and writes the D6 config hash for the dashboard (Plan Phase 2 "D6 freshness under
Docker"). It is IDEMPOTENT and it handles the known `INSERT OR IGNORE` footgun:
`scripts.seed_merchant` prints a fresh key every run but only stores it when the
merchant row did not already exist, so a naive re-run prints a DEAD key and every
request 401s. This script never does that -- it either reuses a verified key or
fails loudly.

Everything is relative to CWD, which the compose file sets to the repo root
(bind-mounted). Writes ONLY:
  - <TG_BOOTSTRAP_ENV_FILE>  (default deploy/compose.env, gitignored) -- the
    env_file the scorer / dashboard / storefront read.
  - tollgate.db               (bind-mounted host DB) -- via the sub-scripts.

Exit codes: 0 success/no-op, 1 loud failure (never a dead key, never a silent
half-bootstrap).
"""

from __future__ import annotations

import os
import re
import sqlite3
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# TOLLGATE_DB_PATH: the Compose stack points the mutable demo DB at a
# Linux-native volume (SQLite WAL cannot mmap -shm over a Windows bind mount).
# The sub-scripts inherit this env var; learn/tune also get it as --demo-db.
DEMO_DB = Path(os.environ.get("TOLLGATE_DB_PATH") or (REPO / "tollgate.db"))
SCHEMA = REPO / "schema.sql"
_CORPUS_SRC = REPO / "data" / "corpus" / "tollgate.db"
# tune_cusum writes tuned policy_config versions back into its --db. To keep the
# bind-mounted 18 MB reference corpus byte-stable (stop condition S-6's spirit),
# learn/tune run against a working COPY on the volume when TOLLGATE_DB_PATH is
# set (the container); the manual path is unchanged.
_CORPUS_WORK = (DEMO_DB.parent / "corpus.db") if os.environ.get("TOLLGATE_DB_PATH") else _CORPUS_SRC
CORPUS_DB = _CORPUS_WORK
MERCHANT_ID = "merchant_demo"

ENV_FILE = Path(os.environ.get("TG_BOOTSTRAP_ENV_FILE", REPO / "deploy" / "compose.env"))
FORCE = os.environ.get("TG_BOOTSTRAP_FORCE", "").strip().lower() in {"1", "true", "yes", "on"}

# Candidate places an already-issued key/secret may live, in priority order.
KEY_SOURCES = (
    ENV_FILE,
    REPO / "services" / "dashboard" / ".env",
    REPO / "services" / "storefront" / ".env",
    REPO / ".env",
)


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[bootstrap] FATAL: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def read_env_values(path: Path) -> dict:
    """Parse a KEY=VALUE file (dotenv-ish). Missing file -> {}."""
    out: dict = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env_file(values: dict) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = read_env_values(ENV_FILE)
    existing.update({k: v for k, v in values.items() if v is not None})
    body = "# Written by scripts.compose_bootstrap -- gitignored. Do not commit.\n"
    for k in sorted(existing):
        body += f"{k}={existing[k]}\n"
    ENV_FILE.write_text(body, encoding="utf-8")
    log(f"wrote env file ({', '.join(sorted(values))})")


def run(mod: str, *args: str) -> str:
    cmd = [sys.executable, "-m", mod, *args]
    log("run: " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        die(f"{mod} exited {proc.returncode}")
    return proc.stdout


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DEMO_DB)
    conn.row_factory = sqlite3.Row
    return conn


def merchant_row():
    if not DEMO_DB.exists():
        return None
    conn = db_conn()
    try:
        try:
            return conn.execute(
                "SELECT api_key_hash, outcome_hmac_key_hash FROM merchant WHERE merchant_id = ?",
                (MERCHANT_ID,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # table not created yet
    finally:
        conn.close()


def latest_policy_thresholds():
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT thresholds FROM policy_config WHERE merchant_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (MERCHANT_ID,),
        ).fetchone()
        return row["thresholds"] if row else None
    finally:
        conn.close()


def has_store_baseline() -> bool:
    conn = db_conn()
    try:
        return conn.execute(
            "SELECT 1 FROM store_baseline WHERE merchant_id = ?", (MERCHANT_ID,)
        ).fetchone() is not None
    finally:
        conn.close()


def _grep(text: str, pattern: str):
    m = re.search(pattern, text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Step 1 -- seed_merchant, footgun-safe
# --------------------------------------------------------------------------- #
def ensure_merchant() -> None:
    from services.scorer.auth import hash_api_key

    row = merchant_row()

    if row is None:
        log(f"no {MERCHANT_ID} row -- seeding")
        out = run("scripts.seed_merchant")
        key = _grep(out, r"API key \(store this[^:]*\):\s*(\S+)")
        secret = _grep(out, r"Outcome HMAC secret \(store this[^:]*\)[^:]*:\s*(\S+)")
        if not key or not secret:
            die("seed_merchant did not print a key/secret in the expected format")
        row = merchant_row()
        if row is None or hash_api_key(key) != row["api_key_hash"]:
            die("seeded key does not hash to the stored merchant row -- aborting")
        write_env_file({"VITE_TOLLGATE_API_KEY": key, "TOLLGATE_OUTCOME_SECRET": secret})
        log("merchant seeded; key + secret written to the env file")
        return

    log(f"{MERCHANT_ID} already exists -- looking for a matching key on file")
    for src in KEY_SOURCES:
        vals = read_env_values(src)
        cand = vals.get("VITE_TOLLGATE_API_KEY") or vals.get("TOLLGATE_API_KEY")
        if cand and hash_api_key(cand) == row["api_key_hash"]:
            secret = vals.get("TOLLGATE_OUTCOME_SECRET")
            ok_secret = bool(secret) and hash_api_key(secret) == row["outcome_hmac_key_hash"]
            if not ok_secret:
                for s2 in KEY_SOURCES:
                    v2 = read_env_values(s2).get("TOLLGATE_OUTCOME_SECRET")
                    if v2 and hash_api_key(v2) == row["outcome_hmac_key_hash"]:
                        secret, ok_secret = v2, True
                        break
            rel = src.relative_to(REPO) if src.is_relative_to(REPO) else src
            log(f"reusing verified key from {rel}"
                + ("" if ok_secret else "  (WARNING: no matching outcome secret -- "
                                        "POST /v1/outcome will 503; core demo unaffected)"))
            payload = {"VITE_TOLLGATE_API_KEY": cand}
            if ok_secret:
                payload["TOLLGATE_OUTCOME_SECRET"] = secret
            write_env_file(payload)
            return

    die(
        f"{MERCHANT_ID} exists in {DEMO_DB.name} but no VITE_TOLLGATE_API_KEY on file "
        "hashes to its api_key_hash. Checked: "
        + ", ".join(str(s) for s in KEY_SOURCES)
        + ". Fix: restore the original key to one of those files, or "
        f"`rm {DEMO_DB.name}` (and its -shm/-wal) and re-run for a fresh seed. "
        "Refusing to print a dead key."
    )


# --------------------------------------------------------------------------- #
# Step 2 -- learn_store_baseline (idempotent: INSERT ... ON CONFLICT DO UPDATE)
# --------------------------------------------------------------------------- #
def ensure_store_baseline() -> None:
    if has_store_baseline() and not FORCE:
        log("store_baseline row present -- skipping learn_store_baseline (TG_BOOTSTRAP_FORCE=1 to re-run)")
        return
    if not CORPUS_DB.exists():
        die(f"{CORPUS_DB} missing -- learn_store_baseline needs the negative-control corpus")
    run("scripts.learn_store_baseline", "--db", str(CORPUS_DB), "--demo-db", str(DEMO_DB))
    if not has_store_baseline():
        die("learn_store_baseline ran but no store_baseline row for merchant_demo")


# --------------------------------------------------------------------------- #
# Step 3 -- tune_cusum (guarded so it does not append a new policy_config
# version on every `docker compose up`)
# --------------------------------------------------------------------------- #
def ensure_tuned_policy() -> None:
    thr = latest_policy_thresholds()
    tuned = bool(thr) and thr.strip() not in ("", "{}")
    if tuned and not FORCE:
        log(f"latest policy_config already tuned (thresholds={thr[:40]}...) -- skipping tune_cusum")
        return
    if not CORPUS_DB.exists():
        die(f"{CORPUS_DB} missing -- tune_cusum needs the negative-control corpus")
    run("scripts.tune_cusum", "--db", str(CORPUS_DB), "--demo-db", str(DEMO_DB))
    thr = latest_policy_thresholds()
    if not (thr and thr.strip() not in ("", "{}")):
        die("tune_cusum ran but the latest policy_config still has empty thresholds")


# --------------------------------------------------------------------------- #
# Step 4 -- D6 config hash for the dashboard
# --------------------------------------------------------------------------- #
def write_config_hash() -> None:
    try:
        from eval.provenance import config_hash

        h = config_hash()
    except Exception as exc:  # noqa: BLE001
        log(f"WARNING: could not compute config_hash ({exc!r}); dashboard will render "
            "'freshness not verifiable in this build'")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", h or ""):
        log(f"WARNING: config_hash returned {h!r}, not a 64-hex digest -- skipping")
        return
    write_env_file({"TG_CONFIG_HASH": h})
    log(f"TG_CONFIG_HASH={h}")


def ensure_corpus_working_copy() -> None:
    """When running containerized, learn/tune operate on a COPY of the corpus so
    the bind-mounted 18 MB reference DB stays byte-stable (see _CORPUS_WORK)."""
    if _CORPUS_WORK == _CORPUS_SRC:
        return
    if not _CORPUS_SRC.exists():
        die(f"{_CORPUS_SRC} missing -- learn/tune need the negative-control corpus")
    need_copy = (
        not _CORPUS_WORK.exists()
        or _CORPUS_WORK.stat().st_size != _CORPUS_SRC.stat().st_size
        or FORCE
    )
    if need_copy:
        _CORPUS_WORK.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = _CORPUS_SRC.with_name(_CORPUS_SRC.name + suffix)
            dst = _CORPUS_WORK.with_name(_CORPUS_WORK.name + suffix)
            if src.exists():
                shutil.copy2(src, dst)
            elif dst.exists():
                dst.unlink()
        log(f"copied reference corpus -> {_CORPUS_WORK} ({_CORPUS_WORK.stat().st_size} bytes)")
    else:
        log("corpus working copy already present -- reusing")


def main() -> None:
    log(f"repo={REPO}  env_file={ENV_FILE}  force={FORCE}")
    if not DEMO_DB.exists():
        log(f"{DEMO_DB.name} absent -- initializing schema")
        from packages.storage.db import initialize_schema

        initialize_schema(DEMO_DB, SCHEMA)
    ensure_merchant()
    ensure_corpus_working_copy()
    ensure_store_baseline()
    ensure_tuned_policy()
    write_config_hash()
    log("bootstrap complete")


if __name__ == "__main__":
    main()
