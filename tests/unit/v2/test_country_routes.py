"""Route coverage for the native v2 countries list."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from sqlalchemy.exc import OperationalError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
    infer_route_group,
)
from policyengine_api.services.v2.countries.types import CountryRead

UNITED_KINGDOM = CountryRead(id="uk", household_enabled=True, society_wide_enabled=True)
UNITED_STATES = CountryRead(id="us", household_enabled=True, society_wide_enabled=True)
HOUSEHOLD_ONLY_COUNTRY = CountryRead(
    id="be", household_enabled=True, society_wide_enabled=False
)


class FakeCountryService:
    """Return fixed countries, or raise ``error``, and count the calls."""

    def __init__(
        self,
        countries: list[CountryRead],
        *,
        error: Exception | None = None,
    ) -> None:
        self.countries = countries
        self.error = error
        self.list_calls = 0

    def list_countries(self) -> list[CountryRead]:
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return self.countries


def _client(service: FakeCountryService) -> tuple[TestClient, dict[str, int]]:
    flask_calls = {"count": 0}
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST"])
    def fallback(resource: str):
        flask_calls["count"] += 1
        return jsonify({"source": "flask", "resource": resource})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_country_service_factory=lambda: service,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    client = TestClient(
        create_asgi_app(flask_app, dependencies=dependencies, route_settings=settings),
        raise_server_exceptions=False,
    )
    return client, flask_calls


def test_countries_list_every_country_with_its_capability() -> None:
    service = FakeCountryService(
        [HOUSEHOLD_ONLY_COUNTRY, UNITED_KINGDOM, UNITED_STATES]
    )
    client, flask_calls = _client(service)

    response = client.get("/v2/countries")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "items": [
                {
                    "id": "be",
                    "household_enabled": True,
                    "society_wide_enabled": False,
                },
                {
                    "id": "uk",
                    "household_enabled": True,
                    "society_wide_enabled": True,
                },
                {
                    "id": "us",
                    "household_enabled": True,
                    "society_wide_enabled": True,
                },
            ]
        },
    }
    assert service.list_calls == 1
    assert flask_calls["count"] == 0


def test_countries_list_needs_no_user_credential() -> None:
    client, _flask_calls = _client(FakeCountryService([UNITED_STATES]))

    response = client.get("/v2/countries", headers={"Authorization": ""})

    assert response.status_code == 200


def test_countries_list_rejects_query_parameters() -> None:
    service = FakeCountryService([UNITED_STATES])
    client, _flask_calls = _client(service)

    response = client.get("/v2/countries?country_id=us")

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert service.list_calls == 0


@pytest.mark.parametrize(
    "error",
    [
        V2ConfigurationError("V2_RUNTIME_DATABASE_URL is required"),
        OperationalError("SELECT", {}, Exception("connection refused")),
    ],
    ids=["configuration", "database"],
)
def test_countries_list_reports_an_unavailable_database_as_503(
    error: Exception,
) -> None:
    client, _flask_calls = _client(FakeCountryService([], error=error))

    response = client.get("/v2/countries")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 countries are unavailable",
    }


def test_countries_list_hides_unexpected_failures_behind_a_500() -> None:
    client, _flask_calls = _client(
        FakeCountryService([], error=RuntimeError("secret detail"))
    )

    response = client.get("/v2/countries")

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "V2 countries query failed",
    }


def test_countries_list_supports_get_only() -> None:
    service = FakeCountryService([UNITED_STATES])
    client, flask_calls = _client(service)

    response = client.post("/v2/countries", json={})

    assert response.status_code == 405
    assert service.list_calls == 0
    assert flask_calls["count"] == 0


def test_countries_list_is_documented_in_the_v2_openapi_document() -> None:
    client, _flask_calls = _client(FakeCountryService([]))

    document = client.get("/v2/openapi.json").json()
    operation = document["paths"]["/v2/countries"]["get"]

    assert operation.get("parameters", []) == []
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CountryListResponse"
    }
    assert {"422", "500", "503"} <= operation["responses"].keys()
    item_schema = document["components"]["schemas"]["CountryItem"]
    assert item_schema["required"] == [
        "id",
        "household_enabled",
        "society_wide_enabled",
    ]
    assert item_schema["additionalProperties"] is False


def test_countries_requests_are_logged_with_the_metadata_route_group() -> None:
    assert infer_route_group("/v2/countries") == "metadata"
