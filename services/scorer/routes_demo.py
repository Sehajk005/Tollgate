"""
Source: Day 9 Plan Phase 3 -- the J6 steps 6-8 demo surface. Every route here
is INERT unless `TOLLGATE_DEMO_CONTROLS=1` (returns 404, so the surface is
invisible in production) and every one drives a REAL code path (stop
condition S-3: no faked decision / tier / availability state).

  GET  /v1/demo/cotenant-ip   step 6  -- one IP currently under enforcement
  POST /v1/demo/flood         step 7  -- start / stop a real concurrent load
  POST /v1/demo/fault         step 8  -- flip the in-scorer fault injector

Auth: `X-Tollgate-Key` via `resolve_merchant_id_cached`, exactly as /v1/score.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from packages.storage.db import connect
from services.scorer.auth import AuthBackendUnavailable, resolve_merchant_id_cached
from services.scorer.demo import DemoFloodRunner, demo_controls_enabled
from services.scorer.deps import ScorerState, get_scorer_state

router = APIRouter()


def _is_local(ip: str) -> bool:
    ip = (ip or "").strip()
    if ip in ("127.0.0.1", "::1", "localhost", ""):
        return True
    if ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                      "172.19.", "172.2", "172.30.", "172.31.", "169.254.")):
        return True
    return False


def _require_demo() -> None:
    # 404, not 403 -- when the gate is off the route does not exist.
    if not demo_controls_enabled():
        raise HTTPException(status_code=404, detail="not found")


def _require_merchant(state: ScorerState, key: Optional[str]) -> str:
    try:
        merchant_id = resolve_merchant_id_cached(state, key)
    except AuthBackendUnavailable:
        raise HTTPException(status_code=503, detail="auth backend unavailable")
    if merchant_id is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return merchant_id


# --------------------------------------------------------------------------- #
# step 6 -- CGNAT co-tenant: an IP currently under enforcement
# --------------------------------------------------------------------------- #
@router.get("/v1/demo/cotenant-ip")
def cotenant_ip(
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    _require_demo()
    merchant_id = _require_merchant(state, x_tollgate_key)

    conn = connect(state.db_path)
    try:
        rows = conn.execute(
            """
            SELECT entity_type, entity_key, expires_at
            FROM enforcement_action
            WHERE merchant_id = ? AND released_at IS NULL
            ORDER BY (incident_id IS NOT NULL) DESC, COALESCE(applied_at, 0) DESC,
                     expires_at DESC
            """,
            (merchant_id,),
        ).fetchall()
        for row in rows:
            et, ek = row["entity_type"], row["entity_key"]
            if et == "ip":
                # Skip the operator's own vantage points (loopback, the Docker
                # bridge, RFC1918) -- the co-tenant story wants an attacker IP.
                if _is_local(ek):
                    continue
                return {"ip": ek, "entity_type": "ip", "expires_at": row["expires_at"]}
            if et == "ipua":
                m = conn.execute(
                    "SELECT ip FROM auth_attempt WHERE merchant_id = ? AND ipua_key = ? "
                    "ORDER BY ingest_time DESC LIMIT 1",
                    (merchant_id, ek),
                ).fetchone()
                if m and m["ip"]:
                    return {
                        "ip": m["ip"],
                        "entity_type": "ipua",
                        "expires_at": row["expires_at"],
                    }
    finally:
        conn.close()

    raise HTTPException(
        status_code=404,
        detail="no IP is currently under enforcement -- run the attack replay first",
    )


# --------------------------------------------------------------------------- #
# step 7 -- flood toggle: a real concurrent load, not a `shed` flag
# --------------------------------------------------------------------------- #
class _FloodBody(BaseModel):
    enabled: bool


@router.post("/v1/demo/flood")
async def flood(
    body: _FloodBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    _require_demo()
    _require_merchant(state, x_tollgate_key)

    runner: Optional[DemoFloodRunner] = getattr(state, "demo_flood", None)
    if runner is None:
        runner = DemoFloodRunner()
        state.demo_flood = runner

    if body.enabled:
        try:
            runner.start()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    else:
        await runner.stop()

    return {"flood": runner.running, "sent": runner.sent, "shed_responses": runner.shed_seen}


# --------------------------------------------------------------------------- #
# step 8 -- fault injector: flips a flag; /v1/score then fails OPEN for real
# --------------------------------------------------------------------------- #
class _FaultBody(BaseModel):
    enabled: bool


@router.post("/v1/demo/fault")
def fault(
    body: _FaultBody,
    x_tollgate_key: Optional[str] = Header(default=None, alias="X-Tollgate-Key"),
    state: ScorerState = Depends(get_scorer_state),
) -> dict:
    _require_demo()
    _require_merchant(state, x_tollgate_key)
    state.demo_fault = bool(body.enabled)
    return {"fault": state.demo_fault}
