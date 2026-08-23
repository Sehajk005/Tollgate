"""
Source: Implementation Plan v2.1 Day 1 -- contract tests 1-4, plus
resolve_client_outcome coverage for decision 18 / finding N2.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts.decision import (
    ClientOutcome,
    Decision,
    UI_ROUTING_TABLE,
    resolve_client_outcome,
)
from packages.contracts.wire import ScoreRequest, ScoreResponse

VALID_REQUEST_KWARGS = dict(
    event_id="evt_1",
    card_hash="card_1",
    bin="411111",
    amount_minor=100,
    currency="INR",
)


class TestRoundTrip:
    # Source: Impl Plan Day 1 acceptance test 1 -- "Round-trip all contracts"
    def test_score_request_round_trips(self):
        req = ScoreRequest(**VALID_REQUEST_KWARGS)
        rebuilt = ScoreRequest.model_validate_json(req.model_dump_json())
        assert rebuilt == req

    def test_score_response_round_trips(self):
        resp = ScoreResponse(attempt_uid="01AAA", decision=Decision.ALLOW, latency_ms=5)
        rebuilt = ScoreResponse.model_validate_json(resp.model_dump_json())
        assert rebuilt == resp


class TestMissingRequiredFields:
    # Source: Impl Plan Day 1 acceptance test 2 -- "missing required field raises"
    @pytest.mark.parametrize(
        "missing_field", ["event_id", "card_hash", "bin", "amount_minor", "currency"]
    )
    def test_missing_required_field_rejected(self, missing_field):
        kwargs = dict(VALID_REQUEST_KWARGS)
        del kwargs[missing_field]
        with pytest.raises(ValidationError):
            ScoreRequest(**kwargs)


class TestDecisionEnum:
    # Source: Impl Plan Day 1 acceptance test 3 -- "`decision` rejects
    # anything outside the six-member enum"
    def test_decision_has_exactly_six_members(self):
        assert set(Decision) == {
            Decision.ALLOW, Decision.MONITOR, Decision.THROTTLE,
            Decision.CHALLENGE, Decision.STEP_UP, Decision.BLOCK,
        }

    def test_decision_rejects_out_of_enum_value(self):
        with pytest.raises(ValueError):
            Decision("not_a_real_tier")

    def test_score_response_rejects_out_of_enum_decision(self):
        with pytest.raises(ValidationError):
            ScoreResponse(attempt_uid="01AAA", decision="not_a_real_tier", latency_ms=1)


class TestUiRoutingTableMatchesClientOutcome:
    # Source: Impl Plan Day 1 acceptance test 4 --
    # "set(UI_ROUTING_TABLE) == set(ClientOutcome)"
    def test_ui_routing_table_covers_exactly_client_outcome(self):
        assert set(UI_ROUTING_TABLE.keys()) == set(ClientOutcome)

    def test_client_outcome_has_exactly_eight_members(self):
        assert len(set(ClientOutcome)) == 8


class TestResolveClientOutcome:
    # Source: v2.1 reconciliation, decision 18 (N2) -- all eight
    # ClientOutcome values are genuinely reachable through
    # resolve_client_outcome(), including the header path (shed) and the
    # timeout path (fail_open) that no response body field could ever carry.
    @pytest.mark.parametrize("decision", list(Decision))
    def test_body_decision_maps_through(self, decision):
        outcome = resolve_client_outcome(
            status_code=200, headers={}, body={"decision": decision.value}, error=None,
        )
        assert outcome == ClientOutcome(decision.value)

    def test_shed_header_maps_to_shed(self):
        outcome = resolve_client_outcome(
            status_code=200,
            headers={"X-Tollgate-Shed": "1"},
            body={"decision": "allow"},
            error=None,
        )
        assert outcome == ClientOutcome.SHED

    def test_timeout_error_maps_to_fail_open(self):
        outcome = resolve_client_outcome(
            status_code=None, headers={}, body=None, error=TimeoutError(),
        )
        assert outcome == ClientOutcome.FAIL_OPEN

    def test_5xx_maps_to_fail_open(self):
        outcome = resolve_client_outcome(status_code=503, headers={}, body=None, error=None)
        assert outcome == ClientOutcome.FAIL_OPEN

    def test_all_eight_client_outcomes_are_reachable(self):
        reachable = set()
        for decision in Decision:
            reachable.add(
                resolve_client_outcome(
                    status_code=200, headers={}, body={"decision": decision.value}, error=None,
                )
            )
        reachable.add(
            resolve_client_outcome(
                status_code=200, headers={"X-Tollgate-Shed": "1"},
                body={"decision": "allow"}, error=None,
            )
        )
        reachable.add(
            resolve_client_outcome(status_code=None, headers={}, body=None, error=TimeoutError())
        )
        assert reachable == set(ClientOutcome)
