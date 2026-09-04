"""
Source: remediation plan FIX-000 (AUDIT-010) -- ONE hermetic way to launch the
real scorer subprocess.

Before this module every `_spawn` helper handed the child `dict(os.environ)`.
That made the child's storage backend a function of *which tests had already
run in the parent*: `create_app()`'s lifespan calls `load_env_file()`, so the
first acceptance test to build an app put the repo-root `.env` -- including
`TOLLGATE_REDIS_URL` -- into the pytest process, and every later `_spawn`
silently promoted its subprocess from the in-memory window store to a shared
Redis DB. `test_day2_e2e` then inherited AUDIT-005's 24-hour idempotency keys
and failed in-suite while passing alone.

The fix is an explicit ALLOW-LIST plus `TOLLGATE_SKIP_DOTENV=1`:

  * no `TOLLGATE_*` variable is ever inherited -- the three `TOLLGATE_TEST_*`
    values are set here, and any backend configuration is passed by the caller
    as an explicit `extra_env`;
  * `TOLLGATE_SKIP_DOTENV=1` stops the child loading `.env` on its own, so a
    developer's local `.env` cannot change what a test measures either;
  * no narrator configuration (`NARRATOR_*` / `GEMINI_*`) is inherited, so a
    machine with a real API key runs the same suite as CI.

The allow-list itself is the OS floor: the interpreter needs these to start,
resolve DNS and open sockets on Windows. It is deliberately generous about
Windows plumbing and absolute about application configuration.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "_run_scorer_for_test.py"

# OS/interpreter plumbing only. Nothing here configures Tollgate.
ENV_ALLOWLIST = (
    # POSIX + Windows interpreter and process basics
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
    # Python-specific
    "PYTHONPATH",
    "PYTHONHASHSEED",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "VIRTUAL_ENV",
)


def hermetic_env(
    db_path: Path,
    spool_dir: Path,
    port: int,
    extra_env: Optional[Mapping[str, str]] = None,
) -> dict:
    """The complete environment for a scorer subprocess: OS plumbing, this
    test's three `TOLLGATE_TEST_*` paths, `TOLLGATE_SKIP_DOTENV=1`, and
    whatever the *test itself* chose to configure."""
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    env["TOLLGATE_SKIP_DOTENV"] = "1"
    env["TOLLGATE_TEST_DB"] = str(db_path)
    env["TOLLGATE_TEST_SPOOL"] = str(spool_dir)
    env["TOLLGATE_TEST_PORT"] = str(port)
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    return env


def spawn_scorer(
    db_path: Path,
    spool_dir: Path,
    port: int,
    extra_env: Optional[Mapping[str, str]] = None,
    capture_output: bool = False,
) -> subprocess.Popen:
    stream = subprocess.PIPE if capture_output else subprocess.DEVNULL
    return subprocess.Popen(
        [sys.executable, str(RUNNER)],
        env=hermetic_env(db_path, spool_dir, port, extra_env),
        stdout=stream,
        stderr=stream,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_health(port: int, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    last_error: Optional[BaseException] = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.1)
    raise TimeoutError(f"scorer did not become healthy in time (last error: {last_error!r})")
