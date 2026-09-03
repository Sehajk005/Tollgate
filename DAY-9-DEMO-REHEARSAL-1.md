# Day 9 — Demo Rehearsal #1

**Plan:** `09-DAY-9-QA-AND-DEMO-PLAN.md` §Phase 12 + §7 (rehearsal protocol).
**Executed:** 2026-09-03 (Session 3). Against the real Docker Compose stack.
**Setup:** clean state via `docker compose down -v` → `docker compose up --build`.
LEFT = storefront `:5173` (`?demo=1`), RIGHT = dashboard `:5174`. No dev console
in frame during the flow; network/console captures taken out of band for evidence.

Rehearsal #1 is an **actual release test**: it discovers defects. Each failure is
stopped on, reproduced, classified, and recorded here + in `DAY-9-DEFECT-LOG.md`.

---

## Pre-rehearsal fixes (before the walkthrough)

| Defect | Sev | Fix | Commit |
|---|---|---|---|
| **DEF-D9-010** storefront normal checkout `onClick={pay}` leaks the React event into the fetch headers → `TypeError` → false "Order confirmed" | P1 | `onClick={() => pay()}` + `tests/acceptance/test_storefront_checkout_wiring.py` | `055613e` |

---

## Pass A — first walkthrough

_(filled during execution)_

---

## Failures discovered

_(filled during execution)_

---

## Pass B — re-run after Pass-A fixes

_(filled during execution)_

---

## Rehearsal #1 verdict

_(filled during execution)_
