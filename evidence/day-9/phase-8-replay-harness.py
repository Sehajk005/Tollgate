"""Day 9 Phase 8 -- Replay lifecycle (release gate) against the running Compose stack.

A. speed-0 matrix: {easy,medium,hard,evasive} x pace{on,off} x 2 repeats (seed 42)
B. speed-60: easy pace-on + easy pace-off + medium pace-on (threat->incident)
C. lifecycle ops: stop mid-run (AUDIT-003) · reset-while-running (AUDIT-004) ·
   repeat run same process (AUDIT-005) · tier switch and back
D. speed-1: short paced proof + stop + reset

Run: uv run python phase8_replay.py <out.json>
"""
from __future__ import annotations
import json, subprocess, sys, time
import httpx

BASE = "http://localhost:8080"
KEY = "S9DyTCV1cEsGQUIJAhi_QIIKGMGQSfeyI3aXh7bzPzg"
c = httpx.Client(base_url=BASE, timeout=60.0)
out = {"runs": [], "checks": {}}
run_ids_seen = []


def redis_floor():
    r = subprocess.run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "-n", "9", "dbsize"],
                       capture_output=True, text=True)
    return int((r.stdout.strip() or "-1"))


def ascore_count():
    code = "import sqlite3;print(sqlite3.connect('/data/tollgate.db').execute('SELECT COUNT(*) FROM attempt_score').fetchone()[0])"
    return int(subprocess.run(["docker", "compose", "exec", "-T", "scorer", "python", "-c", code],
                              capture_output=True, text=True).stdout.strip())


def reset():
    return c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY}).json()


def launch(tier, speed, pace, seed=42):
    body = {"tier": tier, "seed": seed, "speed": speed}
    if pace:
        body["pace_from"] = "episode"
    return c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY}, json=body)


def poll(timeout=260):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get("/v1/replay/status").json()
        if s["state"] in ("finished", "failed", "stopped"):
            return s
        time.sleep(1.0)
    return c.get("/v1/replay/status").json()


def do_run(tier, speed, pace, label):
    reset(); time.sleep(0.3)
    a0 = ascore_count()
    r = launch(tier, speed, pace)
    assert r.status_code == 202, f"{label}: start {r.status_code} {r.text}"
    rid = r.json()["run_id"]
    s = poll()
    time.sleep(1.2)
    a2 = ascore_count()
    rst = reset()
    floor = redis_floor()
    rec = dict(label=label, tier=tier, speed=speed, pace=pace, run_id=rid,
               state=s["state"], sent=s["sent"], total=s["total"], terminal=s["terminal"],
               ascore_delta=a2 - a0, ascore_parity=(a2 - a0 == s["sent"]),
               redis_floor_after_reset=floor, cleared=rst.get("cleared"),
               reset_degraded=rst.get("degraded"))
    out["runs"].append(rec)
    run_ids_seen.append(rid)
    ok = (s["state"] == "finished" and s["sent"] == s["total"] and s["terminal"]
          and rec["ascore_parity"] and rst.get("degraded") is False)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label:26} {tier:7} sp{speed} pace={str(pace):5} "
          f"-> {s['state']:8} {s['sent']}/{s['total']} rid=..{rid[-6:]} "
          f"aScoreD={rec['ascore_delta']} parity={rec['ascore_parity']} floor={floor}")
    return rec


print("\n==================== A. speed-0 matrix (seed 42, x2) ====================")
tier_counts = {}
for tier in ("easy", "medium", "hard", "evasive"):
    for pace in (False, True):
        for rep in (1, 2):
            rc_ = do_run(tier, 0, pace, f"A/{tier}/pace={pace}/rep{rep}")
            tier_counts.setdefault((tier, pace), []).append(rc_["total"])
out["tier_counts"] = {f"{k[0]}/pace={k[1]}": v for k, v in tier_counts.items()}
repeatable = all(len(set(v)) == 1 for v in tier_counts.values())
easy_821 = all(v[0] == 821 for k, v in tier_counts.items() if k[0] == "easy")
pace_invariant = all(tier_counts[(t, False)][0] == tier_counts[(t, True)][0]
                     for t in ("easy", "medium", "hard", "evasive"))
print(f"\n  tier counts: {out['tier_counts']}")
print(f"  repeatable: {repeatable}   easy==821: {easy_821}   count invariant pace on/off: {pace_invariant}")

print("\n==================== B. speed-60 (demo path) ====================")
for tier, pace, lbl in [("easy", True, "B/easy/60/pace"), ("easy", False, "B/easy/60/nopace"),
                        ("medium", True, "B/medium/60/pace")]:
    reset(); time.sleep(0.3)
    t0 = time.time()
    r = launch(tier, 60, pace)
    rid = r.json()["run_id"]
    s = poll(timeout=340)
    dur = time.time() - t0
    incs = subprocess.run(["docker", "compose", "exec", "-T", "scorer", "python", "-c",
        "import sqlite3;print(sqlite3.connect('/data/tollgate.db').execute("
        "\"SELECT COUNT(*) FROM incident WHERE state != 'CLOSED'\").fetchone()[0])"],
        capture_output=True, text=True).stdout.strip()
    ok = s["state"] == "finished" and s["sent"] == s["total"]
    out["runs"].append(dict(label=lbl, tier=tier, speed=60, pace=pace, run_id=rid, state=s["state"],
                            sent=s["sent"], total=s["total"], wall_s=round(dur, 1), open_incidents=incs))
    run_ids_seen.append(rid)
    print(f"  [{'PASS' if ok else 'FAIL'}] {lbl:20} -> {s['state']} {s['sent']}/{s['total']} "
          f"wall={dur:.0f}s open_incidents={incs}")
    reset()

print("\n==================== C. lifecycle ops ====================")
reset(); time.sleep(0.3)
launch("easy", 60, True); time.sleep(3)
mid = c.get("/v1/replay/status").json()
stop_resp = c.post("/v1/replay/stop", headers={"X-Tollgate-Key": KEY}).json()
c1_ok = stop_resp["state"] == "stopped" and stop_resp["state"] != "running"
out["checks"]["C1_stop_true_terminal"] = c1_ok
print(f"  [{'PASS' if c1_ok else 'FAIL'}] C1 stop mid-run: mid running {mid['sent']}/{mid['total']} "
      f"-> stop state={stop_resp['state']} sent={stop_resp['sent']} (not a stale 'running')")
reset()

reset(); time.sleep(0.3)
launch("easy", 60, True); time.sleep(3)
run_state = c.get("/v1/replay/status").json()["state"]
rr = c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY})
time.sleep(0.5)
after = c.get("/v1/replay/status").json()
c2_ok = (rr.status_code == 200 and after["state"] == "idle" and after["run_id"] is None) or \
        (rr.status_code == 409 and after["state"] == run_state)
out["checks"]["C2_reset_while_running"] = c2_ok
print(f"  [{'PASS' if c2_ok else 'FAIL'}] C2 reset while {run_state}: {rr.status_code} -> "
      f"state={after['state']} run_id={after['run_id']}")
time.sleep(2)
a_b = ascore_count(); time.sleep(2); a_a = ascore_count()
c2b_ok = a_a == a_b
out["checks"]["C2b_backend_stopped_scoring"] = c2b_ok
print(f"  [{'PASS' if c2b_ok else 'FAIL'}] C2b backend stopped scoring after reset (attempt_score {a_b} -> {a_a})")
reset()

reset(); time.sleep(0.3)
r1 = launch("easy", 0, False); rid1 = r1.json()["run_id"]; s1 = poll()
r2 = launch("easy", 0, False); rid2 = r2.json()["run_id"]; s2 = poll()
c3_ok = (s1["sent"] == 821 and s2["sent"] == 821 and rid1 != rid2)
out["checks"]["C3_repeat_run_full_and_new_runid"] = c3_ok
out["checks"]["C3_auto_reset_on_dirty_launch"] = r2.json().get("auto_reset") is True
print(f"  [{'PASS' if c3_ok else 'FAIL'}] C3 repeat run: run1 {s1['sent']}/821 ..{rid1[-6:]}  "
      f"run2 {s2['sent']}/821 ..{rid2[-6:]}  distinct={rid1 != rid2}  auto_reset={r2.json().get('auto_reset')}")
reset()

reset(); time.sleep(0.3)
ra = launch("medium", 0, False); sa = poll(); rida = ra.json()["run_id"]
rb = launch("easy", 0, False); sb = poll(); ridb = rb.json()["run_id"]
rc2 = launch("easy", 0, False); sc = poll(); ridc = rc2.json()["run_id"]
c4_ok = len({rida, ridb, ridc}) == 3 and sb["sent"] == sc["sent"] == 821
out["checks"]["C4_tier_switch_and_back"] = c4_ok
print(f"  [{'PASS' if c4_ok else 'FAIL'}] C4 medium->easy->easy: {sa['sent']}/{sa['total']} -> "
      f"{sb['sent']}/821 -> {sc['sent']}/821  3 distinct run_ids={len({rida,ridb,ridc})==3}")
reset()

print("\n==================== D. speed-1 (paced proof) ====================")
reset(); time.sleep(0.3)
r = launch("easy", 1, False)
rid = r.json()["run_id"]
time.sleep(20)
s_mid = c.get("/v1/replay/status").json()
stop = c.post("/v1/replay/stop", headers={"X-Tollgate-Key": KEY}).json()
rst = reset()
d_ok = (r.status_code == 202 and s_mid["state"] == "running" and s_mid["sent"] > 0
        and stop["state"] == "stopped" and rst.get("degraded") is False)
out["checks"]["D_speed1_paces_stops_resets"] = d_ok
print(f"  [{'PASS' if d_ok else 'FAIL'}] D speed-1: 202, after 20s running {s_mid['sent']}/{s_mid['total']}, "
      f"stop->{stop['state']}, reset degraded={rst.get('degraded')}  "
      f"(full easy@1 ~= real-time hours; not a demo speed; determinism -> verify_60x --gate crossing)")

out["checks"]["A_repeatable"] = repeatable
out["checks"]["A_easy_821"] = easy_821
out["checks"]["A_count_invariant_pace"] = pace_invariant
out["checks"]["all_run_ids_unique"] = len(run_ids_seen) == len(set(run_ids_seen))
out["checks"]["no_run_swallowed"] = all(r.get("sent", 0) > 0 for r in out["runs"]
                                        if r.get("state") == "finished")

print("\n==================== GLOBAL CHECKS ====================")
for k, v in out["checks"].items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k} = {v}")
print(f"\n  {len(run_ids_seen)} launches, {len(set(run_ids_seen))} distinct run_ids")

reset()
with open(sys.argv[1] if len(sys.argv) > 1 else "phase8.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"wrote {sys.argv[1] if len(sys.argv) > 1 else 'phase8.json'}")
sys.exit(1 if any(not v for v in out["checks"].values()) else 0)
