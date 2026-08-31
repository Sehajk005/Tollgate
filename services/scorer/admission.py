"""
Source: Day-7 Plan §4 Step 3 / Step 4 -- merchant-scoped admission control and
availability monitoring, all in-process on `ScorerState` (Decision 71's
precedent: hot-path counters never take a second Redis round trip).

  TokenBucket        -- lazy-refill leaky bucket, driven by the injected clock;
                        no background timer, no wall-clock read.
  AdmissionController -- one TokenBucket per merchant_id, so one merchant's
                        flood cannot shed another merchant's traffic.
  AvailabilityMonitor-- a clock-driven rolling count of fail-opens per
                        merchant; past a threshold it raises `alert` and logs
                        ERROR once per window (that once-per-window suppression
                        IS the alert rate limit). The response stays `allow`.

`config/policy.yaml`'s `admission:` block carries the tunables in the existing
{value, unit, source} shape; `load_admission_config()` flattens it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

import yaml

logger = logging.getLogger("tollgate.scorer.admission")

DEFAULT_POLICY_YAML = Path("config/policy.yaml")


@dataclass(frozen=True)
class AdmissionConfig:
    rate_per_s: float
    burst: float
    shed_ttl_s: int
    fail_open_budget_per_min: int
    fail_open_alert_threshold: int

    @property
    def shed_ttl_ms(self) -> int:
        return self.shed_ttl_s * 1000


def load_admission_config(policy_yaml: Path = DEFAULT_POLICY_YAML) -> AdmissionConfig:
    """Parse `config/policy.yaml`'s `admission:` block ({value, unit, source}
    leaves) into a flat AdmissionConfig. Raises KeyError if the block is
    absent -- admission control is not optional on Day 7."""
    raw = yaml.safe_load(Path(policy_yaml).read_text(encoding="utf-8"))
    adm = raw["admission"]

    def v(node):
        return node["value"] if isinstance(node, dict) and "value" in node else node

    return AdmissionConfig(
        rate_per_s=float(v(adm["rate_per_s"])),
        burst=float(v(adm["burst"])),
        shed_ttl_s=int(v(adm["shed_ttl_s"])),
        fail_open_budget_per_min=int(v(adm["fail_open_budget_per_min"])),
        fail_open_alert_threshold=int(v(adm["fail_open_alert_threshold"])),
    )


class TokenBucket:
    """A leaky token bucket refilled lazily from the injected clock. `burst`
    is the capacity; `rate_per_s` is the sustained fill rate. `try_consume`
    advances the fill to `now_ms` first, so no background timer is needed and
    no wall-clock call is made (Day-7 critical constraint)."""

    __slots__ = ("_rate_per_s", "_capacity", "_tokens", "_last_ms")

    def __init__(self, *, rate_per_s: float, burst: float) -> None:
        self._rate_per_s = float(rate_per_s)
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._last_ms: "int | None" = None

    def try_consume(self, now_ms: int, cost: float = 1.0) -> bool:
        if self._last_ms is None:
            self._last_ms = now_ms
        elapsed_ms = now_ms - self._last_ms
        if elapsed_ms > 0:
            self._tokens = min(
                self._capacity, self._tokens + (elapsed_ms / 1000.0) * self._rate_per_s
            )
            self._last_ms = now_ms
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False


class AdmissionController:
    """One `TokenBucket` per merchant_id. The budget is merchant-scoped so a
    flood against merchant A never sheds merchant B's traffic (Day-7 §5
    acceptance row 5 / Threat Model §2)."""

    def __init__(self, config: AdmissionConfig) -> None:
        self._config = config
        self._buckets: Dict[str, TokenBucket] = {}

    @property
    def config(self) -> AdmissionConfig:
        return self._config

    def try_consume(self, merchant_id: str, now_ms: int) -> bool:
        bucket = self._buckets.get(merchant_id)
        if bucket is None:
            bucket = TokenBucket(
                rate_per_s=self._config.rate_per_s, burst=self._config.burst
            )
            self._buckets[merchant_id] = bucket
        return bucket.try_consume(now_ms)


@dataclass
class _MerchantAvailability:
    events_ms: list = field(default_factory=list)  # fail-open timestamps in the live window
    alerting: bool = False
    last_alert_window_ms: "int | None" = None


class AvailabilityMonitor:
    """Per-merchant rolling count of fail-opens over a clock-driven window
    (`window_ms`, default 60 s). Past `alert_threshold` in one window it sets
    `alert=True` and logs ERROR exactly once per window -- that suppression is
    the rate limit. The score response is ALWAYS `allow` regardless (Day-7
    Decision 89); exhausting the budget makes a silent degradation loud, never
    a 5xx and never a different tier."""

    def __init__(self, *, alert_threshold: int, window_ms: int = 60_000) -> None:
        self._alert_threshold = int(alert_threshold)
        self._window_ms = int(window_ms)
        self._by_merchant: Dict[str, _MerchantAvailability] = {}

    def record_fail_open(self, merchant_id: str, now_ms: int, reason: str) -> bool:
        """Record one fail-open; return True iff this is the (single) alert
        emission for the current window."""
        st = self._by_merchant.get(merchant_id)
        if st is None:
            st = _MerchantAvailability()
            self._by_merchant[merchant_id] = st

        floor = now_ms - self._window_ms
        st.events_ms = [t for t in st.events_ms if t > floor]
        st.events_ms.append(now_ms)

        over = len(st.events_ms) >= self._alert_threshold
        st.alerting = over

        window_index = now_ms // self._window_ms
        if over and st.last_alert_window_ms != window_index:
            st.last_alert_window_ms = window_index
            logger.error(
                "availability: merchant %s exceeded the fail-open budget "
                "(%d fail-opens in %d ms, reason=%s); responses stay allow",
                merchant_id, len(st.events_ms), self._window_ms, reason,
            )
            return True
        return False

    def is_alerting(self, merchant_id: str, now_ms: int) -> bool:
        st = self._by_merchant.get(merchant_id)
        if st is None:
            return False
        floor = now_ms - self._window_ms
        live = [t for t in st.events_ms if t > floor]
        return len(live) >= self._alert_threshold
