"""Exercise live test requests locally against the API contract and pinned model."""

import json

import httpx
import pytest

from policyengine_api.query_parameters import AnnualEconomyQuery, parse_query_items
from tests.integration import conftest as live_polling
from tests.integration import test_live_calculate as live_calculate
from tests.integration import test_live_economy as live_economy


@pytest.mark.parametrize(
    ("live_test", "country_id", "region"),
    [
        (live_economy.test_live_utah_macro_reform, "us", "ut"),
        (live_economy.test_live_california_eitc_macro_reform, "us", "state/ca"),
    ],
)
def test_live_macro_requests_follow_the_query_contract(live_test, country_id, region):
    """Run actual live request construction through the server's strict parser."""
    policies = []
    economy_queries = []
    test_year = str(live_economy.CURRENT_YEAR)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == f"/{country_id}/metadata":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "current_law_id": 2,
                        "economy_options": {"time_period": [{"name": test_year}]},
                    }
                },
            )
        if request.method == "POST" and request.url.path == f"/{country_id}/policy":
            policies.append(json.loads(request.content))
            return httpx.Response(201, json={"result": {"policy_id": 123}})

        assert request.method == "GET"
        assert request.url.path == f"/{country_id}/economy/123/over/2"
        economy_queries.append(
            parse_query_items(AnnualEconomyQuery, request.url.params.multi_items())
        )
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {
                    "budget": {"budgetary_impact": -1.0},
                    "intra_decile": {"all": {"Lose less than 5%": 0.1}},
                },
            },
        )

    with httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(respond)
    ) as client:
        live_test(client, "local-probe-12345678", live_polling._poll_live_endpoint)

    assert len(economy_queries) == 1
    assert economy_queries[0].region == region
    assert economy_queries[0].time_period == test_year
    assert len(policies) == 1
    assert "local-probe-12345678" in policies[0]["label"]


def test_live_credit_assertions_match_the_pinned_us_model():
    """Validate the live assertions using the exact fixture and installed model."""
    from policyengine_us import Simulation

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/us/calculate"
        household = json.loads(request.content)["household"]
        simulation = Simulation(situation=household)
        tax_unit = household["tax_units"]["tax unit"]
        for variable in ("eitc", "ctc", "ca_eitc"):
            tax_unit[variable]["2025"] = float(simulation.calculate(variable, 2025)[0])
        return httpx.Response(200, json={"status": "ok", "result": household})

    with httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(respond)
    ) as client:
        live_calculate.test_live_calculate_us_federal_and_california_credits(
            client, "local-probe-12345678"
        )
