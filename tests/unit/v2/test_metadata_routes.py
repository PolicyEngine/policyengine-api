"""Typed route coverage for dormant v2 metadata resources."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.services.v2.metadata.service import (
    InvalidMetadataPageError,
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    MetadataResourceNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.metadata.read_models import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataRegionOption,
    MetadataTimePeriodOption,
    MetadataVariable,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes import dependencies as route_dependencies
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)


class ResourceReader:
    def __init__(
        self,
        results: dict[str, object],
        *,
        error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self.results = results
        self.error = error
        self.close_error = close_error
        self.calls: list[tuple[str, tuple, dict]] = []
        self.closed = False

    def __getattr__(self, name: str):
        if name not in self.results:
            raise AttributeError(name)

        def read(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if self.error is not None:
                raise self.error
            return self.results[name]

        return read

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _resource_results() -> tuple[dict[str, object], dict[str, object]]:
    version = "4.20.3"
    model_id = uuid4()
    model_version_id = uuid4()
    variable_id = uuid4()
    parameter_id = uuid4()
    parameter_value_id = uuid4()
    dataset_id = uuid4()
    region_id = uuid4()
    model = MetadataModel(
        id=model_id,
        name="policyengine-us",
        description="US model",
    )
    model_version = MetadataModelVersionDetail(
        id=model_version_id,
        model_id=model_id,
        version=version,
        description="PolicyEngine.py catalog",
        current_law_id=2,
        metadata_time_periods=[2026],
    )
    variable = MetadataVariable(
        id=variable_id,
        name="employment_income",
        label="Employment income",
        entity="person",
        description=None,
        data_type="float",
        possible_values=None,
        default_value=0,
        adds=None,
        subtracts=None,
    )
    parameter = MetadataParameterSummary(
        id=parameter_id,
        name="gov.example.rate",
        label="Rate",
        description=None,
        data_type="float",
        unit="/1",
    )
    parameter_value = MetadataCanonicalParameterValue(
        id=parameter_value_id,
        parameter_id=parameter_id,
        value=0.1,
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=None,
    )
    dataset = MetadataDataset(
        id=dataset_id,
        name="populace_us_2024",
        description="National input dataset",
        year=2024,
    )
    region = MetadataRegion(
        id=region_id,
        code="us",
        label="United States",
        region_type="national",
        requires_filter=False,
        filter_field=None,
        filter_value=None,
        filter_strategy=None,
        parent_code=None,
        state_code=None,
        state_name=None,
        default_dataset_id=dataset_id,
    )

    def page(items: list[object]) -> MetadataPageResult:
        return MetadataPageResult(
            policyengine_version=version,
            items=items,
            offset=0,
            limit=100,
            has_more=False,
        )

    def detail(item: object) -> MetadataDetailResult:
        return MetadataDetailResult(policyengine_version=version, item=item)

    return (
        {
            "list_models": page([model]),
            "get_model": detail(model),
            "get_model_by_country": MetadataModelSelectionResult(
                policyengine_version=version,
                model=model,
                model_version=model_version,
            ),
            "list_model_versions": page([model_version]),
            "get_model_version": detail(model_version),
            "list_variables": page([variable]),
            "get_variable": detail(variable),
            "list_parameters": page([parameter]),
            "list_parameter_children": page(
                [
                    MetadataParameterChild(
                        path=parameter.name,
                        label=parameter.label or parameter.name,
                        type="parameter",
                        parameter=parameter,
                    )
                ]
            ),
            "get_parameter": detail(parameter),
            "list_parameter_values": page([parameter_value]),
            "get_parameter_value": detail(parameter_value),
            "list_datasets": page([dataset]),
            "get_dataset": detail(dataset),
            "list_regions": page([region]),
            "get_region_by_code": detail(region),
            "get_region": detail(region),
            "get_economy_options": MetadataEconomyOptionsResult(
                policyengine_version=version,
                current_law_id=2,
                region=[
                    MetadataRegionOption(
                        name="us",
                        label="United States",
                        type="national",
                    )
                ],
                time_period=[MetadataTimePeriodOption(name=2026, label="2026")],
                datasets=[
                    MetadataDatasetOption(name="populace_us_2024", label="Microcosm")
                ],
            ),
        },
        {
            "model_id": model_id,
            "model_version_id": model_version_id,
            "variable_id": variable_id,
            "parameter_id": parameter_id,
            "parameter_value_id": parameter_value_id,
            "dataset_id": dataset_id,
            "region_id": region_id,
        },
    )


def _client(factory) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.get("/<country_id>/metadata")
    def v1_metadata(country_id: str):
        return jsonify(
            {
                "status": "ok",
                "message": None,
                "result": {"source": "v1", "country_id": country_id},
            }
        )

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        v2_metadata_reader_factory=factory,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            flask_app,
            dependencies=dependencies,
            route_settings=settings,
        ),
        raise_server_exceptions=False,
    )


def test_each_resource_route_returns_its_typed_result() -> None:
    results, ids = _resource_results()
    reader = ResourceReader(results)
    client = _client(lambda: reader)
    requests = [
        ("list_models", "/v2/tax-benefit-models?country_id=us"),
        ("get_model_by_country", "/v2/tax-benefit-models/by-country/us"),
        (
            "get_model",
            f"/v2/tax-benefit-models/{ids['model_id']}?country_id=us",
        ),
        (
            "list_model_versions",
            "/v2/tax-benefit-model-versions?country_id=us",
        ),
        (
            "get_model_version",
            f"/v2/tax-benefit-model-versions/{ids['model_version_id']}?country_id=us",
        ),
        ("list_variables", "/v2/variables?country_id=us"),
        ("get_variable", f"/v2/variables/{ids['variable_id']}?country_id=us"),
        ("list_parameters", "/v2/parameters?country_id=us"),
        (
            "list_parameter_children",
            "/v2/parameters/children?country_id=us&parent_path=gov.example",
        ),
        (
            "get_parameter",
            f"/v2/parameters/{ids['parameter_id']}?country_id=us",
        ),
        ("list_parameter_values", "/v2/parameter-values?country_id=us"),
        (
            "get_parameter_value",
            f"/v2/parameter-values/{ids['parameter_value_id']}?country_id=us",
        ),
        ("list_datasets", "/v2/datasets?country_id=us"),
        ("get_dataset", f"/v2/datasets/{ids['dataset_id']}?country_id=us"),
        ("list_regions", "/v2/regions?country_id=us"),
        ("get_region_by_code", "/v2/regions/by-code/us?country_id=us"),
        ("get_region", f"/v2/regions/{ids['region_id']}?country_id=us"),
        ("get_economy_options", "/v2/economy-options?country_id=us"),
    ]

    for expected_method, path in requests:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["message"] is None
        assert payload["result"]["policyengine_version"] == "4.20.3"
        assert reader.calls[-1][0] == expected_method

    assert reader.closed


def test_resource_route_forwards_version_filters_and_pagination() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)
    response = _client(lambda: reader).get(
        "/v2/variables",
        params={
            "country_id": "uk",
            "policyengine_version": "4.19.0",
            "offset": 25,
            "limit": 50,
            "search": "income",
        },
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_variables",
            ("uk", "4.19.0"),
            {"offset": 25, "limit": 50, "search": "income"},
        )
    ]
    assert reader.closed


def test_region_code_route_decodes_percent_encoded_slash() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/regions/by-code/state%2Fca",
        params={"country_id": "us"},
    )

    assert response.status_code == 200
    assert reader.calls == [("get_region_by_code", ("us", "state/ca", None), {})]
    assert reader.closed


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"country_id": "us", "offset": -1},
        {"country_id": "us", "limit": 0},
        {"country_id": "us", "limit": 501},
    ],
)
def test_request_validation_failures_use_the_error_schema(params: dict) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    response = _client(factory).get("/v2/variables", params=params)

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid v2 metadata request",
    }
    assert calls == []


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (InvalidMetadataPageError("invalid page"), 400),
        (InvalidPolicyEngineVersionError("invalid version"), 400),
        (UnsupportedPreviewCountryError("ca"), 400),
        (MetadataResourceNotFoundError("missing variable"), 404),
        (MetadataCatalogVersionNotFoundError("missing version"), 404),
        (MetadataCatalogUnavailableError("unavailable"), 503),
        (V2ConfigurationError("missing database URL"), 503),
        (RuntimeError("private query detail"), 500),
    ],
)
def test_query_failures_use_documented_error_statuses(
    error: Exception,
    expected_status: int,
) -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results, error=error)
    response = _client(lambda: reader).get("/v2/variables?country_id=us")

    assert response.status_code == expected_status
    assert response.json()["status"] == "error"
    assert response.json()["message"]
    assert "private query detail" not in response.text
    assert reader.closed


def test_unknown_resources_and_unsupported_methods_use_error_schema() -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    client = _client(factory)
    missing_root = client.get("/v2")
    missing = client.get("/v2/not-a-resource")
    removed_combined = client.get("/v2/us/metadata")

    assert missing_root.status_code == 404
    assert missing_root.json()["status"] == "error"
    assert missing.status_code == 404
    assert missing.json()["status"] == "error"
    assert removed_combined.status_code == 404
    assert removed_combined.json()["status"] == "error"
    for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        for path in ("/v2", "/v2/variables"):
            response = client.request(method, path)
            assert response.status_code == 405
            if method != "HEAD":
                assert response.json()["status"] == "error"
    assert calls == []


def test_default_reader_uses_the_installed_policyengine_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.data.v2 import database
    from policyengine_api.services.v2.metadata import service as metadata_service

    session = object()
    captured = {}
    reader = object()

    def query_service(candidate_session, *, running_policyengine_version):
        captured["session"] = candidate_session
        captured["version"] = running_policyengine_version
        return reader

    monkeypatch.setattr(database, "get_v2_session_factory", lambda: lambda: session)
    monkeypatch.setattr(metadata_service, "V2MetadataService", query_service)
    monkeypatch.setattr(
        route_dependencies.importlib_metadata,
        "version",
        lambda package: "5.2.0" if package == "policyengine" else "unexpected",
    )
    route_dependencies._running_policyengine_version.cache_clear()
    try:
        result = route_dependencies._default_v2_metadata_reader_factory()
    finally:
        route_dependencies._running_policyengine_version.cache_clear()

    assert result is reader
    assert captured == {"session": session, "version": "5.2.0"}


def test_default_factory_and_close_failures_preserve_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results, close_error=RuntimeError("close failed"))
    monkeypatch.setattr(
        route_dependencies,
        "_default_v2_metadata_reader_factory",
        lambda: reader,
    )

    response = _client(None).get("/v2/variables?country_id=us")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert reader.closed


def test_resource_reads_do_not_change_v1_metadata_routing() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)
    client = _client(lambda: reader)

    first = client.get("/v2/variables?country_id=us")
    second = client.get("/v2/variables?country_id=us")
    v1 = client.get("/us/metadata")

    assert first.json() == second.json()
    assert v1.json()["result"] == {"source": "v1", "country_id": "us"}


def test_resource_route_logging_records_the_country_query_parameter() -> None:
    results, _ids = _resource_results()

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = _client(lambda: ResourceReader(results)).get(
            "/v2/variables?country_id=uk"
        )

    assert response.status_code == 200
    payload = mock_logger.log_struct.call_args.args[0]
    assert payload["country_id"] == "uk"
    assert payload["migration"]["route_group"] == "metadata"
    assert payload["migration"]["db_read"] == "supabase"


def test_openapi_references_explicit_resource_response_schemas() -> None:
    results, _ids = _resource_results()
    response = _client(lambda: ResourceReader(results)).get("/v2/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    metadata_paths = {
        "/v2/datasets",
        "/v2/datasets/{dataset_id}",
        "/v2/economy-options",
        "/v2/parameters",
        "/v2/parameters/children",
        "/v2/parameters/{parameter_id}",
        "/v2/parameter-values",
        "/v2/parameter-values/{value_id}",
        "/v2/regions",
        "/v2/regions/by-code/{region_code}",
        "/v2/regions/{region_id}",
        "/v2/tax-benefit-models",
        "/v2/tax-benefit-models/by-country/{country_id}",
        "/v2/tax-benefit-models/{model_id}",
        "/v2/tax-benefit-model-versions",
        "/v2/tax-benefit-model-versions/{version_id}",
        "/v2/variables",
        "/v2/variables/{variable_id}",
    }
    native_paths = {
        "/v2/policies",
        "/v2/policies/{policy_id}",
        "/v2/user-policies",
        "/v2/user-policies/{association_id}",
    }
    assert set(schema["paths"]) == metadata_paths | native_paths

    for path in metadata_paths:
        operation = schema["paths"][path]["get"]
        assert set(operation["responses"]) >= {
            "200",
            "400",
            "404",
            "405",
            "422",
            "500",
            "503",
        }
        success_schema = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert success_schema["$ref"].startswith("#/components/schemas/Metadata")
        for status in ("400", "404", "405", "422", "500", "503"):
            error_schema = operation["responses"][status]["content"][
                "application/json"
            ]["schema"]
            assert error_schema["$ref"] == "#/components/schemas/MetadataErrorResponse"
