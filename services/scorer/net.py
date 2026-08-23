"""
Source: Threat Model v2 section 2 (finding K8) -- source IP is S-class: "TCP
peer address, or X-Forwarded-For hop validated against the merchant's
declared edge." IP is never read from the JSON body -- ScoreRequest declares
no `ip` field at all (packages/contracts/wire.py).
"""

from __future__ import annotations

from fastapi import Request

TRUSTED_EDGE_HOSTS = frozenset({"127.0.0.1", "::1", "testclient"})


def resolve_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in TRUSTED_EDGE_HOSTS:
        return forwarded.split(",")[0].strip()
    return peer
