"""
Source: TRD v2 §6.4 -- "tests/oracles/pandas_windows.py is a slow,
brute-force, obviously-correct window implementation, used ONLY by tests."
Deliberately O(n^2), no `.rolling()`, no clever indexing -- the entire
point is that a reader can convince themselves it is correct at a glance,
independent of the Redis/in-memory implementation it differentially tests
against. Day-3 Plan Step 9.

Never import this module outside tests/ (tests/acceptance/
test_oracle_isolation.py asserts the transitive import closure of
packages/, services/, and scripts/ never reaches here).

Arrival order, not timestamp order, decides ties and out-of-order events.
This matches Redis: a ZADD member only exists in the sorted set once the
command has run, so two events with identical scores (timestamps) are
still ordered by which ZADD executed first. `events` here is a plain
Python list -- its index order IS arrival order, by construction -- and
the loop below walks `events[: i + 1]` rather than any timestamp-sorted
view.
"""

from __future__ import annotations

from typing import Callable, Dict, List

import pandas as pd


def load_events(path: str) -> pd.DataFrame:
    """
    Source: Day-3 Plan Step 9 -- loads a JSONL fixture (golden.jsonl,
    handmade_40.jsonl) in file order. pandas is used here only for
    convenient IO; row order after `read_json(lines=True)` is file order,
    which is preserved as arrival order throughout this module.
    """
    return pd.read_json(path, lines=True)


def window_counts(
    events: List[Dict],
    *,
    key_fn: Callable[[Dict], str],
    member_fn: Callable[[Dict], str],
    time_fn: Callable[[Dict], int],
    window_ms: int,
) -> List[int]:
    """
    Source: TRD §6.1's sliding-window semantics, applied brute-force --
    ZADD, then ZREMRANGEBYSCORE(-inf, floor), then ZCARD, exactly.

    Trimming has no upper bound tied to the querying event's own
    timestamp: ZREMRANGEBYSCORE only ever removes members whose score is
    at or below the CURRENT event's floor, and removal is permanent. A
    member m (added by an earlier same-key event j) therefore survives at
    event i if and only if it was never trimmed by any same-key event
    between j and i inclusive -- i.e. `time_fn(m) > running_max - window_ms`,
    where `running_max` is the largest timestamp seen so far among
    same-key events up to and including i (arrival order). For
    non-decreasing timestamps this reduces to the intuitive
    `time_fn(events[i]) - window_ms < time_fn(m) <= time_fn(events[i])`;
    under out-of-order arrival it does not, and matching Redis exactly
    here (not the intuitive-but-wrong formula) is the entire point of an
    oracle that differentially tests out-of-order behaviour.

    An event scored at exactly `t - window` is excluded (Impl Plan §1.1's
    stated convention: `> floor`, not `>= floor`). Inclusive of the
    current event, matching TRD §6.3: the member being recorded is added,
    then the window is trimmed and counted.

    Returns one count per input event, in the same order as `events`.
    """
    results: List[int] = []
    for i in range(len(events)):
        key_i = key_fn(events[i])
        same_key_upto_i = [
            (j, time_fn(events[j]), member_fn(events[j]))
            for j in range(i + 1)
            if key_fn(events[j]) == key_i
        ]
        running_max = max(t for _, t, _ in same_key_upto_i)
        floor = running_max - window_ms
        members = {member for _, t, member in same_key_upto_i if t > floor}
        results.append(len(members))
    return results
