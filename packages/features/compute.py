"""
Source: TRD v2 §6.4 -- "packages/features/compute.py is THE definition."
One feature implementation, talking to a `WindowStore` protocol; two
backends (Redis, in-memory) implement that protocol so the online score
path and (from Day 4 onward) the offline eval harness read the identical
definition. Day-3 Plan Step 5.

24 features, TRD §6.8's v2.1-corrected enumeration, fixed order
(FEATURE_NAMES). Un-fed slots -- no `store_baseline` row, no `/v1/outcome`,
no `bin_metadata`, no client `ts` on the wire; none of these exist before
Day 4/7 (Day-3 Plan §2 D5) -- emit a defined neutral value rather than NaN
or None, so "no NaN or infinity in any feature, ever" holds by construction
and the vector's shape is stable from tonight through Day 7; only values
change as each upstream lands.

Two raw window statistics (attempts_per_ip_60s, distinct_cards_per_bin_5m)
are both R1/R3's rule floor AND canonical model features -- Decision 17
carves rule floors out as absolute-count statistics that must work from
install-minute-zero, independent of any learned baseline, so they are not
quantile-transformed. R2's underlying statistic (distinct_cards_per_ip_5m)
has no un-suffixed canonical sibling -- only its quantile-transformed
_q form is in FEATURE_NAMES -- so its raw count is carried separately on
FeatureVector for DayOneRules.evaluate_from_features() to read.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from packages.features.store import ScorePathRequest, WindowRequest, WindowStore

WINDOW_60S_MS = 60_000
WINDOW_5M_MS = 5 * 60_000
WINDOW_30M_MS = 30 * 60_000

# Source: TRD §6.1 -- "TTLs are set generously and no feature depends on
# one"; these are memory hygiene only, never correctness. 24h TTLs on the
# idempotency key match card24's own 24h horizon.
IDEM_TTL_MS = 24 * 60 * 60 * 1000
CARD24_TTL_MS = 24 * 60 * 60 * 1000
WINDOW_TTL_SLACK_MS = 60_000

# Source: TRD §6.5 -- CUSUM bucket width; overridden by
# policy_config.cusum_bucket_s from Day 6 onward. Day 3 only builds the
# raw per-bucket attempt counter TRD §6.3 step 5 names (Day-3 Plan §2 D3);
# the S_t statistic itself is Day 6 scope.
CUSUM_BUCKET_S = 10

FEATURE_NAMES: Tuple[str, ...] = (
    "attempts_per_ip_60s",
    "attempts_per_ip_5m",
    "attempts_per_ipua_5m",
    "distinct_cards_per_ip_5m_q",
    "distinct_cards_per_ipua_5m_q",
    "distinct_bins_per_ip_5m",
    "distinct_ips_per_bin_5m",
    "distinct_cards_per_bin_5m",
    "attempts_per_session",
    "card_seen_24h",
    "bin_hhi_5m",
    "bin_entropy_5m",
    "bin_is_foreign_issued",
    "foreign_bin_share_5m",
    "foreign_bin_share_sigma",
    "amount_percentile_vs_store",
    "distinct_amounts_per_ip_5m",
    "store_volume_deviation_sigma",
    "store_decline_rate_deviation_sigma",
    "decline_rate_per_ip_5m",
    "invalid_cvv_share_ip_5m",
    "outcome_coverage_ratio",
    "event_id_reuse_count",
    "clock_skew_s",
)
assert len(FEATURE_NAMES) == 24

UA_CLASSES = ("desktop_browser", "mobile_browser", "known_bot", "headless", "unparseable")


def classify_ua(user_agent: Optional[str]) -> str:
    """
    Source: Threat Model v2 §5/3 -- deterministic five-value classifier.
    The *class* is a window-key component; the raw user_agent string is
    never stored in a key, never a feature, and never leaves the database
    (Threat Model §5/3, §2 -- user_agent is C-class, evidence-panel only).
    """
    ua = (user_agent or "").lower()
    if not ua:
        return "unparseable"
    if "headless" in ua or "phantomjs" in ua:
        return "headless"
    if any(tok in ua for tok in ("bot", "spider", "crawler", "curl", "python-requests")):
        return "known_bot"
    if any(tok in ua for tok in ("mobile", "android", "iphone", "ipad")):
        return "mobile_browser"
    if any(tok in ua for tok in ("mozilla", "chrome", "safari", "firefox", "edg")):
        return "desktop_browser"
    return "unparseable"


def ipua_key(ip: str, ua_class: str) -> str:
    """Source: TRD §6.2 -- ipua = sha1(ip || ua_class); the class, never the raw UA string."""
    return hashlib.sha1(f"{ip}|{ua_class}".encode("utf-8")).hexdigest()


def _finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"feature {name!r} computed a non-finite value: {value!r}")
    return value


def _bin_concentration(bin_members: Tuple[str, ...]) -> Tuple[float, float]:
    """
    Source: TRD §6.8 -- bin_hhi_5m, bin_entropy_5m. `bin_members` entries
    are "{bin}|{attempt_uid}" -- a unique member per event, so the sorted
    set retains every occurrence rather than collapsing repeats the way
    the plain distinct-count metrics do. HHI = sum(p_i^2); entropy uses
    natural log, 0.0 for a single-BIN window (matches the "single-BIN
    window -> HHI = 1.0; uniform over n -> entropy = ln n" analytic
    expectations, Impl Plan §1.1).
    """
    if not bin_members:
        return 0.0, 0.0
    counts: Dict[str, int] = {}
    for raw in bin_members:
        bin_value = raw.split("|", 1)[0]
        counts[bin_value] = counts.get(bin_value, 0) + 1
    total = sum(counts.values())
    hhi = sum((c / total) ** 2 for c in counts.values())
    if len(counts) <= 1:
        entropy = 0.0
    else:
        entropy = -sum((c / total) * math.log(c / total) for c in counts.values())
    return hhi, entropy


@dataclass(frozen=True)
class FeatureContext:
    merchant_id: str
    attempt_uid: str
    ingest_ms: int
    payload_digest: str
    event_id: str
    ip: str
    ua_class: str
    card_hash: str
    bin: str
    amount_minor: int
    session_id: Optional[str]


@dataclass(frozen=True)
class FeatureVector:
    values: Dict[str, float]
    trusted: bool
    degraded_reason: Optional[str]
    idempotent_replay: bool
    stored_attempt_uid: Optional[str]
    baseline_coverage: float
    # Source: Day-7 Plan §4 Step 2 -- the idempotency digest is already
    # computed here (sha256(merchant || event_id || payload_digest)); surface
    # it so services/scorer/scoring.py can key its in-process stored-decision
    # cache off it without re-deriving the hash. Defaulted, like
    # distinct_cards_per_ip_5m_raw; NOT in snapshot() or FEATURE_NAMES, so the
    # model contract and the training corpus are byte-identical to Day 6.
    idem_digest: str = ""
    # Source: Decision 17 -- R2's rule floor reads the raw absolute count,
    # not the quantile-transformed model feature. See module docstring.
    distinct_cards_per_ip_5m_raw: float = 0.0
    # Source: Day-6 Plan §3.2 / D6 -- L2b's required input, an 11th window in
    # the SAME score_path() round trip. Surfaced here (defaulted, like
    # distinct_cards_per_ip_5m_raw), NOT in FEATURE_NAMES and NOT in
    # snapshot(), so the 24-feature model contract and the training corpus
    # are byte-identical to Day 5.
    distinct_cards_per_ip_30m_raw: float = 0.0
    # Source: Day-6 Plan §3.1 -- windows.lua step 6 / the in-memory
    # score_path compute the CUSUM bucket index/count and return them across
    # the protocol boundary; Day 3-5 dropped them on the floor. Plumbed
    # through here for Layer 2a. Also NOT in snapshot() / FEATURE_NAMES.
    cusum_bucket_index: int = 0
    cusum_bucket_count: int = 0

    def snapshot(self) -> dict:
        data: dict = dict(self.values)
        data["trusted"] = self.trusted
        data["baseline_coverage"] = self.baseline_coverage
        if self.degraded_reason is not None:
            data["degraded_reason"] = self.degraded_reason
        return data


def compute_features(store: WindowStore, ctx: FeatureContext) -> FeatureVector:
    """
    Source: TRD §6.3 -- one atomic call covers idempotency, every window,
    event_id-reuse, the 24h card counter, and the CUSUM bucket. Exactly one
    store.score_path() call per invocation (asserted by
    tests/acceptance/test_one_round_trip.py).
    """
    ipua = ipua_key(ctx.ip, ctx.ua_class)
    # Source: Day-3 Plan Step 5 implementer note -- ScoreRequest.session_id
    # is optional; a shared literal key across every sessionless attempt
    # (regardless of caller) would collapse unrelated entities into one
    # window, so sessionless attempts fall back to IP scoping instead.
    session_key = ctx.session_id if ctx.session_id else f"nosession:{ctx.ip}"

    def w(space: str, key: str, metric: str, member: str, window_ms: int, read: str = "count") -> WindowRequest:
        return WindowRequest(
            merchant_id=ctx.merchant_id, space=space, key=key, metric=metric,
            member=member, ingest_ms=ctx.ingest_ms, window_ms=window_ms, read=read,
        )

    windows = (
        w("ip", ctx.ip, "ev", ctx.attempt_uid, WINDOW_60S_MS),                                      # 0: attempts_per_ip_60s
        w("ip", ctx.ip, "ev", ctx.attempt_uid, WINDOW_5M_MS),                                        # 1: attempts_per_ip_5m
        w("ipua", ipua, "ev", ctx.attempt_uid, WINDOW_5M_MS),                                        # 2: attempts_per_ipua_5m
        w("ip", ctx.ip, "card", ctx.card_hash, WINDOW_5M_MS),                                        # 3: distinct_cards_per_ip_5m (raw)
        w("ip", ctx.ip, "bin", ctx.bin, WINDOW_5M_MS),                                               # 4: distinct_bins_per_ip_5m
        w("bin", ctx.bin, "ip", ctx.ip, WINDOW_5M_MS),                                               # 5: distinct_ips_per_bin_5m (D2)
        w("bin", ctx.bin, "card", ctx.card_hash, WINDOW_5M_MS),                                      # 6: distinct_cards_per_bin_5m
        w("session", session_key, "ev", ctx.attempt_uid, WINDOW_30M_MS),                             # 7: attempts_per_session
        w("ip", ctx.ip, "bindist", f"{ctx.bin}|{ctx.attempt_uid}", WINDOW_5M_MS, read="members"),    # 8: bin_hhi/entropy
        w("ip", ctx.ip, "amt", str(ctx.amount_minor), WINDOW_5M_MS),                                 # 9: distinct_amounts_per_ip_5m
        # Source: Day-6 Plan §3.2 / D6 -- L2b's distinct_cards_per_ip_30m,
        # appended at index 10 so no existing positional index shifts and the
        # round trip stays at exactly one score_path() call.
        w("ip", ctx.ip, "card", ctx.card_hash, WINDOW_30M_MS),                                        # 10: distinct_cards_per_ip_30m (raw)
    )

    # Source: Threat Model v2 §3 point 2 -- the idempotency key is
    # sha256(merchant_id || event_id || payload_digest), deliberately NOT
    # payload_digest alone: card-testing traffic legitimately repeats the
    # same M-class fields (card_hash, bin, amount) across many distinct
    # attempts, each with its own event_id. Keying on payload_digest alone
    # would silently collapse that entire attack pattern into one
    # idempotent no-op after the first attempt -- exactly the traffic this
    # system exists to see.
    idem_digest = hashlib.sha256(
        f"{ctx.merchant_id}|{ctx.event_id}|{ctx.payload_digest}".encode("utf-8")
    ).hexdigest()

    request = ScorePathRequest(
        merchant_id=ctx.merchant_id,
        ingest_ms=ctx.ingest_ms,
        idem_digest=idem_digest,
        payload_digest=ctx.payload_digest,
        attempt_uid=ctx.attempt_uid,
        idem_ttl_ms=IDEM_TTL_MS,
        event_id=ctx.event_id,
        card_hash=ctx.card_hash,
        card24_ttl_ms=CARD24_TTL_MS,
        windows=windows,
        cusum_bucket_s=CUSUM_BUCKET_S,
        window_ttl_slack_ms=WINDOW_TTL_SLACK_MS,
    )
    snap = store.score_path(request)
    counts = snap.counts
    members = snap.members

    bin_members = members[8] or ()
    bin_hhi, bin_entropy = _bin_concentration(bin_members)

    values: Dict[str, float] = {
        "attempts_per_ip_60s": float(counts[0]),
        "attempts_per_ip_5m": float(counts[1]),
        "attempts_per_ipua_5m": float(counts[2]),
        # Source: Day-3 Plan §2 D5 -- store_baseline row does not exist
        # until Day 4; the quantile transform is undefined without it.
        "distinct_cards_per_ip_5m_q": 0.0,
        "distinct_cards_per_ipua_5m_q": 0.0,
        "distinct_bins_per_ip_5m": float(counts[4]),
        "distinct_ips_per_bin_5m": float(counts[5]),
        "distinct_cards_per_bin_5m": float(counts[6]),
        "attempts_per_session": float(counts[7]),
        "card_seen_24h": float(snap.card_seen_24h),
        "bin_hhi_5m": bin_hhi,
        "bin_entropy_5m": bin_entropy,
        # Source: Day-3 Plan §2 D5 -- bin_metadata is not populated yet;
        # an unknown BIN is treated as domestic, a stated convention.
        "bin_is_foreign_issued": 0.0,
        "foreign_bin_share_5m": 0.0,
        "foreign_bin_share_sigma": 0.0,
        "amount_percentile_vs_store": 0.0,
        "distinct_amounts_per_ip_5m": float(counts[9]),
        "store_volume_deviation_sigma": 0.0,
        "store_decline_rate_deviation_sigma": 0.0,
        # Source: Day-3 Plan §2 D5 -- /v1/outcome ships Day 7; no decline
        # data exists yet.
        "decline_rate_per_ip_5m": 0.0,
        "invalid_cvv_share_ip_5m": 0.0,
        "outcome_coverage_ratio": 0.0,
        "event_id_reuse_count": float(snap.event_id_reuse_count),
        # Source: Day-3 Plan §2 D5 -- ScoreRequest carries no client `ts`;
        # adding one is a wire change out of Day-3 scope.
        "clock_skew_s": 0.0,
    }

    for name in FEATURE_NAMES:
        values[name] = _finite(name, values[name])

    return FeatureVector(
        values=values,
        trusted=snap.trusted,
        degraded_reason=snap.degraded_reason,
        idempotent_replay=snap.idempotent_replay,
        stored_attempt_uid=snap.stored_attempt_uid,
        baseline_coverage=0.0,
        idem_digest=idem_digest,
        distinct_cards_per_ip_5m_raw=float(counts[3]),
        distinct_cards_per_ip_30m_raw=float(counts[10]),
        cusum_bucket_index=int(snap.cusum_bucket_index),
        cusum_bucket_count=int(snap.cusum_bucket_count),
    )
