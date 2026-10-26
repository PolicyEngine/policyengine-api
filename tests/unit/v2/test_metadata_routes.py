"""Typed route coverage for dormant v2 metadata resources."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes import dependencies as route_dependencies
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    MetadataResponseCache,
)
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.metadata.selected_catalogs import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogParameter,
    MetadataCatalogParametersResult,
    MetadataCatalogVariablesResult,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataDatedValue,
    MetadataDetailResult,
    MetadataEconomyOptions,
    MetadataEconomyOptionsResult,
    MetadataEntity,
    MetadataModel,
    MetadataModelCatalogResult,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataRegionOption,
    MetadataTimePeriodOption,
    MetadataVariable,
    ParameterFilter,
    ParameterTreeLevel,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    ParameterTreeUnavailableError,
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
        is_input_variable=True,
        hidden_input=False,
        module_name=None,
        adds_parameter_path=None,
        subtracts_parameter_path=None,
        enum_values=None,
        unit="currency-USD",
        definition_period="year",
    )
    parameter = MetadataParameterSummary(
        id=parameter_id,
        name="gov.example.rate",
        label="Rate",
        description=None,
        data_type="float",
        unit="/1",
        economy=True,
        household=False,
    )
    parameter_value = MetadataCanonicalParameterValue(
        id=parameter_value_id,
        parameter_id=parameter_id,
        value=0.1,
        start_date=datetime(2025, 1, 1, tzinfo=UTC),
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
            "get_catalog_parameters": MetadataCatalogParametersResult(
                policyengine_version=version,
                catalog_format=2,
                parameters=[
                    MetadataCatalogParameter(
                        **parameter.model_dump(),
                        values=[
                            MetadataDatedValue(
                                start_date=datetime(2025, 1, 1, tzinfo=UTC),
                                end_date=None,
                                value=0.1,
                            )
                        ],
                    )
                ],
                node_labels={"gov.example": "Example policy"},
                missing_names=["gov.removed"],
            ),
            "get_catalog_variables": MetadataCatalogVariablesResult(
                policyengine_version=version,
                catalog_format=2,
                variables=[variable],
                part_parameter_values={
                    "gov.example.parts": [
                        MetadataDatedValue(
                            start_date=datetime(2025, 1, 1, tzinfo=UTC),
                            end_date=None,
                            value=["employment_income"],
                        )
                    ]
                },
            ),
            "get_model_catalog": MetadataModelCatalogResult(
                policyengine_version=version,
                catalog_format=2,
                model=model,
                model_version=model_version,
                entities=[
                    MetadataEntity(key="person", plural="people", is_person=True)
                ],
                basic_inputs=["employment_income"],
                regions=[region],
                datasets=[dataset],
                economy_options=MetadataEconomyOptions(
                    region=[
                        MetadataRegionOption(
                            name="us", label="United States", type="national"
                        )
                    ],
                    time_period=[MetadataTimePeriodOption(name=2026, label="2026")],
                    datasets=[
                        MetadataDatasetOption(
                            name="populace_us_2024", label="Microcosm"
                        )
                    ],
                ),
            ),
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


def _client(factory, *, response_cache=None) -> TestClient:
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
        specification_provider=dict,
        v2_metadata_reader_factory=factory,
        v2_metadata_response_cache=response_cache,
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
        "message": "Invalid API v2 request",
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
    from policyengine_api.services.v2.metadata import services as metadata_services

    session = object()
    captured = {}
    reader = object()

    def query_service(
        candidate_session, *, running_policyengine_version, selected_catalogs
    ):
        captured["session"] = candidate_session.session
        captured["version"] = running_policyengine_version
        captured["selected_catalogs"] = selected_catalogs
        return reader

    monkeypatch.setattr(
        database, "get_v2_read_session_factory", lambda: lambda: session
    )
    monkeypatch.setattr(metadata_services, "V2MetadataService", query_service)
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
    assert captured["session"] is session
    assert captured["version"] == "5.2.0"
    assert isinstance(captured["selected_catalogs"], SelectedCatalogStore)
    assert (
        route_dependencies._process_selected_catalogs() is captured["selected_catalogs"]
    )


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
        "/v2/model-catalog",
        "/v2/model-catalog/variables",
        "/v2/model-catalog/parameters",
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
        "/v2/households",
        "/v2/households/{household_id}",
        "/v2/policies",
        "/v2/policies/{policy_id}",
        "/v2/user-households",
        "/v2/user-households/{association_id}",
        "/v2/user-policies",
        "/v2/user-policies/{association_id}",
        "/v2/user-simulations",
        "/v2/user-simulations/{association_id}",
        "/v2/user-reports",
        "/v2/user-reports/{association_id}",
        "/v2/shared-reports/{association_id}",
        "/v2/me",
        "/v2/me/export",
        "/v2/me/upgrade",
    }
    assert set(schema["paths"]) == metadata_paths | native_paths
    assert "V2ErrorResponse" in schema["components"]["schemas"]
    assert {
        "MetadataErrorResponse",
        "PolicyErrorResponse",
        "UserPolicyErrorResponse",
    }.isdisjoint(schema["components"]["schemas"])

    for path in metadata_paths:
        operation = schema["paths"][path]["get"]
        error_statuses = ["404", "405", "422", "500", "503"]
        if path == "/v2/tax-benefit-models/by-country/{country_id}":
            error_statuses.append("400")
        assert set(operation["responses"]) >= {"200", *error_statuses}
        success_schema = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert success_schema["$ref"].startswith("#/components/schemas/Metadata")
        for status in error_statuses:
            error_schema = operation["responses"][status]["content"][
                "application/json"
            ]["schema"]
            assert error_schema["$ref"] == "#/components/schemas/V2ErrorResponse"


def _every_resource_path(ids: dict[str, object]) -> list[str]:
    return [
        "/v2/tax-benefit-models?country_id=us",
        "/v2/tax-benefit-models/by-country/us",
        f"/v2/tax-benefit-models/{ids['model_id']}?country_id=us",
        "/v2/tax-benefit-model-versions?country_id=us",
        f"/v2/tax-benefit-model-versions/{ids['model_version_id']}?country_id=us",
        "/v2/variables?country_id=us",
        f"/v2/variables/{ids['variable_id']}?country_id=us",
        "/v2/parameters?country_id=us",
        "/v2/parameters/children?country_id=us&parent_path=gov.example",
        f"/v2/parameters/{ids['parameter_id']}?country_id=us",
        "/v2/parameter-values?country_id=us",
        f"/v2/parameter-values/{ids['parameter_value_id']}?country_id=us",
        "/v2/datasets?country_id=us",
        f"/v2/datasets/{ids['dataset_id']}?country_id=us",
        "/v2/regions?country_id=us",
        "/v2/regions/by-code/us?country_id=us",
        f"/v2/regions/{ids['region_id']}?country_id=us",
        "/v2/economy-options?country_id=us",
        "/v2/model-catalog?country_id=us",
        "/v2/model-catalog/variables?country_id=us",
        "/v2/model-catalog/parameters?country_id=us&name=gov.example.rate",
    ]


def test_every_resource_route_serves_an_entity_tag_and_cache_lifetime() -> None:
    results, ids = _resource_results()
    client = _client(lambda: ResourceReader(results))

    for path in _every_resource_path(ids):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "public, max-age=300", path
        assert response.headers["etag"].startswith('"'), path
        assert response.headers["etag"].endswith('"'), path


def test_a_named_catalog_version_is_reusable_for_a_day() -> None:
    results, _ids = _resource_results()
    client = _client(lambda: ResourceReader(results))
    query = {"country_id": "us", "policyengine_version": "4.20.3"}

    first = client.get("/v2/variables", params=query)
    second = client.get("/v2/variables", params=query)

    assert first.headers["cache-control"] == "public, max-age=86400"
    assert first.headers["etag"] == second.headers["etag"]


def test_a_matching_entity_tag_gets_a_not_modified_response_without_a_body() -> None:
    results, _ids = _resource_results()
    client = _client(lambda: ResourceReader(results))
    path = "/v2/variables?country_id=us&policyengine_version=4.20.3"
    entity_tag = client.get(path).headers["etag"]

    revalidated = client.get(path, headers={"If-None-Match": entity_tag})
    weakly_revalidated = client.get(path, headers={"If-None-Match": f"W/{entity_tag}"})
    listed = client.get(path, headers={"If-None-Match": f'"other", {entity_tag}'})
    stale = client.get(path, headers={"If-None-Match": '"other"'})

    for not_modified in (revalidated, weakly_revalidated, listed):
        assert not_modified.status_code == 304
        assert not_modified.content == b""
        assert not_modified.headers["etag"] == entity_tag
        assert not_modified.headers["cache-control"] == "public, max-age=86400"
    assert stale.status_code == 200
    assert stale.json()["status"] == "ok"


def test_different_content_gets_a_different_entity_tag() -> None:
    results, _ids = _resource_results()
    changed_results, _changed_ids = _resource_results()

    first = _client(lambda: ResourceReader(results)).get("/v2/variables?country_id=us")
    changed = _client(lambda: ResourceReader(changed_results)).get(
        "/v2/variables?country_id=us"
    )

    assert first.headers["etag"] != changed.headers["etag"]


def test_failed_reads_carry_no_cache_headers() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results, error=MetadataResourceNotFoundError("missing"))

    response = _client(lambda: reader).get(
        "/v2/variables?country_id=us&policyengine_version=4.20.3"
    )

    assert response.status_code == 404
    assert "etag" not in response.headers
    assert "cache-control" not in response.headers


def test_model_catalog_route_serves_the_small_parts_of_the_selected_version() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/model-catalog", params={"country_id": "US"}
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["policyengine_version"] == "4.20.3"
    assert result["catalog_format"] == 2
    assert result["entities"] == [
        {"key": "person", "plural": "people", "is_person": True}
    ]
    assert result["basic_inputs"] == ["employment_income"]
    assert [region["code"] for region in result["regions"]] == ["us"]
    assert result["economy_options"]["datasets"][0]["default"] is True
    assert reader.calls == [("get_model_catalog", ("us", None), {})]
    assert reader.closed


def test_model_catalog_route_names_an_explicit_version_for_a_day() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/model-catalog",
        params={"country_id": "uk", "policyengine_version": "4.20.3"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert reader.calls == [("get_model_catalog", ("uk", "4.20.3"), {})]


@pytest.mark.parametrize(
    "query",
    [
        "",
        "country_id=ca",
        "country_id=us&country_id=uk",
        "country_id=us&limit=10",
        "country_id=us&policyengine_version=latest",
    ],
)
def test_model_catalog_route_rejects_invalid_queries(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    response = _client(factory).get(f"/v2/model-catalog?{query}")

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert calls == []


def test_model_catalog_route_declares_its_query_in_openapi() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()

    operation = schema["paths"]["/v2/model-catalog"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"country_id", "policyengine_version"}
    assert parameters["country_id"]["required"] is True
    assert parameters["policyengine_version"]["required"] is False
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success == {"$ref": "#/components/schemas/MetadataModelCatalogResponse"}


def test_catalog_variables_route_serves_every_variable_and_part_values() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/model-catalog/variables",
        params={"country_id": "us", "policyengine_version": "4.20.3"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    result = response.json()["result"]
    assert result["catalog_format"] == 2
    assert [variable["name"] for variable in result["variables"]] == [
        "employment_income"
    ]
    assert result["variables"][0]["module_name"] is None
    assert result["part_parameter_values"] == {
        "gov.example.parts": [
            {
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": None,
                "value": ["employment_income"],
            }
        ]
    }
    assert reader.calls == [("get_catalog_variables", ("us", "4.20.3"), {})]


@pytest.mark.parametrize(
    "query",
    ["", "country_id=us&offset=0", "country_id=us&search=income"],
)
def test_catalog_variables_route_rejects_paging_and_unknown_queries(
    query: str,
) -> None:
    results, _ids = _resource_results()
    response = _client(lambda: ResourceReader(results)).get(
        f"/v2/model-catalog/variables?{query}"
    )

    assert response.status_code == 422


def test_catalog_parameters_route_fetches_several_parameters_by_name() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/model-catalog/parameters"
        "?country_id=us&policyengine_version=4.20.3"
        "&name=gov.example.rate&name=gov.removed"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    result = response.json()["result"]
    assert result["parameters"][0]["name"] == "gov.example.rate"
    assert result["parameters"][0]["values"] == [
        {"start_date": "2025-01-01T00:00:00Z", "end_date": None, "value": 0.1}
    ]
    assert result["node_labels"] == {"gov.example": "Example policy"}
    assert result["missing_names"] == ["gov.removed"]
    assert reader.calls == [
        (
            "get_catalog_parameters",
            ("us", "4.20.3"),
            {"names": ["gov.example.rate", "gov.removed"]},
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us",
        "country_id=us&name=",
        "country_id=us&name=gov.example.rate&offset=0",
        "country_id=us&" + "&".join(f"name=gov.p{index}" for index in range(101)),
    ],
)
def test_catalog_parameters_route_rejects_invalid_name_lists(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    response = _client(factory).get(f"/v2/model-catalog/parameters?{query}")

    assert response.status_code == 422
    assert calls == []


def test_catalog_parameters_route_declares_a_repeated_name_in_openapi() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()

    operation = schema["paths"]["/v2/model-catalog/parameters"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"country_id", "policyengine_version", "name"}
    assert parameters["name"]["required"] is True
    name_schema = parameters["name"]["schema"]
    assert name_schema["type"] == "array"
    assert name_schema["minItems"] == 1
    assert name_schema["maxItems"] == 100


def test_parameter_collection_fetches_several_parameters_by_name() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)
    client = _client(lambda: reader)

    named = client.get(
        "/v2/parameters?country_id=US&name=gov.example.rate&name=gov.other.rate"
    )
    paged = client.get("/v2/parameters?country_id=us&offset=5&limit=50&search=rate")

    assert named.status_code == 200
    assert paged.status_code == 200
    assert reader.calls == [
        (
            "list_parameters",
            ("us", None),
            {
                "offset": 0,
                "limit": 100,
                "parameter_filter": ParameterFilter(
                    search=None, names=("gov.example.rate", "gov.other.rate")
                ),
            },
        ),
        (
            "list_parameters",
            ("us", None),
            {
                "offset": 5,
                "limit": 50,
                "parameter_filter": ParameterFilter(search="rate", names=None),
            },
        ),
    ]


def test_parameter_values_fetch_several_parameters_by_name() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameter-values?country_id=us&policyengine_version=4.20.3"
        "&parameter_name=gov.example.rate&parameter_name=gov.other.rate&current=true"
    )

    assert response.status_code == 200
    name, args, kwargs = reader.calls[0]
    assert (name, args) == ("list_parameter_values", ("us", "4.20.3"))
    assert kwargs["value_filter"].parameter_names == (
        "gov.example.rate",
        "gov.other.rate",
    )
    assert kwargs["value_filter"].parameter_id is None
    assert kwargs["value_filter"].current is True
    assert (kwargs["offset"], kwargs["limit"]) == (0, 100)


@pytest.mark.parametrize(
    "path",
    [
        "/v2/parameters?country_id=us&parameter_id=1",
        "/v2/parameters?country_id=us&limit=5&limit=6",
        "/v2/parameters?country_id=us&name=",
        "/v2/parameters?country_id=ca",
        "/v2/parameters?country_id=us&"
        + "&".join(f"name=gov.p{index}" for index in range(101)),
        "/v2/parameter-values?country_id=us&name=gov.example.rate",
        "/v2/parameter-values?country_id=us&current=true&current=false",
        "/v2/parameter-values?country_id=us&parameter_id=not-a-uuid",
    ],
)
def test_parameter_collections_reject_unknown_repeated_and_invalid_queries(
    path: str,
) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    response = _client(factory).get(path)

    assert response.status_code == 422
    assert calls == []


def test_parameter_collections_declare_their_name_filters_in_openapi() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()

    def query_parameters(path: str) -> dict[str, dict]:
        return {
            parameter["name"]: parameter
            for parameter in schema["paths"][path]["get"]["parameters"]
        }

    parameters = query_parameters("/v2/parameters")
    values = query_parameters("/v2/parameter-values")
    assert set(parameters) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "search",
        "name",
    }
    assert parameters["name"]["required"] is False
    assert set(values) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "parameter_id",
        "parameter_name",
        "current",
    }
    assert values["parameter_name"]["required"] is False


def test_whole_version_responses_are_read_once_per_process_and_version() -> None:
    results, _ids = _resource_results()
    readers: list[ResourceReader] = []

    def factory() -> ResourceReader:
        readers.append(ResourceReader(results))
        return readers[-1]

    client = _client(factory, response_cache=MetadataResponseCache())
    paths = [
        "/v2/model-catalog?country_id=us",
        "/v2/model-catalog/variables?country_id=us",
        "/v2/model-catalog/variables?country_id=us&policyengine_version=4.20.3",
        "/v2/model-catalog/variables?country_id=uk",
    ]

    first_responses = [client.get(path) for path in paths]
    repeated_responses = [client.get(path) for path in paths]

    # The explicit request names the running version (4.20.3), so it shares
    # the response the request without a version read: three reads in all.
    assert len(readers) == len(paths) - 1
    assert first_responses[2].content == first_responses[1].content
    for first, repeated in zip(first_responses, repeated_responses, strict=True):
        assert repeated.status_code == 200
        assert repeated.content == first.content
        assert repeated.headers["etag"] == first.headers["etag"]
        assert repeated.headers["cache-control"] == first.headers["cache-control"]
    assert all(reader.closed for reader in readers)


def test_failed_whole_version_reads_are_retried() -> None:
    results, _ids = _resource_results()
    readers = [
        ResourceReader(results, error=MetadataCatalogUnavailableError("down")),
        ResourceReader(results),
    ]
    client = _client(lambda: readers.pop(0), response_cache=MetadataResponseCache())

    failed = client.get("/v2/model-catalog/variables?country_id=us")
    recovered = client.get("/v2/model-catalog/variables?country_id=us")

    assert failed.status_code == 503
    assert "etag" not in failed.headers
    assert recovered.status_code == 200
    assert readers == []


def test_default_dependencies_share_one_response_cache() -> None:
    first = route_dependencies.NativeRouteDependencies.defaults()
    second = route_dependencies.NativeRouteDependencies.defaults()

    assert isinstance(first.v2_metadata_response_cache, MetadataResponseCache)
    assert first.v2_metadata_response_cache is second.v2_metadata_response_cache


@pytest.mark.parametrize(
    ("now", "query", "expected_cache_control"),
    [
        (
            datetime(2026, 12, 31, 23, 0, tzinfo=UTC),
            "&policyengine_version=4.20.3&current=true",
            "public, max-age=3600",
        ),
        (
            datetime(2026, 12, 31, 23, 58, tzinfo=UTC),
            "&current=true",
            "public, max-age=120",
        ),
        (
            datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            "&current=true",
            "public, max-age=300",
        ),
        (
            datetime(2026, 12, 31, 23, 0, tzinfo=UTC),
            "&policyengine_version=4.20.3&current=false",
            "public, max-age=86400",
        ),
        (
            datetime(2026, 12, 31, 23, 0, tzinfo=UTC),
            "&policyengine_version=4.20.3",
            "public, max-age=86400",
        ),
    ],
)
def test_current_parameter_values_are_reused_only_until_the_next_utc_day(
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    query: str,
    expected_cache_control: str,
) -> None:
    from policyengine_api.fastapi_routes.v2.metadata import common

    monkeypatch.setattr(common, "utc_now", lambda: now)
    results, _ids = _resource_results()

    response = _client(lambda: ResourceReader(results)).get(
        f"/v2/parameter-values?country_id=us{query}"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == expected_cache_control


def test_a_kept_response_is_served_without_hashing_its_body_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.fastapi_routes.v2.metadata import common, response_cache

    hashed_bodies: list[int] = []
    original_entity_tag = response_cache.body_entity_tag

    def counting_entity_tag(body: bytes) -> str:
        hashed_bodies.append(len(body))
        return original_entity_tag(body)

    monkeypatch.setattr(response_cache, "body_entity_tag", counting_entity_tag)
    monkeypatch.setattr(common, "body_entity_tag", counting_entity_tag)
    results, _ids = _resource_results()
    client = _client(
        lambda: ResourceReader(results), response_cache=MetadataResponseCache()
    )

    first = client.get("/v2/model-catalog/variables?country_id=us")
    hashed_after_first = len(hashed_bodies)
    second = client.get(
        "/v2/model-catalog/variables?country_id=us&policyengine_version=4.20.3"
    )

    assert hashed_after_first == 1
    assert len(hashed_bodies) == 1
    assert second.headers["etag"] == first.headers["etag"]
    assert second.content == first.content


def _query_rejections(path: str) -> list[str]:
    separator = "&" if "?" in path else "?"
    rejections = [
        f"{path}{separator}policyengine_version=not%20a%20version",
        f"{path}{separator}unexpected=1",
        f"{path}{separator}policyengine_version=4.20.3&policyengine_version=4.20.3",
    ]
    if "country_id=us" in path:
        rejections.append(path.replace("country_id=us", "country_id=ca"))
        rejections.append(
            path.replace("country_id=us&", "").replace("?country_id=us", "")
        )
    return rejections


def test_every_metadata_route_rejects_invalid_queries_before_reading() -> None:
    _results, ids = _resource_results()
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    client = _client(factory)
    for path in _every_resource_path(ids):
        for rejected in _query_rejections(path):
            response = client.get(rejected)
            assert response.status_code == 422, (rejected, response.text)
            assert response.json() == {
                "status": "error",
                "message": "Invalid API v2 request",
            }
    assert calls == []


def test_every_metadata_route_declares_the_shared_catalog_query() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()
    metadata_paths = [
        path
        for path in schema["paths"]
        if path.startswith(
            (
                "/v2/datasets",
                "/v2/economy-options",
                "/v2/model-catalog",
                "/v2/parameter",
                "/v2/regions",
                "/v2/tax-benefit-model",
                "/v2/variables",
            )
        )
    ]

    assert len(metadata_paths) == 21
    for path in metadata_paths:
        parameters = {
            parameter["name"]: parameter
            for parameter in schema["paths"][path]["get"]["parameters"]
            if parameter["in"] == "query"
        }
        version = parameters["policyengine_version"]
        assert version["required"] is False, path
        assert version["schema"]["anyOf"][0]["maxLength"] == 128, path
        if path != "/v2/tax-benefit-models/by-country/{country_id}":
            country = parameters["country_id"]
            assert country["required"] is True, path
            assert country["schema"]["enum"] == ["us", "uk"], path


def test_browser_scripts_can_read_a_metadata_response_entity_tag() -> None:
    results, _ids = _resource_results()

    response = _client(lambda: ResourceReader(results)).get(
        "/v2/model-catalog?country_id=us",
        headers={"Origin": "https://app.policyengine.org"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://app.policyengine.org"
    )
    exposed_headers = {
        value.strip().lower()
        for value in response.headers["access-control-expose-headers"].split(",")
    }
    assert "etag" in exposed_headers


def test_current_values_read_just_before_midnight_expire_at_that_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The read and the response headers must use the same day: values read for
    # 31 December may not be reused into 1 January, even when the headers are
    # written after midnight.
    from policyengine_api.fastapi_routes.v2.metadata import common

    read_instant = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    instants = iter([read_instant, datetime(2027, 1, 1, 0, 0, 1, tzinfo=UTC)])
    monkeypatch.setattr(common, "utc_now", lambda: next(instants))
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameter-values?country_id=us&policyengine_version=4.20.3&current=true"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0"
    _name, _args, kwargs = reader.calls[0]
    assert kwargs["value_filter"].now == read_instant


def _vary_values(response) -> set[str]:
    return {
        value.strip().lower()
        for value in response.headers.get("vary", "").split(",")
        if value.strip()
    }


@pytest.mark.parametrize("origin", [None, "https://app.policyengine.org"])
def test_cacheable_metadata_responses_vary_by_origin(origin: str | None) -> None:
    # The API reflects any origin, so a shared cache must not reuse a response
    # stored for a request without Origin (no Access-Control-Allow-Origin) for
    # a cross-origin one, or the reverse.
    results, _ids = _resource_results()
    client = _client(lambda: ResourceReader(results))
    headers = {} if origin is None else {"Origin": origin}

    small = client.get("/v2/tax-benefit-models?country_id=us", headers=headers)
    large = client.get("/v2/model-catalog?country_id=us", headers=headers)
    revalidated = client.get(
        "/v2/model-catalog?country_id=us",
        headers={**headers, "If-None-Match": large.headers["etag"]},
    )

    assert revalidated.status_code == 304
    for response in (small, large, revalidated):
        assert "origin" in _vary_values(response)
    assert "accept-encoding" in _vary_values(large)


def test_failed_metadata_reads_do_not_add_vary_by_origin() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results, error=MetadataResourceNotFoundError("missing"))

    response = _client(lambda: reader).get("/v2/variables?country_id=us")

    assert response.status_code == 404
    assert "origin" not in _vary_values(response)


def test_openapi_declares_caching_headers_and_not_modified_responses() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()
    metadata_paths = [
        path
        for path in schema["paths"]
        if path.startswith(
            (
                "/v2/datasets",
                "/v2/economy-options",
                "/v2/model-catalog",
                "/v2/parameter",
                "/v2/regions",
                "/v2/tax-benefit-model",
                "/v2/variables",
            )
        )
    ]

    assert len(metadata_paths) == 21
    for path in metadata_paths:
        responses = schema["paths"][path]["get"]["responses"]
        assert set(responses["200"]["headers"]) == {"ETag", "Cache-Control", "Vary"}
        assert "$ref" in responses["200"]["content"]["application/json"]["schema"]
        assert set(responses["304"]["headers"]) == {"ETag", "Cache-Control", "Vary"}
        assert "content" not in responses["304"]
        if path == "/v2/tax-benefit-models/by-country/{country_id}":
            assert "path" in responses["400"]["description"]
        else:
            # Query parameters are validated first (422), so only a country
            # given in the path can return 400.
            assert "400" not in responses, path


def _vary_value_counts(response) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in response.headers.get("vary", "").split(","):
        if value.strip():
            counts[value.strip().lower()] = counts.get(value.strip().lower(), 0) + 1
    return counts


@pytest.mark.parametrize("origin", [None, "https://app.policyengine.org"])
def test_cacheable_responses_and_their_304_carry_the_same_vary_once_each(
    origin: str | None,
) -> None:
    # Through the whole middleware stack (gzip, then CORS): a 304 must carry
    # the Vary its 200 would, and each value appears once.
    results, _ids = _resource_results()
    client = _client(lambda: ResourceReader(results))
    headers = {"Accept-Encoding": "gzip"}
    if origin is not None:
        headers["Origin"] = origin

    small = client.get("/v2/tax-benefit-models?country_id=us", headers=headers)
    compressed = client.get("/v2/model-catalog?country_id=us", headers=headers)
    not_modified = client.get(
        "/v2/model-catalog?country_id=us",
        headers={**headers, "If-None-Match": compressed.headers["etag"]},
    )

    assert compressed.headers.get("content-encoding") == "gzip"
    assert not_modified.status_code == 304
    expected = {"origin": 1, "accept-encoding": 1}
    assert _vary_value_counts(small) == expected
    assert _vary_value_counts(compressed) == expected
    assert _vary_value_counts(not_modified) == expected


def test_openapi_declares_each_variables_unit_and_definition_period() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()

    variable_properties = schema["components"]["schemas"]["MetadataVariable"][
        "properties"
    ]
    for field in ("unit", "definition_period"):
        assert {"type": "string"} in variable_properties[field]["anyOf"]
        assert {"type": "null"} in variable_properties[field]["anyOf"]


def test_openapi_requires_every_catalog_format_2_field_as_nullable() -> None:
    # Every response includes these fields (null for versions published before
    # catalog format 2), so a generated client must not type them as missing.
    results, _ids = _resource_results()
    schemas = (
        _client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()["components"]["schemas"]
    )
    format_2_fields = {
        "MetadataVariable": {
            "is_input_variable",
            "hidden_input",
            "module_name",
            "adds_parameter_path",
            "subtracts_parameter_path",
            "enum_values",
            "unit",
            "definition_period",
        },
        "MetadataParameterSummary": {"economy", "household"},
        "MetadataCatalogParameter": {"economy", "household"},
    }

    for schema_name, fields in format_2_fields.items():
        schema = schemas[schema_name]
        assert set(schema["properties"]) <= set(schema["required"]), schema_name
        for field in fields:
            assert {"type": "null"} in schema["properties"][field]["anyOf"], field


def test_parameter_children_route_forwards_its_level_and_page() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameters/children",
        params={
            "country_id": "UK",
            "policyengine_version": "4.19.0",
            "parent_path": "gov.hmrc.income_tax.rates.uk",
            "reform_changeable": "true",
            "offset": 10,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_children",
            ("uk", "4.19.0"),
            {
                "level": ParameterTreeLevel(
                    parent_path="gov.hmrc.income_tax.rates.uk",
                    reform_changeable=True,
                ),
                "offset": 10,
                "limit": 20,
            },
        )
    ]


def test_parameter_children_route_defaults_to_the_full_top_level() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameters/children", params={"country_id": "us"}
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_children",
            ("us", None),
            {"level": ParameterTreeLevel(), "offset": 0, "limit": 100},
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&parentpath=gov",
        "country_id=us&parent_path=gov&parent_path=gov.irs",
        "country_id=us&reform_changeable=yes-please",
        "country_id=us&limit=501",
        "country_id=ca",
        "parent_path=gov",
        "country_id=us&parent_path=" + "x" * 513,
    ],
)
def test_parameter_children_route_rejects_invalid_queries(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = _resource_results()
        return ResourceReader(results)

    response = _client(factory).get(f"/v2/parameters/children?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert calls == []


def test_parameter_children_route_reports_an_unwritten_tree_as_unavailable() -> None:
    results, _ids = _resource_results()
    message = (
        "catalog version 6.7.5 has no parameter tree: a tree is written when a "
        "catalog version is published, and this version was published before"
    )
    reader = ResourceReader(results, error=ParameterTreeUnavailableError(message))

    response = _client(lambda: reader).get(
        "/v2/parameters/children", params={"country_id": "us"}
    )

    assert response.status_code == 503
    assert response.json() == {"status": "error", "message": message}


def test_parameter_children_openapi_declares_the_query_contract() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()

    parameters = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/v2/parameters/children"]["get"]["parameters"]
    }

    assert set(parameters) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "parent_path",
        "reform_changeable",
    }
    assert parameters["country_id"]["required"] is True
    assert parameters["parent_path"]["schema"]["default"] == ""
    assert parameters["parent_path"]["schema"]["maxLength"] == 512
    assert parameters["reform_changeable"]["schema"]["type"] == "boolean"
    assert parameters["reform_changeable"]["schema"]["default"] is False
    assert parameters["limit"]["schema"]["maximum"] == 500
    description = schema["paths"]["/v2/parameters/children"]["get"]["description"]
    assert "422" in description
    assert "malformed policyengine_version" in description
    assert "503" in description


def test_parameter_children_openapi_declares_exactly_its_error_responses() -> None:
    results, _ids = _resource_results()
    schema = _client(lambda: ResourceReader(results)).get("/v2/openapi.json").json()
    responses = schema["paths"]["/v2/parameters/children"]["get"]["responses"]
    parameter_responses = schema["paths"]["/v2/parameters"]["get"]["responses"]

    assert set(responses) == {"200", "304", "404", "405", "422", "500", "503"}
    assert "PolicyEngine.py version" in responses["422"]["description"]
    assert "parameter tree" in responses["503"]["description"]
    assert "parameter tree" not in parameter_responses["503"]["description"]
