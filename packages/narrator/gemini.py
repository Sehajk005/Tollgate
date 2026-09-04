r"""
Source: Day-8 Plan Step 9 -- the Gemini narrator backend. A drop-in behind
`NARRATOR_BACKEND=gemini`, dispatched OUT OF BAND (never inside
`_resolve_layer2`, never in the scoring hot path -- Day-7 R3 / trap 9). The
template narrative is always written first and is the always-available
fallback; this module only ever REPLACES it on success.

This module does the HTTP + candidate-text extraction only. It raises
`GeminiError(reason)` for an HTTP or network fault; the caller
(`services/scorer/scoring.py::_run_gemini_narration`) does the JSON / shape /
charset / 600-char validation and decides whether to keep the LLM text or
fall back.

Threat Model SS5: the ONLY thing sent to Gemini is `assemble_prompt(bundle)`,
which is already charset-gated and built from a closed vocabulary -- no raw
identifier, no `user_agent`, no C-class value can reach the request body.
`build_request_body` is exported so `test_narrator_injection.py` can scan the
exact bytes that would be dispatched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-1.5-flash"
# The in-order fallback chain used when the caller does not pass an explicit
# `models=`. Kept in sync with packages/config/env.DEFAULT_MODELS -- that
# module is the configuration authority; this is the transport-layer default
# for a direct call_gemini() with neither `model` nor `models` given.
DEFAULT_MODELS: tuple[str, ...] = ("gemini-2.0-flash", "gemini-1.5-flash")
# Only these HTTP statuses advance the chain to the next model. A 429, a
# timeout, a connection error, or any other non-200 raises immediately and
# is handled as a single failed narration attempt by the caller -- turning
# them into retries would break the "exactly one narrator_call row" contract.
_ADVANCE_STATUSES = (400, 404)
DEFAULT_TIMEOUT_S = 8.0
MAX_OUTPUT_TOKENS = 512


class GeminiError(Exception):
    """An HTTP or transport fault. `reason` is a short, log-safe token:
    `http_429` / `http_<code>` / `timeout` / `connection` / `bad_response`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GeminiResponse:
    text: str          # the model's raw output (which we asked to be JSON)
    latency_ms: int    # total wall-clock across every model tried
    model: str = ""    # the model that actually served the 200 (for logging)


def build_request_body(prompt: str) -> dict:
    """The exact JSON body dispatched to Gemini. `prompt` is the only free
    string, and it is `assemble_prompt(bundle)` -- closed vocabulary, charset
    gated. Nothing else is attacker-reachable."""
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }


async def call_gemini(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    models: Optional[Sequence[str]] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    transport=None,
) -> GeminiResponse:
    """POST the prompt, return the candidate text + total latency + the model
    that served it. `transport` is an injected `httpx` transport (tests pass
    `httpx.MockTransport`).

    `models` is an in-order fallback chain: on an HTTP 400/404 (model retired
    or unknown) the next model is tried. Every other fault -- 429, timeout,
    connection, any other non-200, an unparseable body -- raises immediately,
    so one call_gemini() invocation is still one narration attempt. When
    `models` is omitted the single `model` is used, byte-for-byte the prior
    behaviour.
    """
    chain = [m for m in (list(models) if models else [model]) if m]
    if not chain:
        chain = [DEFAULT_MODEL]
    body = build_request_body(prompt)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    advanceable: Optional[GeminiError] = None

    async with httpx.AsyncClient(transport=transport, timeout=timeout_s) as client:
        for i, name in enumerate(chain):
            url = GEMINI_URL.format(model=name)
            try:
                resp = await client.post(url, params={"key": api_key}, json=body)
            except httpx.TimeoutException as exc:
                raise GeminiError("timeout") from exc
            except httpx.TransportError as exc:
                raise GeminiError("connection") from exc

            if resp.status_code == 200:
                latency_ms = int((loop.time() - t0) * 1000)
                try:
                    payload = resp.json()
                    text = payload["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise GeminiError("bad_response") from exc
                return GeminiResponse(text=str(text), latency_ms=latency_ms, model=name)

            if resp.status_code == 429:
                raise GeminiError("http_429")
            if resp.status_code in _ADVANCE_STATUSES and i < len(chain) - 1:
                advanceable = GeminiError(f"http_{resp.status_code}")
                continue
            raise GeminiError(f"http_{resp.status_code}")

    raise advanceable if advanceable is not None else GeminiError("bad_response")
