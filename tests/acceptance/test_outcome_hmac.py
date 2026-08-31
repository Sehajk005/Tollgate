"""
Source: Day-7 Plan §4 Step 5, acceptance rows 10-12 (Threat Model §4/P5).
POST /v1/outcome:

  valid + signed        -> 200, one auth_outcome row with sig_verified = 1
  unsigned              -> 401, no row
  tampered body         -> 401, no row
  stale timestamp       -> 401, no row
  replayed nonce        -> 1st 200, 2nd 409, still exactly one auth_outcome row

The signing secret comes from TOLLGATE_OUTCOME_SECRET and is bound to the
merchant via the existing `outcome_hmac_key_hash` -- the conftest seeds it as
`hash_api_key("outcome-secret")`, so that string is the secret here.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from packages.storage.db import connect

SECRET = "outcome-secret"
MERCHANT_ID = "merchant_test"


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _sign(merchant_id: str, ts_ms: int, nonce: str, body: dict) -> str:
    body_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    signing_string = f"{merchant_id}\n{ts_ms}\n{nonce}\n{body_hash}"
    return hmac.new(SECRET.encode("utf-8"), signing_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _full_body(event_id: str, *, gateway_status: str = "authorized") -> dict:
    """The exact dict `OutcomeRequest.model_dump()` produces -- optional fields
    present as null so the client and server canonicalise identically."""
    return {
        "event_id": event_id,
        "gateway_status": gateway_status,
        "reached_gateway": True,
        "decline_code": None,
        "gateway_latency_ms": None,
        "auth_fee_minor": None,
    }


@pytest.fixture
def outcome_ctx(client, scorer_state, monkeypatch):
    monkeypatch.setenv("TOLLGATE_OUTCOME_SECRET", SECRET)
    key = client.tollgate_api_key

    def score(event_id: str) -> None:
        resp = client.post(
            "/v1/score",
            json={"event_id": event_id, "card_hash": "c-o", "bin": "999123",
                  "amount_minor": 1000, "currency": "INR"},
            headers={"X-Tollgate-Key": key},
        )
        assert resp.status_code == 200
        scorer_state.drainer.drain_once()

    def outcome_headers(ts_ms: int, nonce: str, body: dict, *, sig: "str | None" = None) -> dict:
        return {
            "X-Tollgate-Key": key,
            "X-Tollgate-Signature": sig if sig is not None else _sign(MERCHANT_ID, ts_ms, nonce, body),
            "X-Tollgate-Timestamp": str(ts_ms),
            "X-Tollgate-Nonce": nonce,
        }

    return client, scorer_state, score, outcome_headers


def _count_outcomes(db_path) -> int:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM auth_outcome").fetchone()["c"]
    finally:
        conn.close()


class TestOutcomeHmac:
    def test_valid_signed_outcome_is_recorded_with_sig_verified(self, outcome_ctx):
        client, state, score, headers = outcome_ctx
        score("evt-ok")
        now = state.clock.now_ms()
        body = _full_body("evt-ok")

        resp = client.post("/v1/outcome", json=body, headers=headers(now, "nonce-ok", body))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "recorded"}

        conn = connect(state.db_path)
        try:
            row = conn.execute(
                "SELECT o.sig_verified AS sv FROM auth_outcome o "
                "JOIN auth_attempt a ON a.attempt_uid = o.attempt_uid "
                "WHERE a.event_id = 'evt-ok'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row["sv"] == 1

    def test_unsigned_outcome_is_rejected(self, outcome_ctx):
        client, state, score, _headers = outcome_ctx
        score("evt-unsigned")
        resp = client.post("/v1/outcome", json=_full_body("evt-unsigned"))
        assert resp.status_code == 401
        assert _count_outcomes(state.db_path) == 0

    def test_tampered_body_is_rejected(self, outcome_ctx):
        client, state, score, headers = outcome_ctx
        score("evt-tamper")
        now = state.clock.now_ms()
        signed_body = _full_body("evt-tamper", gateway_status="authorized")
        hdrs = headers(now, "nonce-tamper", signed_body)
        # send a DIFFERENT body under the signature computed for `signed_body`
        tampered = _full_body("evt-tamper", gateway_status="declined")

        resp = client.post("/v1/outcome", json=tampered, headers=hdrs)
        assert resp.status_code == 401
        assert _count_outcomes(state.db_path) == 0

    def test_stale_timestamp_is_rejected(self, outcome_ctx):
        client, state, score, headers = outcome_ctx
        score("evt-stale")
        stale_ts = state.clock.now_ms() - 400_000  # > 5 minutes old
        body = _full_body("evt-stale")

        resp = client.post("/v1/outcome", json=body, headers=headers(stale_ts, "nonce-stale", body))
        assert resp.status_code == 401
        assert _count_outcomes(state.db_path) == 0

    def test_replayed_nonce_is_rejected_and_leaves_one_row(self, outcome_ctx):
        client, state, score, headers = outcome_ctx
        score("evt-replay")
        now = state.clock.now_ms()
        body = _full_body("evt-replay")
        hdrs = headers(now, "nonce-replay", body)

        first = client.post("/v1/outcome", json=body, headers=hdrs)
        assert first.status_code == 200

        second = client.post("/v1/outcome", json=body, headers=hdrs)
        assert second.status_code == 409

        assert _count_outcomes(state.db_path) == 1

    def test_outcome_route_is_503_without_the_secret(self, client, scorer_state, monkeypatch):
        monkeypatch.delenv("TOLLGATE_OUTCOME_SECRET", raising=False)
        resp = client.post("/v1/outcome", json=_full_body("evt-x"))
        assert resp.status_code == 503
