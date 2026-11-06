"""Refused economy requests write no ERROR record; other failures still do.

The daily telemetry error report groups the API's log records at severity
ERROR or above (``severity_number >= 500`` in
``.github/scripts/telemetry_error_issues/bigquery.py``). The economy routes
answer a request that names a policy its country does not have with 404, and a
request that fails validation, such as a year outside the country's years or
an unknown region, with 400. Those requests are refused, not failures of the
API, so the service logs them at WARNING and they add no record to any error
group. Every other failure is still logged at ERROR, including a ValueError
raised after the request was validated, which the route also answers with 400.

The tests serve the routes from a real service over in-memory caches, through
a real observability runtime that keeps every record it writes. So they check
every record a deployed request writes, including the request's completion
record and anything logged through the standard library.
"""

import importlib
from dataclasses import replace
from http import HTTPStatus
from unittest.mock import Mock

import pytest
from flask import Flask
from flask.testing import FlaskClient
from policyengine_observability import (
    CustomLogDestination,
    OTelConfig,
    configure,
    instrument_flask,
)

from policyengine_api.observability import runtime
from policyengine_api.routes import economy_routes, error_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService

# policyengine_api.observability re-exports the runtime object under the name of
# its submodule, so the submodule whose global get_runtime reads is imported by
# its full name.
runtime_module = importlib.import_module("policyengine_api.observability.runtime")

# Cloud Logging's severities from ERROR up: the records the error report reads.
ERROR_OR_ABOVE = frozenset({"ERROR", "CRITICAL", "ALERT", "EMERGENCY"})

UK_CURRENT_LAW_POLICY_ID = 1
UK_REFORM_POLICY_ID = 7
# A US policy ID, which the UK policy table does not have.
US_REFORM_POLICY_ID = 98557
STORED_UK_POLICY_JSON = {
    UK_CURRENT_LAW_POLICY_ID: {},
    UK_REFORM_POLICY_ID: {
        "gov.hmrc.income_tax.rates.uk[0].rate": {"2026-01-01.2100-12-31": 0.21}
    },
}

ANNUAL_ROUTE = "annual"
BUDGET_WINDOW_ROUTE = "budget-window"
FAILURE_MESSAGES = {
    ANNUAL_ROUTE: "Error getting economic impact",
    BUDGET_WINDOW_ROUTE: "Error getting budget-window economic impact",
}
REFUSAL_MESSAGES = {
    ANNUAL_ROUTE: "Refused economic impact request",
    BUDGET_WINDOW_ROUTE: "Refused budget-window economic impact request",
}
# Years the UK model and data do not cover (UK years are 2024 to 2032).
UNAVAILABLE_YEARS = {ANNUAL_ROUTE: "2033", BUDGET_WINDOW_ROUTE: "2023"}


class _CollectedRecords:
    """Keeps every structured record a runtime delivers, in delivery order."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.records.append(record)

    def at_error_or_above(self) -> list[dict[str, object]]:
        return [
            record for record in self.records if record["severity"] in ERROR_OR_ABOVE
        ]

    def with_message(self, message: str) -> list[dict[str, object]]:
        return [record for record in self.records if record.get("message") == message]


@pytest.fixture
def collected_records() -> _CollectedRecords:
    return _CollectedRecords()


@pytest.fixture
def collecting_runtime(monkeypatch, collected_records):
    """Replace the API's runtime with one that keeps its records.

    It keeps the API's logging settings, including the capture of
    standard-library logging, and only replaces where records go.
    """
    observability_runtime = configure(
        replace(
            runtime.config,
            logging=replace(
                runtime.config.logging,
                destinations=(
                    CustomLogDestination(
                        name="collected-records",
                        writer_factory=lambda: collected_records,
                        delivery="inline",
                    ),
                ),
            ),
            otel=OTelConfig(enabled=False),
        )
    )
    monkeypatch.setattr(runtime_module, "runtime", observability_runtime)
    yield observability_runtime
    observability_runtime.shutdown()


@pytest.fixture
def policy_lookup() -> Mock:
    """Answer policy lookups like the UK policy table."""
    policies = Mock()
    policies.get_policy_json.side_effect = lambda country_id, policy_id: (
        STORED_UK_POLICY_JSON.get(policy_id) if country_id == "uk" else None
    )
    return policies


@pytest.fixture
def client(monkeypatch, collecting_runtime, policy_lookup) -> FlaskClient:
    """Serve the economy routes from a real service over in-memory caches.

    The simulation gateway is a mock, and the app-wide error handlers turn an
    unhandled exception into the 500 a deployed request gets.
    """
    namespace = CacheNamespace("test", "economy-refusal-log-severity")
    cache_backend = InMemoryCacheBackend()
    gateway = Mock()
    gateway.resolve_app_name.side_effect = (
        lambda _country_id, version=None, policyengine_version=None: (
            "policyengine-simulation-test",
            version,
        )
    )
    service = EconomyService(
        policy_service_=policy_lookup,
        reform_impacts_service_=ReformImpactsService(
            ReformImpactCache(cache_backend, namespace)
        ),
        budget_window_cache_=BudgetWindowCache(cache_backend, namespace),
        simulation_entrypoint_=gateway,
    )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    # Same order as the API app: instrument Flask, then register handlers.
    instrument_flask(app, collecting_runtime)
    app.register_blueprint(economy_routes.economy_bp)
    app.register_blueprint(error_routes.error_bp)
    return app.test_client()


def request_economy_impact(
    client: FlaskClient,
    route: str,
    *,
    reform_policy_id: int = UK_REFORM_POLICY_ID,
    region: str = "uk",
    year: str = "2026",
):
    """Request a UK economy impact on ``route`` for the reform and current law."""
    path = f"/uk/economy/{reform_policy_id}/over/{UK_CURRENT_LAW_POLICY_ID}"
    if route == ANNUAL_ROUTE:
        return client.get(path, query_string={"region": region, "time_period": year})
    return client.get(
        f"{path}/budget-window",
        query_string={"region": region, "start_year": year, "window_size": "2"},
    )


def assert_refusal_logged_once_at_warning(
    records: _CollectedRecords, route: str, error_type: str
) -> dict[str, object]:
    """Check the request logged its refusal once, at WARNING, and return it."""
    refusals = records.with_message(REFUSAL_MESSAGES[route])
    assert len(refusals) == 1, records.records
    refusal = refusals[0]
    assert refusal["severity"] == "WARNING"
    assert refusal["attributes"]["error_type"] == error_type
    return refusal


@pytest.mark.parametrize("route", [ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def test_a_year_outside_the_countrys_years_writes_no_error_record(
    client, collected_records, route
):
    response = request_economy_impact(client, route, year=UNAVAILABLE_YEARS[route])

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json["errors"][0]["code"] == "DATASET_YEAR_UNAVAILABLE"
    assert collected_records.at_error_or_above() == []
    refusal = assert_refusal_logged_once_at_warning(
        collected_records, route, "SPMValidationError"
    )
    assert refusal["attributes"]["error_code"] == "DATASET_YEAR_UNAVAILABLE"


@pytest.mark.parametrize("route", [ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def test_an_unknown_region_writes_no_error_record(client, collected_records, route):
    response = request_economy_impact(client, route, region="atlantis")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json["message"].startswith("Unknown UK region 'atlantis'")
    assert collected_records.at_error_or_above() == []
    refusal = assert_refusal_logged_once_at_warning(
        collected_records, route, "ValueError"
    )
    assert "error_code" not in refusal["attributes"]


@pytest.mark.parametrize("route", [ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def test_a_policy_the_country_does_not_have_writes_no_error_record(
    client, collected_records, route
):
    response = request_economy_impact(
        client, route, reform_policy_id=US_REFORM_POLICY_ID
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json["message"] == f"Policy #{US_REFORM_POLICY_ID} not found."
    assert collected_records.at_error_or_above() == []
    assert_refusal_logged_once_at_warning(
        collected_records, route, "PolicyNotFoundError"
    )


@pytest.mark.parametrize("route", [ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def test_an_unexpected_failure_is_still_logged_at_error(
    client, collected_records, policy_lookup, route
):
    policy_lookup.get_policy_json.side_effect = RuntimeError("policy table failed")

    response = request_economy_impact(client, route)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    failures = collected_records.with_message(FAILURE_MESSAGES[route])
    assert len(failures) == 1
    assert failures[0]["severity"] == "ERROR"
    assert failures[0]["attributes"]["error_type"] == "RuntimeError"
    assert collected_records.with_message(REFUSAL_MESSAGES[route]) == []


@pytest.mark.parametrize("route", [ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def test_a_value_error_after_validation_is_still_logged_at_error(
    client, collected_records, policy_lookup, route
):
    """A ValueError from a validated request is unexpected, not a refusal.

    The route answers it with 400, as it answers every ValueError, but the
    request passed validation, so the failure is the API's and stays at ERROR.
    """
    policy_lookup.get_policy_json.side_effect = ValueError("policy JSON unreadable")

    response = request_economy_impact(client, route)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    failures = collected_records.with_message(FAILURE_MESSAGES[route])
    assert len(failures) == 1
    assert failures[0]["severity"] == "ERROR"
    assert failures[0]["attributes"]["error_type"] == "ValueError"
    assert collected_records.with_message(REFUSAL_MESSAGES[route]) == []
