"""
Source: Day 9 Plan Phase 3 -- J6 steps 6-8. Every demo control here is
GATED behind `TOLLGATE_DEMO_CONTROLS=1` (default OFF) and every one exercises
a REAL code path -- no faked decision, tier or availability state (stop
condition S-3).

  step 6  GET /v1/demo/cotenant-ip     -- one IP currently under enforcement,
                                          for the CGNAT co-tenant checkout.
  step 7  POST /v1/demo/flood          -- starts / stops a REAL concurrent
                                          load against /v1/score that drains
                                          the merchant token bucket exactly as
                                          a flood would (-> the rules-only shed
                                          rung). Never sets `shed` directly.
  step 8  POST /v1/demo/fault          -- flips a runtime flag; the /v1/score
                                          handler then raises BEFORE
                                          score_attempt(), driving the real
                                          `_fail_open` path. Inert without the
                                          env gate.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("tollgate.scorer.demo")

_TRUE = {"1", "true", "yes", "on"}


def demo_controls_enabled() -> bool:
    """The master gate. Everything in routes_demo.py 404s / no-ops unless this
    is set, so production / default behaviour is unambiguously distinguishable
    (Plan Phase 3 / §8)."""
    return os.environ.get("TOLLGATE_DEMO_CONTROLS", "").strip().lower() in _TRUE


class DemoFloodRunner:
    """A bounded, real HTTP load generator. It fires concurrent
    `POST /v1/score` at the scorer's own port so every request goes through the
    genuine auth -> AdmissionController.try_consume -> shed path. Draining the
    merchant token bucket (`rate_per_s 50 / burst 200`, config/policy.yaml) is
    what makes a subsequent real checkout land on the rules-only shed rung --
    the flood is never a flag that sets `shed`.

    Needs a valid merchant key. Under Compose the scorer entrypoint sources
    `deploy/compose.env`, so `VITE_TOLLGATE_API_KEY` is in the environment; on
    the bare manual path it is not, and start() refuses loudly.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        concurrency: int = 250,
        max_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # One in-flight POST per worker, always. Well above the merchant
        # `rate_per_s 50 / burst 200` bucket so it drains in ~1-2 s and stays
        # empty -- exactly a real flood, never a `shed` flag.
        self._concurrency = concurrency
        self._max_seconds = max_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.sent = 0
        self.shed_seen = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        key = os.environ.get("VITE_TOLLGATE_API_KEY") or os.environ.get("TOLLGATE_API_KEY")
        if not key:
            raise RuntimeError(
                "demo flood needs a merchant key in the environment "
                "(VITE_TOLLGATE_API_KEY). Run the Compose stack, or export it."
            )
        if self.running:
            return
        self._stop.clear()
        self.sent = 0
        self.shed_seen = 0
        self._task = asyncio.create_task(self._run(key))
        logger.warning("demo flood STARTED (concurrency %d, <= %.0fs)",
                       self._concurrency, self._max_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._task = None
        logger.warning("demo flood STOPPED (sent=%d, shed_responses=%d)", self.sent, self.shed_seen)

    async def _run(self, key: str) -> None:
        import httpx

        headers = {"X-Tollgate-Key": key, "Content-Type": "application/json"}
        deadline = time.monotonic() + self._max_seconds
        limits = httpx.Limits(
            max_connections=self._concurrency + 20,
            max_keepalive_connections=self._concurrency + 20,
        )

        async def worker(w: int) -> None:
            n = 0
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=10.0, limits=limits
            ) as client:
                while not self._stop.is_set() and time.monotonic() < deadline:
                    try:
                        r = await client.post(
                            "/v1/score",
                            headers=headers,
                            json={
                                # monotonic_ns, not wall time (test_clock_discipline)
                                "event_id": f"demo-flood-{w}-{n}-{time.monotonic_ns()}",
                                "card_hash": f"demo-flood-card-{(w * 131 + n) % 97}",
                                "bin": "999900",
                                "amount_minor": 100000,
                                "currency": "INR",
                            },
                        )
                        self.sent += 1
                        if r.headers.get("X-Tollgate-Shed") == "1":
                            self.shed_seen += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001
                        pass
                    n += 1

        try:
            await asyncio.gather(*(worker(w) for w in range(self._concurrency)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("demo flood errored: %r", exc)
