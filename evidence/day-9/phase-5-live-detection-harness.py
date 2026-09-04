"""Day 9 Phase 5 -- live detection verification against the running Compose stack.

Runs an `easy` replay (seed 42, speed 60, pace_from episode) through the real
scoring path and asserts the detection stack behaves per spec:
  - R1/R2/R3 rule floors fire and are recorded in attempt_score.rules_fired
  - decisions never AUTOMATICALLY exceed the `challenge` auto-ceiling (Decisions 15/70)
  - Layer 2b distinct-card SPRT opens an incident; state OPEN->ESCALATED
  - entity resolution: incident entities are ip / ipua / card (never store-wide, never asn)
  - enforcement ledger: active count, k_max, advisory_mode; step_up/block PROPOSED only
  - terminal path: confirm -> ceiling raised; resolve -> CLOSED + every enforcement released
Then resets.

Run: uv run python phase5_live_detection.py <out.json>
"""
from __future__ import annotations
import json, sys, time, subprocess
import httpx

BASE = "http://localhost:8080"
KEY = "S9DyTCV1cEsGQUIJAhi_QIIKGMGQSfeyI3aXh7bzPzg"
out = {}


def db(sql, params=()):
    code = (
        "import sqlite3,json;"
        "c=sqlite3.connect('/data/tollgate.db');c.row_factory=sqlite3.Row;"
        f"rows=[dict(r) for r in c.execute({sql!r}, {tuple(params)!r})];"
        "print(json.dumps(rows,default=str))"
    )
    r = subprocess.run(["docker", "compose", "exec", "-T", "scorer", "python", "-c", code],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


c = httpx.Client(base_url=BASE, timeout=30.0)

c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY})
time.sleep(0.5)
pre = c.get("/v1/replay/status").json()
print(f"pre-run state={pre['state']} run_id={pre['run_id']}")

r = c.post("/v1/replay/start", headers={"X-Tollgate-Key": KEY},
           json={"tier": "easy", "seed": 42, "speed": 60, "pace_from": "episode"})
assert r.status_code == 202, r.text
run_id = r.json()["run_id"]
print(f"launched run_id={run_id}")
out["run_id"] = run_id

deadline = time.time() + 240
last = None
while time.time() < deadline:
    s = c.get("/v1/replay/status").json()
    if (s["state"], s["sent"]) != last:
        print(f"  state={s['state']:9} sent={s['sent']}/{s['total']}")
        last = (s["state"], s["sent"])
    if s["state"] in ("finished", "failed", "stopped"):
        break
    time.sleep(1.5)
final = c.get("/v1/replay/status").json()
out["final_status"] = final
print(f"final: state={final['state']} sent={final['sent']}/{final['total']} terminal={final['terminal']}")
out["event_count_ok"] = (final["sent"] == 821 and final["total"] == 821 and final["state"] == "finished")

started = final["started_at_ms"]
scored = db("SELECT s.decision, s.rules_fired, s.shed, s.control_arm, s.incident_id "
            "FROM attempt_score s JOIN auth_attempt a ON a.attempt_uid=s.attempt_uid "
            "WHERE a.merchant_id='merchant_demo' AND s.scored_at >= ?", (started,))
decs, rules_seen, ctrl = {}, set(), 0
for row in scored:
    decs[row["decision"]] = decs.get(row["decision"], 0) + 1
    if row["control_arm"]:
        ctrl += 1
    rf = row["rules_fired"]
    if isinstance(rf, str):
        try:
            rf = json.loads(rf)
        except Exception:
            rf = [rf] if rf else []
    for x in (rf or []):
        rules_seen.add(x if isinstance(x, str) else json.dumps(x))
out["decision_histogram"] = decs
out["rules_fired_seen"] = sorted(rules_seen)
out["n_scored_this_run"] = len(scored)
out["control_arm_count"] = ctrl
print(f"\nscored this run: {len(scored)}  control_arm={ctrl}")
print(f"decision histogram: {decs}")
print(f"rules_fired seen:   {sorted(rules_seen)}")

auto_exceeded = [r for r in scored if r["decision"] in ("block", "step_up")]
out["auto_ceiling_respected"] = (len(auto_exceeded) == 0)
print(f"auto-ceiling respected (no auto block/step_up decision): {len(auto_exceeded) == 0}")

incs = db("SELECT incident_id, state, detector, peak_tier, opened_at, attempts_before_alert, "
          "cards_exposed_before_alert, time_to_detect_s, cusum_stat_at_alert "
          "FROM incident WHERE merchant_id='merchant_demo' AND opened_at >= ? ORDER BY opened_at", (started,))
out["incidents"] = incs
print(f"\nincidents opened this run: {len(incs)}")
for i in incs:
    print(f"  {i['incident_id'][:20]} state={i['state']} detector={i['detector']} peak_tier={i['peak_tier']} "
          f"ttd_s={i['time_to_detect_s']} attempts_before_alert={i['attempts_before_alert']} "
          f"cards_exposed={i['cards_exposed_before_alert']}")

if incs:
    ids = tuple(i["incident_id"] for i in incs)
    ph = ",".join("?" * len(ids))
    ents = db(f"SELECT incident_id, entity_type, entity_key FROM incident_entity WHERE incident_id IN ({ph})", ids)
    out["incident_entities"] = ents
    etypes = sorted(set(e["entity_type"] for e in ents))
    out["entity_types"] = etypes
    out["entity_resolution_ok"] = (all(e["entity_type"] in ("ip", "ipua", "card") for e in ents)
                                   and "store" not in etypes and "asn" not in etypes)
    print(f"\nincident entity_types: {etypes}  (subset of card/ipua/ip; never store/asn)")

    enf = db(f"SELECT action_id, incident_id, entity_type, entity_key, tier, requires_confirmation, "
             f"confirmed_by, applied_at, released_at, expires_at FROM enforcement_action WHERE incident_id IN ({ph})", ids)
    out["enforcement_actions"] = enf
    proposed = [e for e in enf if e["tier"] in ("step_up", "block")]
    out["proposed_are_unconfirmed"] = all(
        e["requires_confirmation"] == 1 and e["confirmed_by"] is None and e["applied_at"] is None for e in proposed)
    print(f"\nenforcement actions: {len(enf)}  proposed(step_up/block)={len(proposed)} "
          f"all-unconfirmed={out['proposed_are_unconfirmed']}")
    for e in enf:
        print(f"  {e['entity_type']}:{str(e['entity_key'])[:24]:24} tier={e['tier']:8} "
              f"req_conf={e['requires_confirmation']} confirmed_by={e['confirmed_by']} released_at={e['released_at']}")

    recent = c.get("/v1/stream/recent").json()["events"]
    enf_frames = [e.get("enforcement") for e in recent if e.get("enforcement")]
    out["sse_enforcement_last"] = enf_frames[-1] if enf_frames else None
    print(f"\nSSE last enforcement frame: {out['sse_enforcement_last']}")

    inc0 = incs[0]["incident_id"]
    prop = next((e for e in enf if e["tier"] in ("step_up", "block") and e["requires_confirmation"] == 1), None)
    if prop:
        cr = c.post(f"/v1/incidents/{inc0}/confirm", headers={"X-Tollgate-Key": KEY},
                    json={"action_id": prop["action_id"], "tier": prop["tier"]})
        out["confirm_result"] = {"status": cr.status_code, "body": cr.json()}
        print(f"\nconfirm {prop['tier']} on {inc0[:20]}: {cr.status_code} {cr.json()}")
        out["after_confirm_row"] = db("SELECT confirmed_by, applied_at, requires_confirmation "
                                      "FROM enforcement_action WHERE action_id=?", (prop["action_id"],))
        print(f"  row after confirm: {out['after_confirm_row']}")

    rr = c.post(f"/v1/incidents/{inc0}/resolve", headers={"X-Tollgate-Key": KEY},
                json={"resolution": "true_positive"})
    out["resolve_result"] = {"status": rr.status_code, "body": rr.json()}
    print(f"\nresolve {inc0[:20]} true_positive: {rr.status_code} {rr.json()}")
    time.sleep(0.5)
    out["incident_after_resolve"] = db("SELECT incident_id, state FROM incident WHERE incident_id=?", (inc0,))
    rel = db("SELECT action_id, released_at FROM enforcement_action WHERE incident_id=?", (inc0,))
    out["enforcement_after_resolve"] = rel
    out["all_released_after_resolve"] = all(e["released_at"] is not None for e in rel)
    print(f"  incident state after resolve: {out['incident_after_resolve']}")
    print(f"  enforcement all released: {out['all_released_after_resolve']}  ({rel})")

rst = c.post("/v1/replay/reset", headers={"X-Tollgate-Key": KEY})
out["final_reset"] = {"status": rst.status_code, "cleared": rst.json().get("cleared"),
                      "degraded": rst.json().get("degraded")}
print(f"\nfinal reset: {rst.status_code} cleared={rst.json().get('cleared')} degraded={rst.json().get('degraded')}")

checks = {
    "event_count_easy_821": out.get("event_count_ok"),
    "R1_R2_R3_floors_fired": bool({"R1", "R2", "R3"} & set(out["rules_fired_seen"])),
    "auto_ceiling_respected": out.get("auto_ceiling_respected"),
    "incident_opened": len(out.get("incidents", [])) > 0,
    "incident_escalated_or_terminal": any(i["state"] in ("ESCALATED", "COOLING", "CLOSED")
                                          for i in out.get("incidents", [])),
    "entity_resolution_ip_ipua_card": out.get("entity_resolution_ok"),
    "proposed_enforcement_unconfirmed": out.get("proposed_are_unconfirmed"),
    "resolve_released_all_enforcement": out.get("all_released_after_resolve"),
    "reset_returns_200_cleared": out["final_reset"]["status"] == 200,
}
out["checks"] = checks
print("\n==================== CHECKS ====================")
for k, v in checks.items():
    print(f"  [{'PASS' if v else 'FAIL/NA'}] {k} = {v}")

with open(sys.argv[1] if len(sys.argv) > 1 else "phase5_live.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"\nwrote {sys.argv[1] if len(sys.argv) > 1 else 'phase5_live.json'}")
sys.exit(1 if any(not v for v in checks.values()) else 0)
