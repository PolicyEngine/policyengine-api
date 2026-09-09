"""Native FastAPI contract tests for immutable v2 households."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest
from sqlalchemy.exc import OperationalError, TimeoutError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.households.types import (
    HouseholdPage,
    HouseholdRead,
    NativeHouseholdCreation,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    HouseholdCreationIntegrityError,
    HouseholdNotFoundError,
    HouseholdValidationError,
)


HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000010")
CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _document() -> dict[str, object]:
    memberships = {
        "household": "household-1",
        "family": "family-1",
        "tax_unit": "tax-unit-1",
        "spm_unit": "spm-unit-1",
        "marital_unit": "marital-unit-1",
    }
    document: dict[str, object] = {
        "people": [
            {
                "id": "person-1",
                "source_name": "you",
                "values": {"age": {"2026": 40}},
                "memberships": memberships,
            }
        ]
    }
    for collection, identifier in memberships.items():
        document[collection] = [
            {"id": identifier, "source_name": "primary", "values": {}}
        ]
    return document


def _household_read(
    *,
    household_id: UUID = HOUSEHOLD_ID,
    country_id: str = "us",
) -> HouseholdRead:
    return HouseholdRead(
        id=household_id,
        country_id=country_id,
        default_year=2026,
        household_data=_document(),
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


class FakeHouseholdService:
    def __init__(self) -> None:
        self.created = True
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_household(self, household_input) -> NativeHouseholdCreation:
        self.calls.append(("create_household", household_input))
        self._raise()
        return NativeHouseholdCreation(item=_household_read(), created=self.created)

    def get_household(self, **filters) -> HouseholdRead:
        self.calls.append(("get_household", filters))
        self._raise()
        return _household_read(household_id=filters["household_id"])

    def list_households(self, **filters) -> HouseholdPage:
        self.calls.append(("list_households", filters))
        self._raise()
        return HouseholdPage(
            items=(_household_read(),),
            offset=filters["offset"],
            limit=filters["limit"],
            has_more=False,
        )


def _client(
    service: FakeHouseholdService,
) -> tuple[TestClient, dict[str, int]]:
    flask_calls = {"count": 0}
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST", "PATCH", "DELETE"])
    def fallback(resource: str):
        flask_calls["count"] += 1
        return jsonify({"source": "flask", "resource": resource})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        v2_household_service_factory=lambda: service,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return (
        TestClient(
            create_asgi_app(
                flask_app,
                dependencies=dependencies,
                route_settings=settings,
            ),
            raise_server_exceptions=False,
        ),
        flask_calls,
    )


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "default_year": 2026,
        "household_data": _document(),
    }
    body.update(changes)
    return body


def test_create_returns_201_for_new_and_200_for_deduplicated_content() -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    created = client.post("/v2/households?country_id=US", json=_body())
    service.created = False
    deduplicated = client.post("/v2/households?country_id=us", json=_body())

    assert created.status_code == 201
    assert deduplicated.status_code == 200
    assert created.json() == deduplicated.json()
    assert created.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(HOUSEHOLD_ID),
                "country_id": "us",
                "default_year": 2026,
                "household_data": _document(),
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    command = service.calls[0][1]
    assert command.country_id == "us"
    assert command.default_year == 2026
    assert flask_calls["count"] == 0


def test_create_rejects_country_mismatch_and_non_content_fields() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    mismatch = client.post("/v2/households?country_id=uk", json=_body())
    named = client.post(
        "/v2/households?country_id=us",
        json={**_body(), "name": "Not base content", "description": "No"},
    )
    modeled = client.post(
        "/v2/households?country_id=us",
        json={**_body(), "tax_benefit_model_version_id": str(uuid4())},
    )

    assert mismatch.status_code == 400
    assert named.status_code == 422
    assert modeled.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize("default_year", [None, 1899, 2201])
def test_create_requires_a_bounded_non_null_default_year(default_year) -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    response = client.post(
        "/v2/households?country_id=us",
        json=_body(default_year=default_year),
    )

    assert response.status_code == 422
    assert service.calls == []


def test_create_rejects_unknown_duplicate_oversized_and_excessive_entities() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    unknown = client.post("/v2/households?country_id=us&search=age", json=_body())
    duplicate = client.post("/v2/households?country_id=us&country_id=uk", json=_body())
    excessive_document = _document()
    excessive_document["people"] = [
        {
            "id": f"person-{index}",
            "values": {},
            "memberships": {},
        }
        for index in range(1_001)
    ]
    excessive = client.post(
        "/v2/households?country_id=us",
        json=_body(household_data=excessive_document),
    )
    oversized = client.post(
        "/v2/households?country_id=us",
        content=b'{"country_id":"us","padding":"' + b"x" * 1_048_576 + b'"}',
        headers={"content-type": "application/json"},
    )

    assert unknown.status_code == 422
    assert duplicate.status_code == 422
    assert excessive.status_code == 422
    assert oversized.status_code == 413
    assert oversized.json()["status"] == "error"
    assert service.calls == []


def test_detail_is_country_scoped_and_returns_complete_content() -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=US")
    service.error = HouseholdNotFoundError("household was not found")
    missing = client.get(f"/v2/households/{uuid4()}?country_id=uk")

    assert response.status_code == 200
    assert response.json()["result"]["item"]["household_data"] == _document()
    assert service.calls[0] == (
        "get_household",
        {"country_id": "us", "household_id": HOUSEHOLD_ID},
    )
    assert missing.status_code == 404
    assert missing.json() == {"status": "error", "message": "household was not found"}
    assert flask_calls["count"] == 0


def test_list_passes_exact_year_filter_and_canonical_pagination() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    response = client.get(
        "/v2/households?country_id=us&default_year=2026&offset=2&limit=3"
    )
    search = client.get("/v2/households?country_id=us&search=age")
    excessive = client.get("/v2/households?country_id=us&limit=501")

    assert response.status_code == 200
    assert response.json()["result"]["offset"] == 2
    assert response.json()["result"]["limit"] == 3
    assert service.calls == [
        (
            "list_households",
            {
                "country_id": "us",
                "default_year": 2026,
                "offset": 2,
                "limit": 3,
            },
        )
    ]
    assert search.status_code == 422
    assert excessive.status_code == 422


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (HouseholdValidationError("invalid relationship"), 400, "relationship"),
        (HouseholdNotFoundError("absent household"), 404, "absent"),
        (
            HouseholdContentHashCollisionError("database statement secret"),
            409,
            "conflicts",
        ),
        (
            HouseholdCreationIntegrityError("database statement secret"),
            500,
            "integrity",
        ),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            503,
            "unavailable",
        ),
        (TimeoutError("pool timeout"), 503, "unavailable"),
        (RuntimeError("credential and household value"), 500, "operation failed"),
    ],
)
def test_household_failures_map_to_secret_safe_typed_errors(
    error: Exception,
    status: int,
    message: str,
) -> None:
    service = FakeHouseholdService()
    service.error = error
    client, _flask_calls = _client(service)

    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us")

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()
    assert "secret" not in response.text
    assert "credential" not in response.text


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_base_household_mutations_are_not_exposed(method: str) -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    response = client.request(
        method.upper(),
        f"/v2/households/{HOUSEHOLD_ID}?country_id=us",
        json={},
    )

    assert response.status_code == 405
    assert response.json()["status"] == "error"
    assert service.calls == []
    assert flask_calls["count"] == 0


def test_openapi_publishes_query_body_item_page_and_error_schemas() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)
    schema = client.get("/v2/openapi.json").json()

    assert set(
        path for path in schema["paths"] if path.startswith("/v2/households")
    ) == {
        "/v2/households",
        "/v2/households/{household_id}",
    }
    collection = schema["paths"]["/v2/households"]["get"]
    parameters = {item["name"]: item for item in collection["parameters"]}
    assert parameters["country_id"]["required"] is True
    assert parameters["default_year"]["schema"]["anyOf"][0]["minimum"] == 1900
    assert parameters["offset"]["schema"]["default"] == 0
    assert parameters["limit"]["schema"]["maximum"] == 500

    create = schema["paths"]["/v2/households"]["post"]
    assert {"200", "201", "400", "404", "409", "413", "422", "500", "503"} <= set(
        create["responses"]
    )
    request_ref = create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["default_year"]["minimum"] == 1900
    document_refs = request_schema["properties"]["household_data"]["anyOf"]
    us_document = next(
        schema["components"]["schemas"][item["$ref"].rsplit("/", 1)[-1]]
        for item in document_refs
        if item["$ref"].rsplit("/", 1)[-1].startswith("USHouseholdDocument")
    )
    assert "spm" in us_document["properties"]
    assert "spm" not in us_document["required"]
    assert us_document["properties"]["people"]["maxItems"] == 1000
    entity_record = schema["components"]["schemas"]["HouseholdEntityRecord"]
    assert entity_record["properties"]["values"]["maxProperties"] == 500
    item_schema = schema["components"]["schemas"]["HouseholdItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "default_year",
        "household_data",
        "created_at",
        "updated_at",
    }
    assert {
        "content_hash",
        "canonicalization_version",
        "name",
        "description",
    }.isdisjoint(item_schema["properties"])


def test_browser_preflight_and_cross_origin_errors_use_application_cors() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)
    origin = "https://app.example"

    preflight = client.options(
        "/v2/households",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    error = client.get(
        "/v2/households?country_id=us&search=age",
        headers={"Origin": origin},
    )

    assert preflight.status_code == 200
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert service.calls == []
    assert error.status_code == 422
    assert error.headers["access-control-allow-origin"] == origin
    assert (
        "x-policyengine-request-id"
        in error.headers["access-control-expose-headers"].lower()
    )


def test_native_household_routes_do_not_use_cloud_sql_or_flask(monkeypatch) -> None:
    def reject_cloud_sql():
        raise AssertionError("Cloud SQL must not be selected")

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    assert client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us").status_code == 200
    assert service.calls[0][0] == "get_household"
    assert flask_calls["count"] == 0


@pytest.mark.parametrize(
    "selection",
    [
        None,
        {"geography_kind": "national"},
        {
            "forecast_content_sha256": "a" * 64,
            "scenario": "baseline",
            "geography_kind": "national",
            "geography_id": None,
            "county_vintage": "2020",
            "as_of": None,
        },
    ],
)
def test_native_household_http_preserves_spm_and_historical_omission(
    monkeypatch, selection
) -> None:
    from copy import deepcopy

    service = FakeHouseholdService()
    saved = _household_read()
    if selection is not None:
        saved.household_data["spm"] = deepcopy(selection)
    monkeypatch.setattr(service, "get_household", lambda **_filters: saved)
    client, _ = _client(service)
    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us")
    assert response.status_code == 200
    returned = response.json()["result"]["item"]["household_data"]
    if selection is None:
        assert "spm" not in returned
    else:
        assert returned["spm"] == selection

    created = client.post(
        "/v2/households?country_id=us",
        json={
            "country_id": "us",
            "default_year": 2026,
            "household_data": returned,
        },
    )
    assert created.status_code == 201
    supplied = service.calls[-1][1].household_data
    if selection is None:
        assert "spm" not in supplied
    else:
        assert supplied["spm"] == selection


@pytest.mark.parametrize(
    "selection", [None, [], {"unexpected": True}, {"geography_kind": "metro"}]
)
def test_native_household_invalid_spm_is_rejected_before_service(selection) -> None:
    service = FakeHouseholdService()
    client, _ = _client(service)
    document = _document()
    document["spm"] = selection
    response = client.post(
        "/v2/households?country_id=us",
        json={
            "country_id": "us",
            "default_year": 2026,
            "household_data": document,
        },
    )
    assert response.status_code == 422
    assert service.calls == []
