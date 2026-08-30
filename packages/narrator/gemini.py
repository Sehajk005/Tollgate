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

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-1.5-flash"
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
    latency_ms: int


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
    timeout_s: float = DEFAULT_TIMEOUT_S,
    transport=None,
) -> GeminiResponse:
    """POST the prompt, return the candidate text + call latency. `transport`
    is an injected `httpx` transport (tests pass `httpx.MockTransport`)."""
    url = GEMINI_URL.format(model=model)
    body = build_request_body(prompt)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout_s) as client:
            resp = await client.post(url, params={"key": api_key}, json=body)
    except httpx.TimeoutException as exc:
        raise GeminiError("timeout") from exc
    except httpx.TransportError as exc:
        raise GeminiError("connection") from exc
    latency_ms = int((loop.time() - t0) * 1000)

    if resp.status_code == 429:
        raise GeminiError("http_429")
    if resp.status_code != 200:
        raise GeminiError(f"http_{resp.status_code}")

    try:
        payload = resp.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeminiError("bad_response") from exc

    return GeminiResponse(text=str(text), latency_ms=latency_ms)
