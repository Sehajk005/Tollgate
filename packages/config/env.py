r"""
Source: env-config plan -- one place that names every environment variable
the scorer reads, parses it, and loads an optional repo-root `.env` at
startup.

Design constraint: the accessors here are thin `os.environ` reads and are
NEVER cached. `eval/corpus.py` writes `NARRATOR_ENABLED` at runtime and the
narrator acceptance tests `monkeypatch.setenv` after import, so a frozen
settings object resolved once would break them. This module centralizes
names, defaults, and parsing -- the reads stay dynamic.

`load_env_file()` uses `override=False`: the real process environment always
wins over `.env`, so existing inline `KEY=val uvicorn ...` invocations and
test monkeypatching are unaffected. It is additive -- nothing here changes
how any existing value is interpreted when no `.env` is present.
"""

from __future__ import annotations

import os
from typing import Optional

# The Gemini model fallback chain, used only when neither GEMINI_MODELS nor
# the legacy single GEMINI_MODEL is set. `gemini-1.5-flash` -- the value
# hard-coded in scoring.py before this module existed -- is kept reachable
# for backwards compatibility; a current model leads it so that a retired
# primary does not make every narration silently fall back to the template.
DEFAULT_MODELS: tuple[str, ...] = ("gemini-2.0-flash", "gemini-1.5-flash")

_TRUE = {"1", "true", "yes", "on"}

_loaded = False


def load_env_file(*, force: bool = False) -> Optional[str]:
    """Load a repo-root `.env` into ``os.environ`` once. Idempotent unless
    ``force=True`` (tests). Returns the resolved path, or ``None`` when there
    was nothing to load or loading was skipped. Real environment variables
    are never overridden (``override=False``). Never raises -- a missing
    ``python-dotenv`` or a missing file is a silent no-op.
    """
    global _loaded
    if _loaded and not force:
        return None
    _loaded = True

    if os.environ.get("TOLLGATE_SKIP_DOTENV", "").strip().lower() in _TRUE:
        return None
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return None

    path = find_dotenv(usecwd=True)
    if not path:
        return None
    load_dotenv(path, override=False)
    return path


def narrator_enabled() -> bool:
    """`NARRATOR_ENABLED` -- default true; only the literal "false" disables."""
    return os.environ.get("NARRATOR_ENABLED", "true").strip().lower() != "false"


def narrator_backend() -> str:
    """`NARRATOR_BACKEND` -- default "template"."""
    return os.environ.get("NARRATOR_BACKEND", "template")


def gemini_api_key() -> str:
    """`GEMINI_API_KEY` -- empty string when unset."""
    return os.environ.get("GEMINI_API_KEY", "")


def gemini_models() -> tuple[str, ...]:
    """The Gemini model fallback chain, in order of preference.

    `GEMINI_MODELS` (comma-separated) wins; else the legacy single
    `GEMINI_MODEL` as a one-element chain (byte-for-byte the pre-existing
    behaviour); else `DEFAULT_MODELS`.
    """
    raw = os.environ.get("GEMINI_MODELS", "").strip()
    if raw:
        models = tuple(m.strip() for m in raw.split(",") if m.strip())
        if models:
            return models
    single = os.environ.get("GEMINI_MODEL", "").strip()
    if single:
        return (single,)
    return DEFAULT_MODELS


def redis_url() -> Optional[str]:
    """`TOLLGATE_REDIS_URL` -- None when unset (in-memory window store)."""
    return os.environ.get("TOLLGATE_REDIS_URL")


def outcome_secret() -> Optional[str]:
    """`TOLLGATE_OUTCOME_SECRET` -- None when unset (the /v1/outcome route
    then self-guards with a 503)."""
    return os.environ.get("TOLLGATE_OUTCOME_SECRET")


def validate_startup() -> list[str]:
    """Human-readable warnings about a misconfigured narrator, for the
    process to log at startup. Never includes the key value -- presence
    only. An empty list means nothing looks wrong.
    """
    warnings: list[str] = []
    backend = narrator_backend()
    enabled = narrator_enabled()
    has_key = bool(gemini_api_key().strip())

    known = ("template", "gemini")
    if backend not in known:
        warnings.append(
            f"NARRATOR_BACKEND={backend!r} is not a known backend "
            f"({' / '.join(known)}); a scored request will raise "
            f"NotImplementedError in the narrator path"
        )
        return warnings

    if backend == "gemini" and not enabled:
        warnings.append(
            "NARRATOR_BACKEND=gemini but NARRATOR_ENABLED=false -- the narrator "
            "is disabled; every incident uses the template"
        )
    if backend == "gemini" and enabled and not has_key:
        warnings.append(
            "NARRATOR_BACKEND=gemini but GEMINI_API_KEY is missing or blank -- "
            "the narrator will SILENTLY use the template for every incident"
        )
    if backend != "gemini" and has_key:
        warnings.append(
            f"GEMINI_API_KEY is set but NARRATOR_BACKEND is {backend!r}, not "
            "'gemini' -- the key is unused"
        )
    return warnings
