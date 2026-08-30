"""Typed route coverage for the dormant v2 metadata preview."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.query import (
    InvalidMetadataPageError,
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    MetadataResourceNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptions,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersion,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameter,
    MetadataParameterChild,
    MetadataParameterNode,
    MetadataParameterSummary,
    MetadataParameterValue,
    MetadataRegion,
    MetadataRegionOption,
    MetadataResult,
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


class Reader:
    def __init__(
        self,
        result: MetadataResult,
        error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self.result = result
        self.error = error
        self.close_error = close_error
        self.calls = []
        self.closed = False

    def get_metadata(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataResult:
        self.calls.append((country_id, policyengine_version))
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class ResourceReader:
    def __init__(
        self,
        results: dict[str, object],
        *,
        error: Exception | None = None,
    ):
        self.results = results
        self.error = error
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


def _result(country_id: str = "us") -> MetadataResult:
    model_id = uuid4()
    version_id = uuid4()
    dataset_id = uuid4()
    region_id = uuid4()
    parameter_id = uuid4()
    return MetadataResult(
        current_law_id=2 if country_id == "us" else 1,
        model=MetadataModel(
            id=model_id,
            name=f"policyengine-{country_id}",
            description="Model",
        ),
        model_version=MetadataModelVersion(
            id=version_id,
            model_id=model_id,
            version="4.20.3",
            description="PolicyEngine.py catalog",
        ),
        variables=[
            MetadataVariable(
                id=uuid4(),
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
        ],
        parameter_nodes=[
            MetadataParameterNode(
                id=uuid4(),
                name="gov.example",
                label="Example",
                description=None,
            )
        ],
        parameters=[
            MetadataParameter(
                id=parameter_id,
                name="gov.example.rate",
                label="Rate",
                description=None,
                data_type="float",
                unit="/1",
                values=[
                    MetadataParameterValue(
                        id=uuid4(),
                        value=0.1,
                        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                        end_date=None,
                    )
                ],
            )
        ],
        datasets=[
            MetadataDataset(
                id=dataset_id,
                name=f"populace_{country_id}_2024",
                description="Populace",
                year=2024,
            )
        ],
        regions=[
            MetadataRegion(
                id=region_id,
                code=country_id,
                label=country_id.upper(),
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
        ],
        economy_options=MetadataEconomyOptions(
            region=[
                MetadataRegionOption(
                    name=country_id,
                    label=country_id.upper(),
                    type="national",
                )
            ],
            time_period=[MetadataTimePeriodOption(name=2026, label="2026")],
            datasets=[],
        ),
    )


def _resource_results(country_id: str = "us") -> dict[str, object]:
    combined = _result(country_id)
    version = combined.model_version.version
    model_version = MetadataModelVersionDetail(
        **combined.model_version.model_dump(),
        current_law_id=combined.current_law_id,
        metadata_time_periods=[2026],
    )
    parameter = combined.parameters[0]
    parameter_summary = MetadataParameterSummary(
        **parameter.model_dump(exclude={"values"})
    )
    parameter_value = MetadataCanonicalParameterValue(
        parameter_id=parameter.id,
        **parameter.values[0].model_dump(),
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

    return {
        "list_models": page([combined.model]),
        "get_model": detail(combined.model),
        "get_model_by_country": MetadataModelSelectionResult(
            policyengine_version=version,
            model=combined.model,
            model_version=model_version,
        ),
        "list_model_versions": page([model_version]),
        "get_model_version": detail(model_version),
        "list_variables": page(combined.variables),
        "get_variable": detail(combined.variables[0]),
        "list_parameters": page([parameter_summary]),
        "list_parameter_children": page(
            [
                MetadataParameterChild(
                    path=parameter_summary.name,
                    label=parameter_summary.label or parameter_summary.name,
                    type="parameter",
                    parameter=parameter_summary,
                )
            ]
        ),
        "get_parameter": detail(parameter_summary),
        "list_parameter_values": page([parameter_value]),
        "get_parameter_value": detail(parameter_value),
        "list_datasets": page(combined.datasets),
        "get_dataset": detail(combined.datasets[0]),
        "list_regions": page(combined.regions),
        "get_region_by_code": detail(combined.regions[0]),
        "get_region": detail(combined.regions[0]),
        "get_economy_options": MetadataEconomyOptionsResult(
            policyengine_version=version,
            current_law_id=combined.current_law_id,
            **combined.economy_options.model_dump(),
        ),
    }


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


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_preview_get_returns_typed_catalog_response(country_id: str) -> None:
    readers = []

    def factory():
        reader = Reader(_result(country_id))
        readers.append(reader)
        return reader

    response = _client(factory).get(f"/v2/{country_id}/metadata")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["message"] is None
    assert payload["result"]["current_law_id"] == (2 if country_id == "us" else 1)
    assert payload["result"]["model_version"]["version"] == "4.20.3"
    assert payload["result"]["economy_options"]["region"][0]["name"] == country_id
    assert isinstance(
        payload["result"]["economy_options"]["time_period"][0]["name"],
        int,
    )
    assert readers[0].calls == [(country_id, None)]
    assert readers[0].closed


def test_unsupported_country_and_methods_return_typed_client_errors() -> None:
    calls = []

    def factory():
        calls.append("called")
        return Reader(_result())

    client = _client(factory)
    country_response = client.get("/v2/ca/metadata")
    assert country_response.status_code == 404
    assert country_response.json()["status"] == "error"
    assert country_response.json()["message"]

    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        response = client.request(method, "/v2/us/metadata")
        assert response.status_code == 405
        assert response.json()["status"] == "error"
        assert response.json()["message"]
    assert calls == []


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (MetadataCatalogUnavailableError("missing"), 503),
        (V2ConfigurationError("missing URL"), 503),
        (RuntimeError("private database detail"), 500),
    ],
)
def test_preview_failures_are_typed_and_hide_internal_details(
    error: Exception,
    expected_status: int,
) -> None:
    reader = Reader(_result(), error=error)
    response = _client(lambda: reader).get("/v2/us/metadata")

    assert response.status_code == expected_status
    assert response.json()["status"] == "error"
    assert response.json()["message"]
    assert "private database detail" not in response.text
    assert reader.closed


@pytest.mark.parametrize(
    ("version", "error", "expected_status"),
    [
        (
            "not a version",
            InvalidPolicyEngineVersionError("invalid PolicyEngine.py version"),
            400,
        ),
        (
            "4.99.0",
            MetadataCatalogVersionNotFoundError(
                "PolicyEngine.py 4.99.0 is not published for us"
            ),
            404,
        ),
    ],
)
def test_preview_version_selector_returns_typed_client_errors(
    version: str,
    error: Exception,
    expected_status: int,
) -> None:
    reader = Reader(_result(), error=error)

    response = _client(lambda: reader).get(
        "/v2/us/metadata",
        params={"policyengine_version": version},
    )

    assert response.status_code == expected_status
    assert response.json()["status"] == "error"
    assert response.json()["message"]
    assert reader.calls == [("us", version)]
    assert reader.closed


def test_preview_passes_explicit_version_to_reader() -> None:
    result = _result()
    result.model_version.version = "4.19.0"
    reader = Reader(result)

    response = _client(lambda: reader).get(
        "/v2/us/metadata",
        params={"policyengine_version": "4.19.0"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["model_version"]["version"] == "4.19.0"
    assert reader.calls == [("us", "4.19.0")]


def test_preview_uses_default_reader_factory_when_none_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = Reader(_result())
    monkeypatch.setattr(
        route_dependencies,
        "_default_v2_metadata_reader_factory",
        lambda: reader,
    )

    response = _client(None).get("/v2/us/metadata")

    assert response.status_code == 200
    assert reader.calls == [("us", None)]
    assert reader.closed


def test_preview_ignores_reader_close_failure() -> None:
    reader = Reader(_result(), close_error=RuntimeError("close failed"))

    response = _client(lambda: reader).get("/v2/us/metadata")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert reader.closed


def test_default_reader_uses_the_installed_policyengine_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.data.v2 import database
    from policyengine_api.data.v2.catalog import query

    session = object()
    captured = {}
    reader = object()

    def query_service(candidate_session, *, running_policyengine_version):
        captured["session"] = candidate_session
        captured["version"] = running_policyengine_version
        return reader

    monkeypatch.setattr(database, "get_v2_session_factory", lambda: lambda: session)
    monkeypatch.setattr(query, "V2MetadataQueryService", query_service)
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


def test_preview_reads_repeat_without_changing_v1_routing() -> None:
    reader = Reader(_result())
    client = _client(lambda: reader)

    first = client.get("/v2/us/metadata")
    second = client.get("/v2/us/metadata")
    v1 = client.get("/us/metadata")

    assert first.json() == second.json()
    assert reader.calls == [("us", None), ("us", None)]
    assert v1.json()["result"] == {"source": "v1", "country_id": "us"}


def test_openapi_references_explicit_preview_response_schemas() -> None:
    client = _client(lambda: Reader(_result()))
    response = client.get("/v2/openapi.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    schema = response.json()
    assert set(schema["paths"]) == {
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
        "/v2/us/metadata",
        "/v2/uk/metadata",
        "/v2/variables",
        "/v2/variables/{variable_id}",
        "/v2/{country_id}/metadata",
    }

    for path in ("/v2/us/metadata", "/v2/uk/metadata"):
        operation = schema["paths"][path]["get"]
        assert set(operation["responses"]) >= {
            "200",
            "400",
            "404",
            "405",
            "500",
            "503",
        }
        assert (
            operation["responses"]["200"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/MetadataSuccessResponse"
        )
        for status in ("400", "404", "405", "500", "503"):
            assert (
                operation["responses"][status]["content"]["application/json"]["schema"][
                    "$ref"
                ]
                == "#/components/schemas/MetadataErrorResponse"
            )

    unsupported = schema["paths"]["/v2/{country_id}/metadata"]
    assert set(unsupported) == {"get"}
    assert (
        unsupported["get"]["responses"]["404"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/MetadataErrorResponse"
    )


def test_each_split_resource_route_returns_its_typed_result() -> None:
    reader = ResourceReader(_resource_results())
    client = _client(lambda: reader)
    combined = _result()
    parameter = combined.parameters[0]
    requests = [
        ("list_models", "/v2/tax-benefit-models?country_id=us"),
        ("get_model_by_country", "/v2/tax-benefit-models/by-country/us"),
        (
            "get_model",
            f"/v2/tax-benefit-models/{combined.model.id}?country_id=us",
        ),
        (
            "list_model_versions",
            "/v2/tax-benefit-model-versions?country_id=us",
        ),
        (
            "get_model_version",
            f"/v2/tax-benefit-model-versions/{combined.model_version.id}?country_id=us",
        ),
        ("list_variables", "/v2/variables?country_id=us"),
        (
            "get_variable",
            f"/v2/variables/{combined.variables[0].id}?country_id=us",
        ),
        ("list_parameters", "/v2/parameters?country_id=us"),
        (
            "list_parameter_children",
            "/v2/parameters/children?country_id=us&parent_path=gov.example",
        ),
        ("get_parameter", f"/v2/parameters/{parameter.id}?country_id=us"),
        ("list_parameter_values", "/v2/parameter-values?country_id=us"),
        (
            "get_parameter_value",
            f"/v2/parameter-values/{parameter.values[0].id}?country_id=us",
        ),
        ("list_datasets", "/v2/datasets?country_id=us"),
        (
            "get_dataset",
            f"/v2/datasets/{combined.datasets[0].id}?country_id=us",
        ),
        ("list_regions", "/v2/regions?country_id=us"),
        (
            "get_region_by_code",
            f"/v2/regions/by-code/{combined.regions[0].code}?country_id=us",
        ),
        (
            "get_region",
            f"/v2/regions/{combined.regions[0].id}?country_id=us",
        ),
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


def test_split_route_forwards_version_filters_and_pagination() -> None:
    reader = ResourceReader(_resource_results())
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


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"country_id": "us", "offset": -1},
        {"country_id": "us", "limit": 0},
        {"country_id": "us", "limit": 501},
    ],
)
def test_split_route_validation_failures_use_the_error_schema(params: dict) -> None:
    calls = []

    def factory():
        calls.append("called")
        return ResourceReader(_resource_results())

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
        (RuntimeError("private query detail"), 500),
    ],
)
def test_split_route_query_failures_use_documented_error_statuses(
    error: Exception,
    expected_status: int,
) -> None:
    reader = ResourceReader(_resource_results(), error=error)
    response = _client(lambda: reader).get("/v2/variables?country_id=us")

    assert response.status_code == expected_status
    assert response.json()["status"] == "error"
    assert response.json()["message"]
    assert "private query detail" not in response.text
    assert reader.closed
