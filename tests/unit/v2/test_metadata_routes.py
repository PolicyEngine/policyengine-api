"""Typed route coverage for dormant v2 metadata resources."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes import dependencies as route_dependencies
from policyengine_api.services.v2.metadata.selected_catalogs import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
)
from tests.fixtures.v2_metadata_routes import (
    ResourceReader,
    every_resource_path,
    metadata_route_client,
    resource_results,
)


def test_each_resource_route_returns_its_typed_result() -> None:
    results, ids = resource_results()
    reader = ResourceReader(results)
    client = metadata_route_client(lambda: reader)
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
    results, _ids = resource_results()
    reader = ResourceReader(results)
    response = metadata_route_client(lambda: reader).get(
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
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get("/v2/variables", params=params)

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
    results, _ids = resource_results()
    reader = ResourceReader(results, error=error)
    response = metadata_route_client(lambda: reader).get("/v2/variables?country_id=us")

    assert response.status_code == expected_status
    assert response.json()["status"] == "error"
    assert response.json()["message"]
    assert "private query detail" not in response.text
    assert reader.closed


def test_unknown_resources_and_unsupported_methods_use_error_schema() -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = resource_results()
        return ResourceReader(results)

    client = metadata_route_client(factory)
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
    results, _ids = resource_results()
    reader = ResourceReader(results, close_error=RuntimeError("close failed"))
    monkeypatch.setattr(
        route_dependencies,
        "_default_v2_metadata_reader_factory",
        lambda: reader,
    )

    response = metadata_route_client(None).get("/v2/variables?country_id=us")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert reader.closed


def test_resource_reads_do_not_change_v1_metadata_routing() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)
    client = metadata_route_client(lambda: reader)

    first = client.get("/v2/variables?country_id=us")
    second = client.get("/v2/variables?country_id=us")
    v1 = client.get("/us/metadata")

    assert first.json() == second.json()
    assert v1.json()["result"] == {"source": "v1", "country_id": "us"}


def test_resource_route_logging_records_the_country_query_parameter() -> None:
    results, _ids = resource_results()

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = metadata_route_client(lambda: ResourceReader(results)).get(
            "/v2/variables?country_id=uk"
        )

    assert response.status_code == 200
    payload = mock_logger.log_struct.call_args.args[0]
    assert payload["country_id"] == "uk"
    assert payload["migration"]["route_group"] == "metadata"
    assert payload["migration"]["db_read"] == "supabase"


def test_openapi_references_explicit_resource_response_schemas() -> None:
    results, _ids = resource_results()
    response = metadata_route_client(lambda: ResourceReader(results)).get(
        "/v2/openapi.json"
    )

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
        "/v2/parameters/search-file",
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
        "/v2/countries",
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


def test_model_catalog_route_serves_the_small_parts_of_the_selected_version() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(f"/v2/model-catalog?{query}")

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert calls == []


def test_model_catalog_route_declares_its_query_in_openapi() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )

    operation = schema["paths"]["/v2/model-catalog"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"country_id", "policyengine_version"}
    assert parameters["country_id"]["required"] is True
    assert parameters["policyengine_version"]["required"] is False
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success == {"$ref": "#/components/schemas/MetadataModelCatalogResponse"}


def test_catalog_variables_route_serves_every_variable_and_part_values() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
    results, _ids = resource_results()
    response = metadata_route_client(lambda: ResourceReader(results)).get(
        f"/v2/model-catalog/variables?{query}"
    )

    assert response.status_code == 422


def test_catalog_parameters_route_fetches_several_parameters_by_name() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(
        f"/v2/model-catalog/parameters?{query}"
    )

    assert response.status_code == 422
    assert calls == []


def test_catalog_parameters_route_declares_a_repeated_name_in_openapi() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )

    operation = schema["paths"]["/v2/model-catalog/parameters"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"country_id", "policyengine_version", "name"}
    assert parameters["name"]["required"] is True
    name_schema = parameters["name"]["schema"]
    assert name_schema["type"] == "array"
    assert name_schema["minItems"] == 1
    assert name_schema["maxItems"] == 100


def test_parameter_collection_fetches_several_parameters_by_name() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)
    client = metadata_route_client(lambda: reader)

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
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
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
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(path)

    assert response.status_code == 422
    assert calls == []


def test_parameter_collections_declare_their_name_filters_in_openapi() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )

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
    _results, ids = resource_results()
    calls = []

    def factory():
        calls.append("called")
        results, _ids = resource_results()
        return ResourceReader(results)

    client = metadata_route_client(factory)
    for path in every_resource_path(ids):
        for rejected in _query_rejections(path):
            response = client.get(rejected)
            assert response.status_code == 422, (rejected, response.text)
            assert response.json() == {
                "status": "error",
                "message": "Invalid API v2 request",
            }
    assert calls == []


def test_every_metadata_route_declares_the_shared_catalog_query() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )
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

    assert len(metadata_paths) == 22
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


def test_openapi_declares_each_variables_unit_and_definition_period() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )

    variable_properties = schema["components"]["schemas"]["MetadataVariable"][
        "properties"
    ]
    for field in ("unit", "definition_period"):
        assert {"type": "string"} in variable_properties[field]["anyOf"]
        assert {"type": "null"} in variable_properties[field]["anyOf"]


def test_openapi_requires_every_catalog_format_2_field_as_nullable() -> None:
    # Every response includes these fields (null for versions published before
    # catalog format 2), so a generated client must not type them as missing.
    results, _ids = resource_results()
    schemas = (
        metadata_route_client(lambda: ResourceReader(results))
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
