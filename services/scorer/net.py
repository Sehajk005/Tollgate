"""
Source: Threat Model v2 section 2 (finding K8) -- source IP is S-class: "TCP
peer address, or X-Forwarded-For hop validated against the merchant's
declared edge." IP is never read from the JSON body -- ScoreRequest declares
no `ip` field at all (packages/contracts/wire.py).

Day 9 Plan Phase 2: under Docker the storefront/dashboard reach the scorer
through a Vite proxy container whose bridge IP is none of the loopback hosts
below, so without configuration every storefront request would collapse to one
container IP. `TOLLGATE_TRUSTED_EDGE_HOSTS` (comma-separated) lets the operator
declare that edge -- exactly Threat Model K8's "validated against the merchant's
declared edge". It is ADDITIVE to the built-in loopback set and defaults to
empty, so behaviour off-Docker is byte-identical.
"""

from __future__ import annotations

import os

from fastapi import Request

# The built-in edge: the manual path (uvicorn on the host) and the test client.
_DEFAULT_TRUSTED_EDGE_HOSTS = frozenset({"127.0.0.1", "::1", "testclient"})


def _load_trusted_edge_hosts() -> frozenset:
    extra = os.environ.get("TOLLGATE_TRUSTED_EDGE_HOSTS", "")
    hosts = {h.strip() for h in extra.split(",") if h.strip()}
    return _DEFAULT_TRUSTED_EDGE_HOSTS | hosts


# Resolved once at import (matches the previous module-constant semantics).
# Tests that need a different edge set the env var and reload this module, or
# monkeypatch this name directly.
TRUSTED_EDGE_HOSTS = _load_trusted_edge_hosts()


def resolve_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in TRUSTED_EDGE_HOSTS:
        return forwarded.split(",")[0].strip()
    return peer
