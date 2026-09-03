"""
Source: Day-2 Plan §G "Replay Design" -- the virtual-clock replay driver,
exactly the loop described there: `vclock.set_ms(t0 + ev.t_ms)` -- never
`advance_ms(wall_delta)` -- so virtual time IS event time. "The only
wall-clock call in the loop is asyncio.sleep, which affects nothing the
scorer reads" (Day-2 Plan §G).

`ulid` is seeded deterministically from `request.seed` (see
services/scorer/scoring.py's docstring) so attempt_uid minting, not just
decisions, is reproducible under A13's speed=0-vs-60 comparison.

Remediation plan FIX-005 / FIX-006 / FIX-007 / FIX-011 -- THE BACKEND OWNS THE
LIFECYCLE. Day 2 shipped a driver with four wire states, a `stop()` that only
set a flag, a `reset()` that ignored the running task, and a `run()` with no
`try/except`. Between them that produced five of the audit's six demo-enders:

  * a finished run rendered forever as `RUNNING (N-1/N)`, because `sent` was
    written AFTER the publish and the terminal transition published nothing
    (AUDIT-002);
  * `stop` serialised the pre-stop snapshot with no await, so it always
    reported `running` (AUDIT-003);
  * `reset` mutated state while the loop kept scoring and then overwrote the
    status on its next iteration (AUDIT-004);
  * any exception in the loop vanished into a never-awaited task and showed as
    a frozen counter (AUDIT-007);
  * the tier selector had nothing authoritative to reconcile against
    (AUDIT-013).

The state machine below is now explicit, every transition publishes, and a
`run_id` gives each run an identity the frontend can use as its single reset
signal.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, replace
from typing import Optional

from packages.clock.clock import SystemClock, VirtualClock
from packages.clock.ids import UlidGenerator
from packages.contracts.wire import ScoreRequest
from packages.storage.db import connect
from services.scorer.deps import ScorerState
from services.scorer.scoring import score_attempt

logger = logging.getLogger("tollgate.scorer.replay")

# Source: remediation plan §7 -- the wire states, split into the two sets every
# consumer actually reasons about. TERMINAL means "the operator may act";
# BUSY means "a lifecycle transition owns the driver right now".
TERMINAL_STATES = frozenset({"idle", "stopped", "finished", "failed"})
BUSY_STATES = frozenset({"starting", "running", "stopping", "resetting"})

# How long `stop()` and `reset()` wait for the loop to acknowledge. Bounded at
# every acquisition point: a lock held across an unbounded await on a task that
# never ends would hang the handler, which is the failure this replaces.
STOP_ACK_TIMEOUT_S = 2.0
CANCEL_ACK_TIMEOUT_S = 2.0

# Source: remediation plan FIX-007 -- watchdog thresholds, in wall-clock ms.
# The audit measured the maximum inter-event sleep at 60x as 4.6 s; 30 s is a
# 6.5x margin over that, and speed 0 never sleeps at all.
WATCHDOG_PACED_MS = 30_000
WATCHDOG_UNPACED_MS = 15_000
WATCHDOG_POLL_S = 1.0

# Source: remediation plan FIX-011 -- how much event time to pace before the
# episode starts, so the operator sees the run settle before the attack lands.
PACE_LEAD_MS = 20_000


@dataclass(frozen=True)
class ReplayRequest:
    tier: str
    seed: int = 42
    speed: int = 0
    epoch_ms: Optional[int] = None
    hours: int = 3
    # Source: remediation plan FIX-011 (AUDIT-014). "episode" pages through the
    # pre-episode events at full tilt and engages `speed` pacing ~20 s of event
    # time before the attack. EVERY event is still scored, in the same order, at
    # the same virtual time -- only the wall-clock sleep changes, so determinism
    # is untouched (asserted by test_replay_pacing.py).
    pace_from: Optional[str] = None


@dataclass
class ReplayStatus:
    """The authoritative snapshot. Additive over Day 2's shape: every key it
    carried is still here and still means the same thing, so `test_sse.py`,
    `test_stream_recent.py` and the Day-2 consumers are unaffected."""

    state: str = "idle"  # idle | starting | running | stopping | stopped | finished | failed | resetting
    tier: Optional[str] = None
    seed: Optional[int] = None
    speed: Optional[int] = None
    sent: int = 0
    total: int = 0
    episode_id: Optional[str] = None
    virtual_time_ms: int = 0
    # --- remediation plan §7, all additive ---------------------------------
    run_id: Optional[str] = None        # minted at mark_starting; THE reset signal
    epoch_ms: Optional[int] = None      # which time domain this run lives in
    error: Optional[str] = None         # "<ExcType>: <msg>" when state == "failed"
    stop_reason: Optional[str] = None   # operator | reset | watchdog
    started_at_ms: Optional[int] = None
    updated_at_ms: int = 0
    pace_from: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> dict:
        return {
            "state": self.state, "tier": self.tier, "seed": self.seed, "speed": self.speed,
            "sent": self.sent, "total": self.total, "episode_id": self.episode_id,
            "virtual_time_ms": self.virtual_time_ms,
            "run_id": self.run_id, "epoch_ms": self.epoch_ms, "error": self.error,
            "stop_reason": self.stop_reason, "started_at_ms": self.started_at_ms,
            "updated_at_ms": self.updated_at_ms, "pace_from": self.pace_from,
            "terminal": self.is_terminal,
        }


# Lifecycle bookkeeping -- `updated_at_ms`, `started_at_ms` and the watchdog's
# progress stamp -- needs REAL elapsed time, and must keep needing it even when
# the scoring path is driven by a VirtualClock. It goes through `SystemClock`
# rather than `time.time()` for the reason TRD §4 gives and
# test_clock_discipline.py enforces: nothing outside packages/clock reads the
# wall clock directly. Deliberately NOT `state.clock`, which tests replace with
# a VirtualClock -- a frozen clock would freeze the watchdog with it.
_WALL = SystemClock()


def _now_ms() -> int:
    return _WALL.now_ms()


class ReplayDriver:
    def __init__(self, state: ScorerState, merchant_id: str) -> None:
        self._state = state
        self._merchant_id = merchant_id
        self._clock = VirtualClock(epoch_ms=0)
        self._status = ReplayStatus(state="idle", updated_at_ms=_now_ms())
        self._stop_requested = False
        # Source: remediation plan FIX-005 -- one lock serialises start / stop /
        # reset, which is what closes AUDIT-004's "status says idle while the
        # task is still scoring" window by construction.
        self._lifecycle_lock = asyncio.Lock()
        # Set by `run()` on EVERY exit path (finish, stop, exception, cancel),
        # so `stop()` and `reset()` can wait for a real acknowledgement instead
        # of guessing (AUDIT-003).
        self._stopped_event = asyncio.Event()
        self._stopped_event.set()  # nothing is running at construction
        self._last_progress_ms = 0
        self._watchdog_task: Optional[asyncio.Task] = None

    @property
    def clock(self) -> VirtualClock:
        return self._clock

    @property
    def status(self) -> ReplayStatus:
        """The LIVE status object. Callers that only read it immediately (the
        routes, `scoring.py`'s per-event snapshot) use this; anything that keeps
        the value must take `snapshot()` instead."""
        return self._status

    def snapshot(self) -> ReplayStatus:
        """An immutable-by-detachment copy.

        `ReplayStatus` is a mutable dataclass that `_set_status` updates in
        place, so handing `self._status` to a caller that KEEPS it means the
        caller's "finished" run silently becomes "resetting" the moment someone
        resets. Every method that returns a status to be held returns a copy."""
        return replace(self._status)

    @property
    def lifecycle_lock(self) -> asyncio.Lock:
        return self._lifecycle_lock

    # -- status writes ---------------------------------------------------

    def _set_status(self, **changes) -> ReplayStatus:
        """Every status write goes through here, so `updated_at_ms` is always
        stamped and no transition can be silent. The frontend's reducer drops
        any snapshot older than the one it holds, which is what makes an
        out-of-order control frame harmless."""
        for key, value in changes.items():
            setattr(self._status, key, value)
        self._status.updated_at_ms = _now_ms()
        return self.snapshot()

    def _finalize(self, **changes) -> None:
        """Record a terminal state -- unless a REASON has already been recorded.

        A run that has already said why it ended must not have that erased by
        the stop or the cancel that follows. The watchdog marks `failed` and
        then requests a stop; without this guard the loop's own stop branch (or
        `run()`'s CancelledError handler) would immediately overwrite `failed`
        with a bare `stopped`, and the operator would be told the run was
        stopped on purpose when in fact it died."""
        if self._status.state == "failed":
            return
        self._set_status(**changes)

    async def publish_status(self, *, reset: bool = False) -> None:
        """Source: remediation plan FIX-008 -- the low-latency transport for a
        lifecycle transition. Best-effort by design: the 1 s status poll is the
        path that survives a missed frame or a dead task, so a publish failure
        here must never propagate into a lifecycle transition."""
        frame = {
            "type": "replay_status",
            "replay": self._status.to_dict(),
            "reset": reset,
        }
        try:
            await self._state.event_bus.publish(frame)
        except Exception:  # noqa: BLE001 -- see docstring
            logger.exception("replay: failed to publish a %s control frame", self._status.state)

    # -- lifecycle transitions -------------------------------------------

    def mark_starting(self, request: ReplayRequest) -> str:
        """
        Synchronous, and deliberately so: `asyncio.create_task()` does not begin
        executing `run()` until the next event-loop iteration, so without a
        synchronous claim two rapid POST /v1/replay/start calls could both
        observe a non-busy state and both launch a driver. The caller holds
        `lifecycle_lock` across the check and this call.

        Returns the new `run_id` -- a fresh ULID per run, which is what makes a
        repeat run a REAL run rather than a 24-hour silent no-op (AUDIT-005),
        and what the frontend uses as its single reset signal (AUDIT-015).
        """
        run_id = self._state.ulid.new()
        self._stop_requested = False
        self._stopped_event = asyncio.Event()  # cleared: a run is now in flight
        self._last_progress_ms = _now_ms()
        self._status = ReplayStatus(
            state="starting", tier=request.tier, seed=request.seed, speed=request.speed,
            sent=0, total=0, episode_id=None, virtual_time_ms=0,
            run_id=run_id, epoch_ms=request.epoch_ms, error=None, stop_reason=None,
            started_at_ms=_now_ms(), updated_at_ms=_now_ms(),
            pace_from=request.pace_from,
        )
        return run_id

    async def stop(self, reason: str = "operator") -> ReplayStatus:
        """
        Source: remediation plan FIX-005 (AUDIT-003). Day 2 set a flag and
        serialised immediately, so the response was ALWAYS the pre-stop
        snapshot -- `running`, with a stale `sent`. This waits for the loop to
        acknowledge on `_stopped_event` and returns the true terminal snapshot.

        On timeout it returns `stopping`, never a stale `running`: the 1 s
        status poll resolves it a moment later. Bounded, so a wedged loop
        cannot hang the handler holding the lifecycle lock.
        """
        if self._status.is_terminal:
            return self.snapshot()
        self._stop_requested = True
        self._set_status(state="stopping", stop_reason=reason)
        await self.publish_status()
        try:
            await asyncio.wait_for(self._stopped_event.wait(), STOP_ACK_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(
                "replay: stop was not acknowledged within %.1fs; reporting 'stopping' "
                "(run_id=%s). The status poll will resolve the terminal state.",
                STOP_ACK_TIMEOUT_S, self._status.run_id,
            )
        return self.snapshot()

    async def _await_task_termination(self) -> bool:
        """Stop -> await -> cancel -> await. Returns True when nothing is
        running any more. Never clears state on a task that refuses to die --
        refusing to reset beats corrupting live detector state."""
        task = self._state.replay_task
        if task is None or task.done():
            return True

        self._stop_requested = True
        try:
            await asyncio.wait_for(asyncio.shield(task), STOP_ACK_TIMEOUT_S)
            return True
        except asyncio.TimeoutError:
            logger.warning("replay: task did not stop cooperatively; cancelling")
        except asyncio.CancelledError:
            return True
        except Exception:  # noqa: BLE001 -- the task's own failure is handled in run()
            return True

        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), CANCEL_ACK_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception:  # noqa: BLE001
            pass
        return task.done()

    def _clear_all(self) -> dict:
        """
        Source: remediation plan §9 -- clear each layer INDEPENDENTLY, each in
        its own try/except, and report per layer.

        Day 2 called `window_store.clear()` first with no guard. Under the
        documented Redis configuration that method did not exist, so an
        `AttributeError` on line 1 took the other five clears down with it and
        the route returned HTTP 500 (AUDIT-001). One missing method disabled
        every layer; now one failing layer disables only itself.
        """
        cleared: dict = {}

        def _try(name: str, fn) -> None:
            try:
                result = fn()
                cleared[name] = True if result is None else result
            except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
                logger.exception("replay reset: clearing %s failed", name)
                cleared[name] = False
                cleared[f"{name}_error"] = f"{type(exc).__name__}: {exc}"

        _try("window_store", lambda: self._state.window_store.clear(self._merchant_id))
        if self._state.threat is not None:
            _try("threat", self._state.threat.clear)
        if self._state.layer2 is not None:
            _try("layer2", self._state.layer2.reset)
        if self._state.incidents is not None:
            _try("incidents", self._state.incidents.clear)
        if self._state.policy_engine is not None:
            _try("policy_engine", self._state.policy_engine.clear)
        # Source: remediation plan F-E -- the in-process stored-decision cache
        # was never cleared. With Redis cleared but the cache retained, an
        # attempt could take `idempotent_replay=True` against zeroed features
        # and MISS the cache, falling through to full scoring on an empty
        # feature vector: silently wrong output, no error. Latent until
        # AUDIT-001 was fixed; cleared here so it never becomes reachable.
        _try("decision_cache", self._state.decision_cache.clear)
        # The in-process registry and the PERSISTED incident rows are two views
        # of "live". Clearing only the registry leaves the rows open in SQLite
        # with nothing behind them, so `GET /v1/incidents?state=live` -- which is
        # what D3 now reads (FIX-015) -- keeps serving the previous run's
        # incidents after a Reset, and they can never transition again. They are
        # closed with `resolution="reset"` rather than deleted: the audit trail
        # is preserved, and "live" becomes true again.
        _try("persisted_incidents", self._close_open_incident_rows)
        return cleared

    def _close_open_incident_rows(self) -> int:
        from packages.storage.repository import read_open_incidents, resolve_incident

        conn = connect(self._state.db_path)
        try:
            rows = read_open_incidents(conn, self._merchant_id)
            for row in rows:
                resolve_incident(
                    conn, row["incident_id"], resolution="reset",
                    resolved_by="reset", closed_at=_now_ms(),
                )
            return len(rows)
        finally:
            conn.close()

    async def reset(self, *, stop_reason: str = "reset") -> dict:
        """
        Source: remediation plan §9 (AUDIT-001, 004, 005, 015). The order is the
        whole point:

            cancel/stop -> AWAIT termination -> clear -> publish cleared -> idle

        Day 2 cleared first and never looked at `replay_task`, so the loop kept
        scoring and overwrote `status` on its next iteration: the UI showed
        `idle` while the backend was still running. The system must never report
        idle while the previous replay is alive, so if the task refuses to die
        this returns 409 and leaves state UNTOUCHED -- refusing beats corrupting.

        The caller holds `lifecycle_lock`.
        """
        self._set_status(state="resetting", stop_reason=stop_reason)
        await self.publish_status()

        if not await self._await_task_termination():
            logger.error("replay reset: the replay task is still alive; refusing to clear")
            self._set_status(state="running")
            await self.publish_status()
            return {"ok": False, "reason": "replay did not terminate; state left untouched"}

        self._state.replay_task = None
        cleared = self._clear_all()
        degraded = any(value is False for value in cleared.values())

        self._clock = VirtualClock(epoch_ms=0)
        self._stop_requested = False
        self._stopped_event = asyncio.Event()
        self._stopped_event.set()
        self._status = ReplayStatus(state="idle", updated_at_ms=_now_ms())
        await self.publish_status(reset=True)
        return {"ok": True, "cleared": cleared, "degraded": degraded}

    # -- supervision ------------------------------------------------------

    async def _watchdog(self, run_id: str, threshold_ms: int) -> None:
        """
        Source: remediation plan FIX-007. If the loop stops making progress
        without exiting, the status must stop claiming `running`.

        HONEST LIMITATION, stated here so nobody over-trusts it: this is an
        asyncio task, so it cannot fire while the loop is blocked by a
        SYNCHRONOUS spin -- it would not have caught AUDIT-006. That is
        FIX-002's job. This catches await-starvation, hung I/O and a task that
        stopped advancing; the loop-lag monitor in app.py leaves evidence in the
        log for the cases neither can preempt.
        """
        try:
            while True:
                await asyncio.sleep(WATCHDOG_POLL_S)
                if self._status.run_id != run_id or self._status.is_terminal:
                    return
                if self._status.state != "running":
                    continue
                stalled_ms = _now_ms() - self._last_progress_ms
                if stalled_ms > threshold_ms:
                    logger.error(
                        "replay watchdog: no progress for %d ms (threshold %d ms) at "
                        "%d/%d, run_id=%s -- marking the run failed",
                        stalled_ms, threshold_ms, self._status.sent, self._status.total, run_id,
                    )
                    self._set_status(
                        state="failed",
                        error=f"watchdog: no progress for {stalled_ms} ms",
                        stop_reason="watchdog",
                    )
                    await self.publish_status()
                    self._stop_requested = True
                    return
        except asyncio.CancelledError:
            return

    def _pace_from_ms(self, request: ReplayRequest, result) -> int:
        """Source: remediation plan FIX-011 (AUDIT-014). Events before this
        event-time offset are scored without sleeping. Returns 0 (uniform
        pacing, exactly Day 2's behaviour) when pacing is not requested or the
        stream carries no episode."""
        if request.pace_from != "episode" or not request.speed:
            return 0
        episodes = getattr(result, "episodes", None) or []
        if not episodes:
            logger.info("replay: pace_from='episode' but the stream has no episode; pacing uniformly")
            return 0
        return max(0, int(episodes[0].started_at) - PACE_LEAD_MS)

    # -- the loop ---------------------------------------------------------

    async def run(self, request: ReplayRequest, stream=None) -> ReplayStatus:
        """
        Source: remediation plan FIX-005 / FIX-007. Every exit path -- finished,
        stopped, failed, cancelled -- writes a terminal status, publishes a
        control frame and sets `_stopped_event`. Day 2's version had no
        `try/except` at all, so one exception left the status frozen at
        `running` forever with the task handle holding a strong reference that
        even suppressed asyncio's "never retrieved" warning (AUDIT-007).
        """
        run_id = self._status.run_id
        epoch_ms = request.epoch_ms if request.epoch_ms is not None else self._state.clock.now_ms()
        self._clock = VirtualClock(epoch_ms=epoch_ms)
        # Source: remediation plan §17 drainer gate -- `attempt_uid` must be
        # unique ACROSS runs, or the second run of a tier writes primary keys the
        # first already owns and `INSERT OR IGNORE` silently drops every row.
        # Measured: 20 runs x 821 events produced 16 420 scored attempts and just
        # 821 `attempt_score` rows. A repeat run was real on the wire and
        # invisible in the database.
        #
        # The run scope is applied ONLY when a run has an identity. Callers that
        # drive the driver directly and never call `mark_starting` -- the eval
        # corpus (`eval/corpus.py`) and A13's speed-0-vs-60 determinism test --
        # have `run_id is None`, so their ULID stream is byte-identical to what
        # shipped and the committed corpus and golden fixtures do not move.
        ulid_seed = f"ulid:{request.seed}" if run_id is None else f"ulid:{request.seed}:{run_id}"
        ulid = UlidGenerator(clock=self._clock, rng=random.Random(ulid_seed))
        # Source: remediation plan FIX-004 -- the run scope for idempotency
        # keys. Without it the second run of a tier produced byte-identical
        # digests, every SET NX found the previous run's key, and the whole run
        # was silently swallowed as an idempotent replay for 24 hours
        # (AUDIT-005).
        idem_namespace = f"r{run_id}:" if run_id else ""

        threshold_ms = WATCHDOG_PACED_MS if request.speed else WATCHDOG_UNPACED_MS
        self._watchdog_task = asyncio.create_task(self._watchdog(run_id, threshold_ms))

        try:
            if stream is None:
                from packages.simulator.generate import build_stream  # local: keep off the storefront's import graph

                result = build_stream(seed=request.seed, tier=request.tier, hours=request.hours)
                events = result.events
                episode_id = result.episodes[0].episode_id if result.episodes else None
                pace_from_ms = self._pace_from_ms(request, result)
            else:
                events = list(stream)
                episode_id = None
                pace_from_ms = 0

            total = len(events)
            self._set_status(
                state="running", total=total, sent=0, episode_id=episode_id,
                virtual_time_ms=epoch_ms, epoch_ms=epoch_ms,
            )
            self._last_progress_ms = _now_ms()
            await self.publish_status()

            prev_t_ms = 0
            for index, ev in enumerate(events):
                if self._stop_requested:
                    self._finalize(
                        state="stopped", sent=index, virtual_time_ms=self._clock.now_ms(),
                        stop_reason=self._status.stop_reason or "operator",
                    )
                    await self.publish_status()
                    return self.snapshot()

                self._clock.set_ms(epoch_ms + ev.t_ms)
                body = ScoreRequest(**ev.to_score_request())
                await score_attempt(
                    self._state, merchant_id=self._merchant_id, ip=ev.ip, body=body,
                    clock=self._clock, ulid=ulid, idem_namespace=idem_namespace,
                )

                # `sent` is written BEFORE the pacing sleep and before the next
                # iteration's publish, so the last event's own SSE frame no
                # longer reports `sent = total - 1` (AUDIT-002).
                self._set_status(sent=index + 1, virtual_time_ms=self._clock.now_ms())
                self._last_progress_ms = _now_ms()

                if request.speed and ev.t_ms >= pace_from_ms:
                    delta_ms = ev.t_ms - prev_t_ms
                    if delta_ms > 0:
                        await asyncio.sleep(delta_ms / 1000 / request.speed)
                else:
                    # Cooperative yield. Without it an unpaced replay never
                    # awaits anything that suspends -- an uncontended
                    # asyncio.Lock and an unbounded Queue.put both complete
                    # without yielding -- so the whole run monopolises the event
                    # loop and /healthz, /v1/score and even the reply to
                    # /v1/replay/start itself are queued behind it. Measured at
                    # 6.4 s for one easy replay on Redis.
                    await asyncio.sleep(0)
                prev_t_ms = ev.t_ms

            self._finalize(state="finished", sent=total, virtual_time_ms=self._clock.now_ms())
            await self.publish_status()
            return self.snapshot()

        except asyncio.CancelledError:
            self._finalize(
                state="stopped", virtual_time_ms=self._clock.now_ms(),
                stop_reason=self._status.stop_reason or "reset",
            )
            # Published best-effort: on a cancel the frame may not make it out,
            # which is exactly why the status poll exists.
            await self.publish_status()
            raise
        except Exception as exc:  # noqa: BLE001 -- recorded on the status, never swallowed
            logger.exception("replay: run failed at %d/%d", self._status.sent, self._status.total)
            self._set_status(
                state="failed", error=f"{type(exc).__name__}: {exc}",
                virtual_time_ms=self._clock.now_ms(),
            )
            await self.publish_status()
            return self.snapshot()
        finally:
            self._stopped_event.set()
            if self._watchdog_task is not None:
                self._watchdog_task.cancel()
                self._watchdog_task = None
