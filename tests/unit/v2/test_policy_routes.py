"""Native FastAPI contract tests for immutable v2 policies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest
from sqlalchemy.exc import OperationalError, TimeoutError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.services.v2.policies.types import (
    NativePolicyCreation,
    PolicyPage,
    PolicyParameterValueRead,
    PolicyRead,
)
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
    PolicyNotFoundError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)


POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")
MODEL_ID = UUID("00000000-0000-0000-0000-000000000020")
MODEL_VERSION_ID = UUID("00000000-0000-0000-0000-000000000030")
PARAMETER_ID = UUID("00000000-0000-0000-0000-000000000040")
VALUE_ID = UUID("00000000-0000-0000-0000-000000000050")
CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _policy_read(*, policy_id: UUID = POLICY_ID, country_id: str = "us") -> PolicyRead:
    return PolicyRead(
        id=policy_id,
        country_id=country_id,
        tax_benefit_model_id=MODEL_ID,
        tax_benefit_model_version_id=MODEL_VERSION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
        parameter_values=(
            PolicyParameterValueRead(
                id=VALUE_ID,
                parameter_id=PARAMETER_ID,
                parameter_name="gov.example.rate",
                value={"rate": 0.2},
                start_date=CREATED_AT,
                end_date=None,
            ),
        ),
    )


class FakePolicyService:
    def __init__(self) -> None:
        self.created = True
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_policy(self, command) -> NativePolicyCreation:
        self.calls.append(("create_policy", command))
        self._raise()
        return NativePolicyCreation(item=_policy_read(), created=self.created)

    def get_policy(self, **filters) -> PolicyRead:
        self.calls.append(("get_policy", filters))
        self._raise()
        return _policy_read(policy_id=filters["policy_id"])

    def list_policies(self, **filters) -> PolicyPage:
        self.calls.append(("list_policies", filters))
        self._raise()
        return PolicyPage(
            items=(_policy_read(),),
            offset=filters["offset"],
            limit=filters["limit"],
            has_more=False,
        )


def _client(
    service: FakePolicyService,
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
        v2_policy_service_factory=lambda: service,
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


def _body(**changes) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "tax_benefit_model_id": str(MODEL_ID),
        "parameter_values": [
            {
                "parameter_id": str(PARAMETER_ID),
                "value": {"rate": 0.2},
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    }
    body.update(changes)
    return body


def test_create_returns_201_for_new_and_200_for_deduplicated_content() -> None:
    service = FakePolicyService()
    client, flask_calls = _client(service)

    created = client.post(
        "/v2/policies?country_id=US&policyengine_version=5.2.0",
        json=_body(),
    )
    service.created = False
    deduplicated = client.post("/v2/policies?country_id=us", json=_body())

    assert created.status_code == 201
    assert deduplicated.status_code == 200
    assert created.json() == deduplicated.json()
    assert created.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(POLICY_ID),
                "country_id": "us",
                "tax_benefit_model_id": str(MODEL_ID),
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "parameter_values": [
                    {
                        "id": str(VALUE_ID),
                        "parameter_id": str(PARAMETER_ID),
                        "parameter_name": "gov.example.rate",
                        "value": {"rate": 0.2},
                        "start_date": "2026-01-01T00:00:00Z",
                        "end_date": None,
                    }
                ],
            }
        },
    }
    first_command = service.calls[0][1]
    assert first_command.country_id == "us"
    assert first_command.policyengine_version == "5.2.0"
    assert flask_calls["count"] == 0


def test_create_rejects_country_mismatch_and_core_presentation_fields() -> None:
    service = FakePolicyService()
    client, _flask_calls = _client(service)

    mismatch = client.post("/v2/policies?country_id=uk", json=_body())
    named = client.post(
        "/v2/policies?country_id=us",
        json={**_body(), "name": "Not core content", "description": "No"},
    )

    assert mismatch.status_code == 400
    assert named.status_code == 422
    assert named.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert service.calls == []


def test_create_rejects_unknown_duplicate_and_oversized_input_before_service() -> None:
    service = FakePolicyService()
    client, _flask_calls = _client(service)

    unknown = client.post(
        "/v2/policies?country_id=us&search=rate",
        json=_body(),
    )
    duplicate = client.post(
        "/v2/policies?country_id=us&country_id=uk",
        json=_body(),
    )
    excessive_values = client.post(
        "/v2/policies?country_id=us",
        json=_body(
            parameter_values=[
                {
                    "parameter_id": str(uuid4()),
                    "value": index,
                    "start_date": "2026-01-01T00:00:00Z",
                }
                for index in range(1_001)
            ]
        ),
    )
    oversized = client.post(
        "/v2/policies?country_id=us",
        content=b'{"country_id":"us","padding":"' + b"x" * 1_048_576 + b'"}',
        headers={"content-type": "application/json"},
    )

    assert unknown.status_code == 422
    assert unknown.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert duplicate.status_code == 422
    assert excessive_values.status_code == 422
    assert oversized.status_code == 413
    assert oversized.json()["status"] == "error"
    assert service.calls == []


def test_detail_is_country_scoped_and_returns_typed_not_found() -> None:
    service = FakePolicyService()
    client, flask_calls = _client(service)

    response = client.get(f"/v2/policies/{POLICY_ID}?country_id=US")
    service.error = PolicyNotFoundError("policy was not found")
    missing = client.get(f"/v2/policies/{uuid4()}?country_id=uk")

    assert response.status_code == 200
    assert (
        response.json()["result"]["item"]["parameter_values"][0]["parameter_name"]
        == "gov.example.rate"
    )
    assert service.calls[0] == (
        "get_policy",
        {"country_id": "us", "policy_id": POLICY_ID},
    )
    assert missing.status_code == 404
    assert missing.json() == {"status": "error", "message": "policy was not found"}
    assert flask_calls["count"] == 0


def test_list_passes_exact_model_filter_and_canonical_pagination() -> None:
    service = FakePolicyService()
    client, _flask_calls = _client(service)

    response = client.get(
        f"/v2/policies?country_id=us&tax_benefit_model_id={MODEL_ID}&offset=2&limit=3"
    )
    search = client.get("/v2/policies?country_id=us&search=rate")
    excessive = client.get("/v2/policies?country_id=us&limit=501")

    assert response.status_code == 200
    assert response.json()["result"]["offset"] == 2
    assert response.json()["result"]["limit"] == 3
    assert service.calls == [
        (
            "list_policies",
            {
                "country_id": "us",
                "tax_benefit_model_id": MODEL_ID,
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
        (PolicyCatalogValidationError("bad model"), 400, "bad model"),
        (MetadataCatalogVersionNotFoundError("absent catalog"), 404, "absent"),
        (
            PolicyContentHashCollisionError("database statement secret"),
            409,
            "conflicts",
        ),
        (
            PolicyCreationIntegrityError("database statement secret"),
            500,
            "integrity",
        ),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
        (
            MetadataCatalogUnavailableError("database statement secret"),
            503,
            "unavailable",
        ),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            503,
            "unavailable",
        ),
        (TimeoutError("pool timeout"), 503, "unavailable"),
        (RuntimeError("credential and policy value"), 500, "operation failed"),
    ],
)
def test_policy_failures_map_to_secret_safe_typed_errors(
    error: Exception,
    status: int,
    message: str,
) -> None:
    service = FakePolicyService()
    service.error = error
    client, _flask_calls = _client(service)

    response = client.get(f"/v2/policies/{POLICY_ID}?country_id=us")

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()
    assert "secret" not in response.text
    assert "credential" not in response.text


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_core_policy_mutations_are_not_exposed(method: str) -> None:
    service = FakePolicyService()
    client, flask_calls = _client(service)

    response = client.request(
        method.upper(),
        f"/v2/policies/{POLICY_ID}?country_id=us",
        json={},
    )

    assert response.status_code == 405
    assert response.json()["status"] == "error"
    assert service.calls == []
    assert flask_calls["count"] == 0


def test_openapi_publishes_request_query_response_and_error_contracts() -> None:
    service = FakePolicyService()
    client, _flask_calls = _client(service)
    schema = client.get("/v2/openapi.json").json()

    assert set(path for path in schema["paths"] if path.startswith("/v2/policies")) == {
        "/v2/policies",
        "/v2/policies/{policy_id}",
    }
    collection = schema["paths"]["/v2/policies"]["get"]
    parameters = {item["name"]: item for item in collection["parameters"]}
    assert parameters["country_id"]["required"] is True
    assert parameters["offset"]["schema"]["default"] == 0
    assert parameters["limit"]["schema"]["default"] == 100
    assert parameters["limit"]["schema"]["maximum"] == 500
    assert parameters["tax_benefit_model_id"]["schema"]["anyOf"][0]["format"] == (
        "uuid"
    )

    create = schema["paths"]["/v2/policies"]["post"]
    create_parameters = {item["name"]: item for item in create["parameters"]}
    assert create_parameters["country_id"]["required"] is True
    assert create_parameters["policyengine_version"]["required"] is False
    assert {"200", "201", "400", "404", "409", "413", "422", "500", "503"} <= (
        set(create["responses"])
    )
    request_ref = create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert request_schema["additionalProperties"] is False
    parameter_values = request_schema["properties"]["parameter_values"]
    assert parameter_values["maxItems"] == 1000
    item_schema = schema["components"]["schemas"]["PolicyItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "tax_benefit_model_id",
        "created_at",
        "updated_at",
        "parameter_values",
    }
    assert "name" not in item_schema["properties"]
    assert "description" not in item_schema["properties"]


def test_native_policy_routes_do_not_use_cloud_sql_or_flask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_cloud_sql():
        raise AssertionError("Cloud SQL must not be selected")

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    service = FakePolicyService()
    client, flask_calls = _client(service)

    assert client.get(f"/v2/policies/{POLICY_ID}?country_id=us").status_code == 200
    assert service.calls[0][0] == "get_policy"
    assert flask_calls["count"] == 0
