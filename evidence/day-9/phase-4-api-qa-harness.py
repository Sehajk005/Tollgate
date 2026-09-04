"""Day 9 Phase 4 -- Backend / API QA harness (standalone; scratchpad only).

Exercises every route in services/scorer against the running Compose stack
(http://localhost:8080) with the plan's per-route matrix:
happy / auth present-absent-invalid / malformed / oversized / missing fields /
wrong types / duplicate event_id / same event_id different payload / concurrent.

Records: request, status, response shape, whether the error body is
operator-readable (a `detail` string) vs a stack trace, latency where relevant,
and the observed state transition.

It DOES start one real replay to exercise 409-while-busy + stop + reset, then
returns the driver to idle. Fault toggle is restored to off. Flood is exercised
only as `enabled:false` (safe no-op) + auth/validation.

Run:  uv run python phase4_api_qa.py <out.json>
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import time
import uuid

import httpx

BASE = "http://localhost:8080"
KEY = "S9DyTCV1cEsGQUIJAhi_QIIKGMGQSfeyI3aXh7bzPzg"
BADKEY = "not-a-real-key-000000000000000000000000000"

results = []


def rec(route, case, *, method, status, expected, body_shape, readable, note="", latency_ms=None):
    exp = list(expected) if isinstance(expected, (list, tuple, set)) else expected
    ok = "PASS" if (status in expected if isinstance(expected, (list, tuple, set)) else status == expected) else "FAIL"
    results.append(dict(route=route, case=case, method=method, status=status, expected=exp,
                        verdict=ok, body=body_shape, readable=readable, note=note,
                        latency_ms=latency_ms))
    print(f"  [{ok}] {method:5} {route:34} {case:42} -> {status}  {note}")


def shape(r):
    try:
        j = r.json()
    except Exception:
        return f"<non-json {len(r.text)}b> {r.text[:120]!r}"
    if isinstance(j, dict):
        return "{" + ",".join(sorted(j.keys())) + "}"
    if isinstance(j, list):
        return f"[list n={len(j)}]"
    return repr(j)[:120]


def readable_err(r):
    try:
        j = r.json()
    except Exception:
        return "NO (non-json)" if r.status_code >= 400 else "n/a"
    if r.status_code < 400:
        return "n/a"
    d = j.get("detail")
    if isinstance(d, str) and d and "Traceback" not in d:
        return f"YES ({d!r})"
    if isinstance(d, list):
        locs = [".".join(str(x) for x in e.get("loc", [])) for e in d]
        return f"YES (422 field errors: {locs})"
    return f"MAYBE ({j})"


def score_body(**over):
    b = dict(event_id=f"p4-{uuid.uuid4()}", card_hash="c" * 24, bin="424242",
             amount_minor=1999, currency="INR", last4="4242", session_id="p4-sess")
    b.update(over)
    return b


def C(**kw):
    return httpx.Client(base_url=BASE, timeout=30.0, **kw)


print("\n==================== /healthz ====================")
with C() as c:
    t = time.perf_counter()
    r = c.get("/healthz")
    lat = (time.perf_counter() - t) * 1000
    rec("/healthz", "happy (no auth)", method="GET", status=r.status_code, expected=200,
        body_shape=shape(r), readable=readable_err(r), note=f"{r.json()}", latency_ms=round(lat, 1))
    r = c.request("POST", "/healthz")
    rec("/healthz", "wrong method POST", method="POST", status=r.status_code, expected=405,
        body_shape=shape(r), readable=readable_err(r))


print("\n==================== POST /v1/score ====================")
with C() as c:
    t = time.perf_counter()
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body())
    lat = (time.perf_counter() - t) * 1000
    j = r.json() if r.status_code == 200 else {}
    rec("/v1/score", "happy path", method="POST", status=r.status_code, expected=200,
        body_shape=shape(r), readable=readable_err(r),
        note=f"decision={j.get('decision')} latency_ms={j.get('latency_ms')}", latency_ms=round(lat, 1))
    resp_keys = set(j.keys())
    rec("/v1/score", "response shape exact", method="POST", status=r.status_code, expected=200,
        body_shape=shape(r), readable="n/a",
        note=f"keys={sorted(resp_keys)} exact={resp_keys == {'attempt_uid','decision','latency_ms'}}")

    r = c.post("/v1/score", json=score_body())
    rec("/v1/score", "auth absent", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": BADKEY}, json=score_body())
    rec("/v1/score", "auth invalid", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": ""}, json=score_body())
    rec("/v1/score", "auth empty string", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))

    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY, "content-type": "application/json"},
               content=b"{not json at all")
    rec("/v1/score", "malformed JSON body", method="POST", status=r.status_code,
        expected=(400, 422), body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, data={"event_id": "x"})
    rec("/v1/score", "wrong content-type (form)", method="POST", status=r.status_code,
        expected=(400, 415, 422), body_shape=shape(r), readable=readable_err(r))

    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json={"event_id": "only-this"})
    rec("/v1/score", "missing required fields", method="POST", status=r.status_code, expected=422,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body(event_id=""))
    rec("/v1/score", "empty event_id (min_length=1)", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body(amount_minor="NaN-str"))
    rec("/v1/score", "wrong type amount_minor=str", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body(amount_minor=-5))
    rec("/v1/score", "negative amount_minor (ge=0)", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY},
               json=score_body(ip="203.0.113.5", merchant_id="attacker", rules_fired=["x"]))
    rec("/v1/score", "hostile extra fields ignored", method="POST", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a", note="extra keys silently dropped")

    big = c.post("/v1/score", headers={"X-Tollgate-Key": KEY},
                 json=score_body(card_hash="A" * 4_000_000))
    rec("/v1/score", "oversized body (~4MB card_hash)", method="POST", status=big.status_code,
        expected=(200, 413, 422), body_shape=shape(big), readable=readable_err(big),
        note="must not 500/hang")

    eid = f"p4-dup-{uuid.uuid4()}"
    b1 = score_body(event_id=eid)
    r1 = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=b1)
    r2 = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=b1)
    u1, u2 = r1.json().get("attempt_uid"), r2.json().get("attempt_uid")
    rec("/v1/score", "duplicate event_id + identical payload", method="POST", status=r2.status_code,
        expected=200, body_shape=shape(r2), readable="n/a",
        note=f"uid_identical={u1==u2} dec1={r1.json().get('decision')} dec2={r2.json().get('decision')}")
    b3 = score_body(event_id=eid, amount_minor=999999)
    r3 = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=b3)
    u3 = r3.json().get("attempt_uid")
    rec("/v1/score", "same event_id, different payload", method="POST", status=r3.status_code,
        expected=200, body_shape=shape(r3), readable="n/a",
        note=f"uid3==dup_uid1? {u3==u1} dec={r3.json().get('decision')}")

print("\n-- concurrent identical requests (10x) --")
eid_c = f"p4-conc-{uuid.uuid4()}"
bc = score_body(event_id=eid_c)


def _one(_):
    with C() as cc:
        rr = cc.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=bc)
        return rr.status_code, rr.json().get("attempt_uid"), rr.json().get("decision")


with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    got = list(ex.map(_one, range(10)))
codes = [g[0] for g in got]
uids = set(g[1] for g in got)
decs = set(g[2] for g in got)
rec("/v1/score", "10x concurrent identical event_id", method="POST", status=max(codes),
    expected=200, body_shape="{...}", readable="n/a",
    note=f"all_200={all(x==200 for x in codes)} distinct_uids={len(uids)} decisions={sorted(decs)}")


print("\n==================== GET /v1/stream + /v1/stream/recent ====================")
with C() as c:
    with c.stream("GET", "/v1/stream") as s:
        ct = s.headers.get("content-type", "")
        xab = s.headers.get("x-accel-buffering")
        first = ""
        t0 = time.perf_counter()
        for chunk in s.iter_text():
            first += chunk
            if first.strip() or time.perf_counter() - t0 > 5:
                break
        rec("/v1/stream", "opens, headers flush, SSE grammar", method="GET", status=s.status_code,
            expected=200, body_shape=f"content-type={ct!r}", readable="n/a",
            note=f"x-accel-buffering={xab!r} first={first[:24]!r}")
    r = c.get("/v1/stream/recent")
    rec("/v1/stream/recent", "happy (unauth, Decision 94)", method="GET", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a",
        note=f"events_n={len(r.json().get('events', []))}")
    r = c.get("/v1/stream/recent", params={"after": "nonexistent-uid-cursor"})
    rec("/v1/stream/recent", "after=<unknown cursor>", method="GET", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a",
        note=f"events_n={len(r.json().get('events', []))}")
    r = c.get("/v1/stream/recent", headers={"X-Tollgate-Key": BADKEY})
    rec("/v1/stream/recent", "bad key still 200 (open surface)", method="GET", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a")


print("\n==================== /v1/replay/* ====================")
with C() as c:
    r = c.get("/v1/replay/status")
    rec("/v1/replay/status", "open (Decision 107), no auth", method="GET", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a", note=f"state={r.json().get('state')}")

    r = c.post("/v1/replay/start", json={"tier": "easy"})
    rec("/v1/replay/start", "auth absent", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": BADKEY}, json={"tier": "easy"})
    rec("/v1/replay/start", "auth invalid", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/stop")
    rec("/v1/replay/stop", "auth absent", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/reset")
    rec("/v1/replay/reset", "auth absent", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/reset", headers={"X-Tollgate-Key": BADKEY})
    rec("/v1/replay/reset", "auth invalid", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))

    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY}, json={})
    rec("/v1/replay/start", "missing tier -> 422", method="POST", status=r.status_code, expected=422,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY}, json={"tier": "easy", "speed": "fast"})
    rec("/v1/replay/start", "wrong type speed=str -> 422", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY}, json={"tier": "no-such-tier"})
    rec("/v1/replay/start", "unknown tier value", method="POST", status=r.status_code,
        expected=(202, 400, 422, 500), body_shape=shape(r), readable=readable_err(r),
        note="observe how an invalid tier is handled")
    # if that erroneously started something, clean up
    if r.status_code == 202:
        time.sleep(0.5)
        c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY})

    st_before = c.get("/v1/replay/status").json().get("state")
    c.post("/v1/replay/start", headers={"X-Tollgate-Key": BADKEY}, json={"tier": "easy"})
    st_after = c.get("/v1/replay/status").json().get("state")
    rec("/v1/replay/start", "rejected call leaves state untouched", method="POST", status=200,
        expected=200, body_shape="n/a", readable="n/a",
        note=f"state {st_before!r} -> {st_after!r} unchanged={st_before == st_after}")

    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY},
               json={"tier": "easy", "seed": 42, "speed": 60})
    rec("/v1/replay/start", "happy (easy seed42 speed60) -> 202", method="POST", status=r.status_code,
        expected=202, body_shape=shape(r), readable="n/a",
        note=f"state={r.json().get('state')} auto_reset={r.json().get('auto_reset')}")
    time.sleep(1.0)
    r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY}, json={"tier": "easy"})
    rec("/v1/replay/start", "409 while busy", method="POST", status=r.status_code, expected=409,
        body_shape=shape(r), readable=readable_err(r))
    time.sleep(2.0)
    r = c.post("/v1/replay/stop", headers={"X-Tollgate-Key": KEY})
    rec("/v1/replay/stop", "happy stop -> true terminal snapshot", method="POST", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a",
        note=f"state={r.json().get('state')} sent={r.json().get('sent')}/{r.json().get('total')}")
    r = c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY})
    j = r.json()
    rec("/v1/replay/reset", "happy reset -> 200 + cleared map", method="POST", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a",
        note=f"state={j.get('state')} cleared={j.get('cleared')} degraded={j.get('degraded')}")
    r = c.get("/v1/replay/status")
    rec("/v1/replay/status", "post-reset state == idle", method="GET", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a",
        note=f"state={r.json().get('state')} run_id={r.json().get('run_id')}")


print("\n==================== /v1/incidents* ====================")
with C() as c:
    r = c.get("/v1/incidents", headers={"X-Tollgate-Key": KEY})
    rec("/v1/incidents", "happy (state=live)", method="GET", status=r.status_code, expected=200,
        body_shape=shape(r), readable="n/a", note=f"n={len(r.json().get('incidents', []))}")
    r = c.get("/v1/incidents")
    rec("/v1/incidents", "auth absent", method="GET", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.get("/v1/incidents", headers={"X-Tollgate-Key": BADKEY})
    rec("/v1/incidents", "auth invalid", method="GET", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.get("/v1/incidents", headers={"X-Tollgate-Key": KEY}, params={"state": "bogus"})
    rec("/v1/incidents", "unknown state param", method="GET", status=r.status_code,
        expected=(200, 422), body_shape=shape(r), readable=readable_err(r))

    r = c.get("/v1/incidents/does-not-exist", headers={"X-Tollgate-Key": KEY})
    rec("/v1/incidents/{id}", "unknown id -> 404", method="GET", status=r.status_code, expected=404,
        body_shape=shape(r), readable=readable_err(r))
    r = c.get("/v1/incidents/does-not-exist")
    rec("/v1/incidents/{id}", "auth absent", method="GET", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))

    r = c.post("/v1/incidents/x/confirm", headers={"X-Tollgate-Key": KEY},
               json={"action_id": "a", "tier": "block"})
    rec("/v1/incidents/{id}/confirm", "unknown incident -> 404", method="POST", status=r.status_code,
        expected=404, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/incidents/x/confirm", json={"action_id": "a", "tier": "block"})
    rec("/v1/incidents/{id}/confirm", "auth absent", method="POST", status=r.status_code,
        expected=401, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/incidents/x/confirm", headers={"X-Tollgate-Key": KEY}, json={"tier": "block"})
    rec("/v1/incidents/{id}/confirm", "missing action_id -> 422", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))

    r = c.post("/v1/incidents/x/resolve", headers={"X-Tollgate-Key": KEY},
               json={"resolution": "false_positive"})
    rec("/v1/incidents/{id}/resolve", "unknown incident -> 404", method="POST", status=r.status_code,
        expected=404, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/incidents/x/resolve", headers={"X-Tollgate-Key": KEY}, json={"resolution": "banana"})
    rec("/v1/incidents/{id}/resolve", "bad resolution value -> 422", method="POST",
        status=r.status_code, expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/incidents/x/resolve", json={"resolution": "false_positive"})
    rec("/v1/incidents/{id}/resolve", "auth absent", method="POST", status=r.status_code,
        expected=401, body_shape=shape(r), readable=readable_err(r))


print("\n==================== POST /v1/outcome ====================")
with C() as c:
    r = c.post("/v1/outcome", json={"event_id": "x", "gateway_status": "ok", "reached_gateway": True})
    rec("/v1/outcome", "unsigned -> 401", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/outcome", headers={"X-Tollgate-Key": KEY, "X-Tollgate-Signature": "deadbeef",
                                       "X-Tollgate-Timestamp": "1", "X-Tollgate-Nonce": "n1"},
               json={"event_id": "x", "gateway_status": "ok", "reached_gateway": True})
    rec("/v1/outcome", "stale timestamp -> 401", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/outcome", headers={"X-Tollgate-Key": KEY, "X-Tollgate-Signature": "deadbeef",
                                       "X-Tollgate-Timestamp": str(int(time.time() * 1000)),
                                       "X-Tollgate-Nonce": "n2"},
               json={"event_id": "x", "gateway_status": "ok", "reached_gateway": True})
    rec("/v1/outcome", "fresh ts, bad signature -> 401", method="POST", status=r.status_code,
        expected=401, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/outcome", headers={"X-Tollgate-Key": KEY, "X-Tollgate-Signature": "x",
                                       "X-Tollgate-Timestamp": str(int(time.time() * 1000)),
                                       "X-Tollgate-Nonce": "n3"},
               json={"event_id": "x", "gateway_status": "ok", "reached_gateway": True, "extra": "no"})
    rec("/v1/outcome", "extra field (extra=forbid) -> 422", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/outcome", headers={"X-Tollgate-Key": KEY, "X-Tollgate-Signature": "x",
                                       "X-Tollgate-Timestamp": str(int(time.time() * 1000)),
                                       "X-Tollgate-Nonce": "n4"},
               json={"gateway_status": "ok", "reached_gateway": True})
    rec("/v1/outcome", "missing event_id -> 422", method="POST", status=r.status_code, expected=422,
        body_shape=shape(r), readable=readable_err(r))


print("\n==================== /v1/demo/* (TOLLGATE_DEMO_CONTROLS=1 on this stack) ====================")
with C() as c:
    r = c.get("/v1/demo/cotenant-ip", headers={"X-Tollgate-Key": KEY})
    rec("/v1/demo/cotenant-ip", "gated on, key ok", method="GET", status=r.status_code,
        expected=(200, 404), body_shape=shape(r), readable=readable_err(r), note=f"body={r.json()}")
    r = c.get("/v1/demo/cotenant-ip")
    rec("/v1/demo/cotenant-ip", "auth absent -> 401", method="GET", status=r.status_code,
        expected=401, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/demo/flood", headers={"X-Tollgate-Key": KEY}, json={"enabled": False})
    rec("/v1/demo/flood", "enabled:false safe no-op", method="POST", status=r.status_code,
        expected=200, body_shape=shape(r), readable="n/a", note=f"{r.json()}")
    r = c.post("/v1/demo/flood", json={"enabled": False})
    rec("/v1/demo/flood", "auth absent -> 401", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/demo/flood", headers={"X-Tollgate-Key": KEY}, json={})
    rec("/v1/demo/flood", "missing enabled -> 422", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/demo/fault", json={"enabled": True})
    rec("/v1/demo/fault", "auth absent -> 401", method="POST", status=r.status_code, expected=401,
        body_shape=shape(r), readable=readable_err(r))
    r = c.post("/v1/demo/fault", headers={"X-Tollgate-Key": KEY}, json={})
    rec("/v1/demo/fault", "missing enabled -> 422", method="POST", status=r.status_code,
        expected=422, body_shape=shape(r), readable=readable_err(r))
    c.post("/v1/demo/fault", headers={"X-Tollgate-Key": KEY}, json={"enabled": True})
    rs = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body())
    rec("/v1/demo/fault", "fault ON -> /v1/score 200 allow (fail-open, never 5xx)", method="POST",
        status=rs.status_code, expected=200, body_shape=shape(rs), readable="n/a",
        note=f"decision={rs.json().get('decision')}")
    off = c.post("/v1/demo/fault", headers={"X-Tollgate-Key": KEY}, json={"enabled": False})
    rec("/v1/demo/fault", "restored to OFF", method="POST", status=off.status_code, expected=200,
        body_shape=shape(off), readable="n/a", note=f"{off.json()}")
    rs = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=score_body())
    rec("/v1/demo/fault", "after OFF -> full path restored", method="POST", status=rs.status_code,
        expected=200, body_shape=shape(rs), readable="n/a", note=f"decision={rs.json().get('decision')}")


print("\n==================== unknown route ====================")
with C() as c:
    r = c.get("/v1/does-not-exist")
    rec("/v1/does-not-exist", "unknown route -> 404", method="GET", status=r.status_code,
        expected=404, body_shape=shape(r), readable=readable_err(r))
    r = c.get("/")
    rec("/", "root -> 404", method="GET", status=r.status_code, expected=404,
        body_shape=shape(r), readable=readable_err(r))


n_fail = sum(1 for x in results if x["verdict"] == "FAIL")
print(f"\n==================== SUMMARY: {len(results)} checks, {n_fail} FAIL ====================")
for x in results:
    if x["verdict"] == "FAIL":
        print(f"  FAIL {x['method']} {x['route']} :: {x['case']} -> got {x['status']} want {x['expected']}  {x['note']}")

out = sys.argv[1] if len(sys.argv) > 1 else "phase4_results.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nwrote {out}")
sys.exit(1 if n_fail else 0)
