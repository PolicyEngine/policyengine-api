"""Native FastAPI contract tests for v2 dynamics, stored as policies are."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.dynamics.types import (
    CheckedDynamicRead,
    NativeDynamicCreation,
    NativeDynamicCreationInput,
)
from policyengine_api.services.v2.dynamics.validators import (
    DynamicContentHashCollisionError,
    DynamicCreationIntegrityError,
    DynamicNotFoundError,
    DynamicSetsPolicyParametersError,
    DynamicStorageError,
)
from policyengine_api.services.v2.policies.types import PolicyParameterValueRead
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
)

DYNAMIC_ID = UUID("00000000-0000-0000-0000-000000000011")
MODEL_ID = UUID("00000000-0000-0000-0000-000000000020")
MODEL_VERSION_ID = UUID("00000000-0000-0000-0000-000000000030")
PARAMETER_ID = UUID("00000000-0000-0000-0000-000000000040")
VALUE_ID = UUID("00000000-0000-0000-0000-000000000050")
CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"


def _dynamic_read(
    *, dynamic_id: UUID = DYNAMIC_ID, missing_parameters: tuple[str, ...] | None = ()
) -> CheckedDynamicRead:
    return CheckedDynamicRead(
        id=dynamic_id,
        country_id="us",
        tax_benefit_model_id=MODEL_ID,
        tax_benefit_model_version_id=MODEL_VERSION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
        parameter_values=(
            PolicyParameterValueRead(
                id=VALUE_ID,
                parameter_id=PARAMETER_ID,
                parameter_name=INCOME_ELASTICITY,
                value=0.25,
                start_date=CREATED_AT,
                end_date=None,
            ),
        ),
        missing_parameters=missing_parameters,
    )


class FakeDynamicService:
    """Records each call; raises ``error`` when set."""

    def __init__(self) -> None:
        self.created = True
        self.error: Exception | None = None
        self.missing_parameters: tuple[str, ...] | None = ()
        self.calls: list[tuple[str, object]] = []

    def create_dynamic(
        self, dynamic_input: NativeDynamicCreationInput
    ) -> NativeDynamicCreation:
        self.calls.append(("create_dynamic", dynamic_input))
        if self.error is not None:
            raise self.error
        return NativeDynamicCreation(item=_dynamic_read(), created=self.created)

    def get_dynamic(self, **filters: object) -> CheckedDynamicRead:
        self.calls.append(("get_dynamic", filters))
        if self.error is not None:
            raise self.error
        dynamic_id = filters["dynamic_id"]
        assert isinstance(dynamic_id, UUID)
        return _dynamic_read(
            dynamic_id=dynamic_id, missing_parameters=self.missing_parameters
        )


def _client(service: FakeDynamicService) -> tuple[TestClient, dict[str, int]]:
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
        v2_dynamic_service_factory=lambda: service,
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


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "tax_benefit_model_id": str(MODEL_ID),
        "parameter_values": [
            {
                "parameter_id": str(PARAMETER_ID),
                "value": 0.25,
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    }
    body.update(changes)
    return body


def test_create_answers_201_for_a_new_dynamic_and_200_for_stored_content() -> None:
    service = FakeDynamicService()
    client, flask_calls = _client(service)

    created = client.post(
        "/v2/dynamics?country_id=us&policyengine_version=5.2.0", json=_body()
    )
    service.created = False
    found = client.post("/v2/dynamics?country_id=us", json=_body())

    assert created.status_code == 201
    assert found.status_code == 200
    assert created.json() == found.json()
    item = created.json()["result"]["item"]
    assert created.json()["status"] == "ok"
    assert item == {
        "id": str(DYNAMIC_ID),
        "country_id": "us",
        "tax_benefit_model_id": str(MODEL_ID),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "parameter_values": [
            {
                "id": str(VALUE_ID),
                "parameter_id": str(PARAMETER_ID),
                "parameter_name": INCOME_ELASTICITY,
                "value": 0.25,
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": None,
            }
        ],
        "missing_parameters": [],
    }
    first_call = service.calls[0]
    assert first_call[0] == "create_dynamic"
    assert isinstance(first_call[1], NativeDynamicCreationInput)
    assert first_call[1].policyengine_version == "5.2.0"
    assert flask_calls["count"] == 0


def test_create_refuses_an_empty_dynamic_and_a_country_mismatch_before_service() -> (
    None
):
    service = FakeDynamicService()
    client, _flask_calls = _client(service)

    empty = client.post("/v2/dynamics?country_id=us", json=_body(parameter_values=[]))
    mismatch = client.post("/v2/dynamics?country_id=uk", json=_body())
    unknown_field = client.post("/v2/dynamics?country_id=us", json=_body(name="x"))
    oversized = client.post(
        "/v2/dynamics?country_id=us",
        content=b"{" + b" " * 1_048_577 + b"}",
        headers={"content-type": "application/json"},
    )

    assert empty.status_code == 422
    assert empty.json() == {"status": "error", "message": "Invalid API v2 request"}
    assert mismatch.status_code == 400
    assert unknown_field.status_code == 422
    assert oversized.status_code == 413
    assert service.calls == []


def test_create_refuses_policy_parameters_naming_them() -> None:
    service = FakeDynamicService()
    service.error = DynamicSetsPolicyParametersError(("gov.irs.rate", "gov.irs.x"))
    client, _flask_calls = _client(service)

    response = client.post("/v2/dynamics?country_id=us", json=_body())

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["code"] == "policy_parameters"
    assert body["policy_parameters"] == ["gov.irs.rate", "gov.irs.x"]
    assert "/v2/policies" in body["message"]


def test_detail_is_country_scoped_and_reports_missing_parameters() -> None:
    service = FakeDynamicService()
    service.missing_parameters = (INCOME_ELASTICITY,)
    client, _flask_calls = _client(service)
    dynamic_id = uuid4()

    found = client.get(f"/v2/dynamics/{dynamic_id}?country_id=uk")
    service.error = DynamicNotFoundError(f"dynamic {dynamic_id} was not found")
    missing = client.get(f"/v2/dynamics/{dynamic_id}?country_id=uk")

    assert found.status_code == 200
    assert found.json()["result"]["item"]["id"] == str(dynamic_id)
    assert found.json()["result"]["item"]["missing_parameters"] == [INCOME_ELASTICITY]
    assert service.calls[0] == (
        "get_dynamic",
        {"country_id": "uk", "dynamic_id": dynamic_id},
    )
    assert missing.status_code == 404
    assert missing.json() == {
        "status": "error",
        "message": f"dynamic {dynamic_id} was not found",
    }


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (PolicyCatalogValidationError("wrong model"), 400, "wrong model"),
        (MetadataCatalogVersionNotFoundError("no 9.9.9"), 404, "no 9.9.9"),
        (
            DynamicContentHashCollisionError("secret detail"),
            409,
            "Dynamic content hash conflicts with storage",
        ),
        (
            DynamicCreationIntegrityError("secret detail"),
            500,
            "Stored dynamic integrity failed",
        ),
        (
            DynamicStorageError("SELECT secret"),
            503,
            "V2 dynamic persistence is unavailable",
        ),
        (
            MetadataCatalogUnavailableError("catalog secret"),
            503,
            "V2 dynamic persistence is unavailable",
        ),
        (RuntimeError("secret detail"), 500, "V2 dynamic operation failed"),
    ],
)
def test_dynamic_failures_map_to_secret_safe_typed_errors(
    error: Exception, status_code: int, message: str
) -> None:
    service = FakeDynamicService()
    service.error = error
    client, _flask_calls = _client(service)

    response = client.post("/v2/dynamics?country_id=us", json=_body())

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v2/dynamics?country_id=us"),
        ("PATCH", f"/v2/dynamics/{DYNAMIC_ID}?country_id=us"),
        ("DELETE", f"/v2/dynamics/{DYNAMIC_ID}?country_id=us"),
    ],
)
def test_dynamics_are_neither_listed_nor_changed(method: str, path: str) -> None:
    service = FakeDynamicService()
    client, _flask_calls = _client(service)

    response = client.request(method, path)

    assert response.status_code in {404, 405}
    assert service.calls == []


def test_openapi_publishes_the_dynamic_routes_and_their_errors() -> None:
    client, _flask_calls = _client(FakeDynamicService())

    schema = client.get("/v2/openapi.json").json()

    create = schema["paths"]["/v2/dynamics"]["post"]
    detail = schema["paths"]["/v2/dynamics/{dynamic_id}"]["get"]
    assert set(schema["paths"]["/v2/dynamics"]) == {"post"}
    assert set(schema["paths"]["/v2/dynamics/{dynamic_id}"]) == {"get"}
    assert {"200", "201", "400", "404", "409", "413", "422", "500", "503"} <= set(
        create["responses"]
    )
    assert {"200", "404", "503"} <= set(detail["responses"])
    query_names = {
        parameter["name"]
        for parameter in create["parameters"]
        if parameter["in"] == "query"
    }
    assert query_names == {"country_id", "policyengine_version"}
    request_schema = schema["components"]["schemas"]["DynamicCreateRequest"]
    parameter_values = request_schema["properties"]["parameter_values"]
    assert parameter_values["minItems"] == 1
    assert parameter_values["maxItems"] == 1_000
    assert "dynamic_id null" in parameter_values["description"]
