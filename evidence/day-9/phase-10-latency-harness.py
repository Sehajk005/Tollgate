"""Day 9 Phase 10 -- /v1/score latency + availability rungs, against the running stack.

Run: uv run python phase10_latency.py <out.json>
"""
from __future__ import annotations
import json, statistics, subprocess, sys, time, uuid
import concurrent.futures as cf
import httpx

BASE = "http://localhost:8080"
KEY = "S9DyTCV1cEsGQUIJAhi_QIIKGMGQSfeyI3aXh7bzPzg"
out = {}


def body(**o):
    b = dict(event_id=f"p10-{uuid.uuid4()}", card_hash="c" * 24, bin="424242",
             amount_minor=1999, currency="INR")
    b.update(o)
    return b


def pctile(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f = int(k)
    return xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f)


def summ(name, rtt, compute):
    d = dict(
        n=len(rtt),
        rtt_p50=round(pctile(rtt, 50), 1), rtt_p95=round(pctile(rtt, 95), 1),
        rtt_p99=round(pctile(rtt, 99), 1), rtt_max=round(max(rtt), 1),
        compute_p50=round(pctile(compute, 50), 1), compute_p95=round(pctile(compute, 95), 1),
        compute_p99=round(pctile(compute, 99), 1), compute_max=round(max(compute), 1),
        compute_mean=round(statistics.mean(compute), 1),
    )
    out[name] = d
    print(f"\n{name}  (n={d['n']})")
    print(f"  round-trip  p50={d['rtt_p50']:>7} p95={d['rtt_p95']:>7} p99={d['rtt_p99']:>7} max={d['rtt_max']:>7} ms")
    print(f"  compute_ms  p50={d['compute_p50']:>7} p95={d['compute_p95']:>7} p99={d['compute_p99']:>7} max={d['compute_max']:>7} ms   (TRD target: p99 < 100)")
    return d


c = httpx.Client(base_url=BASE, timeout=30.0)
for _ in range(20):
    c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=body())

print("==================== FULL PATH -- sequential (n=300) ====================")
rtt, comp = [], []
for _ in range(300):
    t = time.perf_counter()
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=body())
    rtt.append((time.perf_counter() - t) * 1000)
    comp.append(r.json().get("latency_ms", -1))
full_seq = summ("full_path_sequential", rtt, comp)

print("\n==================== FULL PATH -- 10 concurrent clients (n=500) ====================")
def one(_):
    with httpx.Client(base_url=BASE, timeout=30.0) as cc:
        t = time.perf_counter()
        r = cc.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=body())
        return (time.perf_counter() - t) * 1000, r.json().get("latency_ms", -1), r.status_code
with cf.ThreadPoolExecutor(max_workers=10) as ex:
    res = list(ex.map(one, range(500)))
rtt = [x[0] for x in res]; comp = [x[1] for x in res]
codes = set(x[2] for x in res)
full_conc = summ("full_path_10concurrent", rtt, comp)
out["full_path_10concurrent"]["status_codes"] = sorted(codes)
print(f"  status codes: {sorted(codes)}")

print("\n==================== BURST -- 200 requests back-to-back ====================")
rtt, comp, codes = [], [], []
t0 = time.perf_counter()
for _ in range(200):
    t = time.perf_counter()
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=body())
    rtt.append((time.perf_counter() - t) * 1000)
    comp.append(r.json().get("latency_ms", -1))
    codes.append(r.status_code)
burst_wall = time.perf_counter() - t0
summ("burst_200", rtt, comp)
out["burst_200"]["wall_s"] = round(burst_wall, 2)
out["burst_200"]["req_per_s"] = round(200 / burst_wall, 1)
out["burst_200"]["shed_count"] = sum(1 for x in codes if x != 200)
print(f"  wall={burst_wall:.2f}s  {200/burst_wall:.1f} req/s  non-200(shed)={out['burst_200']['shed_count']}")

print("\n==================== FAIL-OPEN rung latency (demo fault) ====================")
c.post("/v1/demo/fault", headers={"X-Tollgate-Key": KEY}, json={"enabled": True})
rtt, comp = [], []
for _ in range(100):
    t = time.perf_counter()
    r = c.post("/v1/score", headers={"X-Tollgate-Key": KEY}, json=body())
    rtt.append((time.perf_counter() - t) * 1000)
    comp.append(r.json().get("latency_ms", -1))
    assert r.status_code == 200, r.status_code
c.post("/v1/demo/fault", headers={"X-Tollgate-Key": KEY}, json={"enabled": False})
summ("fail_open_rung", rtt, comp)
print("  (fail-open should be FASTER than the full path -- it skips model + Layer 2)")

print("\n==================== LLM not on the scoring path ====================")
nb = subprocess.run(["docker", "compose", "exec", "-T", "scorer", "sh", "-c", "echo $NARRATOR_BACKEND"],
                    capture_output=True, text=True).stdout.strip()
ncalls = subprocess.run(["docker", "compose", "exec", "-T", "scorer", "python", "-c",
    "import sqlite3;print(sqlite3.connect('/data/tollgate.db').execute('SELECT COUNT(*) FROM narrator_call').fetchone()[0])"],
    capture_output=True, text=True).stdout.strip()
out["narrator"] = {"backend": nb, "narrator_call_rows": ncalls,
                   "note": "Decision 98 -- Gemini dispatched out-of-band after the terminal SSE publish; "
                           "score latency above reflects NO Gemini on the path."}
print(f"  NARRATOR_BACKEND={nb!r}  narrator_call rows={ncalls}")

out["trd_p99_target"] = {"target_ms": 100,
                         "full_seq_compute_p99": full_seq["compute_p99"],
                         "full_conc_compute_p99": full_conc["compute_p99"],
                         "met_sequential": full_seq["compute_p99"] < 100,
                         "met_concurrent": full_conc["compute_p99"] < 100}
print(f"\n  TRD p99<100ms compute: seq p99={full_seq['compute_p99']} "
      f"({'MET' if full_seq['compute_p99']<100 else 'MISS'}), "
      f"10-conc p99={full_conc['compute_p99']} ({'MET' if full_conc['compute_p99']<100 else 'MISS'})")

with open(sys.argv[1] if len(sys.argv) > 1 else "phase10_latency.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"\nwrote {sys.argv[1] if len(sys.argv) > 1 else 'phase10_latency.json'}")
