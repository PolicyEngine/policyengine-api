"""HTTP answers for a catalog version whose current-law values pruning removed.

Every route that serves current-law parameter values, parameter tree rows or
the parameter search file answers 404 with ``Cache-Control: no-store`` and the
service's message, so no cache keeps the answer after the version is installed
again and its values return. The request names data the catalog no longer
holds, so the answer is a client error: a 503 would be counted as a server
error by the daily telemetry error report (issue #4243). When the pruned
version is the one the process runs, which a request without
``policyengine_version`` selects, the service is at fault, so it answers 503
with the same message and header. An unavailable catalog still answers 503.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.fastapi_routes.v2.metadata.response_cache_support import (
    MetadataResponseCache,
)
from policyengine_api.services.v2.metadata.validators import (
    CatalogValuesPrunedError,
)
from tests.fixtures.v2_metadata_routes import ResourceReader, metadata_route_client

PRUNED_VERSION = "5.0.1"
PRUNED_MESSAGE = (
    f"PolicyEngine.py {PRUNED_VERSION}'s current-law parameter values for us were "
    "removed from the catalog, with its parameter tree and search file; they "
    f"return when PolicyEngine.py {PRUNED_VERSION} is installed again"
)
VERSION_QUERY = f"country_id=us&policyengine_version={PRUNED_VERSION}"
# A fixed value, so every collection gives the parametrized test the same ID.
PRUNED_VALUE_ID = UUID("6f1d5c2e-3b8a-4e7f-9a40-1c2d3e4f5a6b")

# Each route that serves data pruning removes, and the reader method it calls.
PRUNED_DATA_ROUTES = [
    (f"/v2/parameter-values?{VERSION_QUERY}", "list_parameter_values"),
    (f"/v2/parameter-values/{PRUNED_VALUE_ID}?{VERSION_QUERY}", "get_parameter_value"),
    (f"/v2/parameters/children?{VERSION_QUERY}", "list_parameter_children"),
    (f"/v2/parameters/search-file?{VERSION_QUERY}", "get_parameter_search_file"),
    (f"/v2/model-catalog/variables?{VERSION_QUERY}", "get_catalog_variables"),
    (
        f"/v2/model-catalog/parameters?{VERSION_QUERY}&name=gov.example.rate",
        "get_catalog_parameters",
    ),
]


def _pruned_reader(method_name: str) -> ResourceReader:
    return ResourceReader(
        {method_name: None}, error=CatalogValuesPrunedError(PRUNED_MESSAGE)
    )


def _assert_pruned_answer(response) -> None:
    assert response.status_code == 404
    assert response.json() == {"status": "error", "message": PRUNED_MESSAGE}
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers


@pytest.mark.parametrize(("path", "method_name"), PRUNED_DATA_ROUTES)
def test_routes_serving_pruned_data_answer_404_that_no_cache_keeps(
    path: str,
    method_name: str,
) -> None:
    reader = _pruned_reader(method_name)

    response = metadata_route_client(lambda: reader).get(path)

    _assert_pruned_answer(response)
    assert [call[0] for call in reader.calls] == [method_name]
    assert reader.closed


def test_revalidating_a_pruned_version_search_file_answers_404_too() -> None:
    reader = _pruned_reader("get_parameter_search_file_hash")

    response = metadata_route_client(lambda: reader).get(
        f"/v2/parameters/search-file?{VERSION_QUERY}",
        headers={"If-None-Match": '"0123"', "Accept-Encoding": "gzip"},
    )

    _assert_pruned_answer(response)
    assert [call[0] for call in reader.calls] == ["get_parameter_search_file_hash"]


def test_a_kept_whole_version_response_cache_does_not_keep_the_pruned_answer() -> None:
    readers: list[ResourceReader] = []

    def factory() -> ResourceReader:
        readers.append(_pruned_reader("get_catalog_variables"))
        return readers[-1]

    client = metadata_route_client(factory, response_cache=MetadataResponseCache())
    path = f"/v2/model-catalog/variables?{VERSION_QUERY}"

    first = client.get(path)
    second = client.get(path)

    _assert_pruned_answer(first)
    _assert_pruned_answer(second)
    # The failure was not kept: the second request read again.
    assert len(readers) == 2


@pytest.mark.parametrize(("path", "method_name"), PRUNED_DATA_ROUTES)
def test_routes_serving_pruned_data_answer_503_when_the_running_version_is_pruned(
    path: str,
    method_name: str,
) -> None:
    reader = ResourceReader(
        {method_name: None},
        error=CatalogValuesPrunedError(PRUNED_MESSAGE, running_version=True),
    )

    response = metadata_route_client(lambda: reader).get(path)

    assert response.status_code == 503
    assert response.json() == {"status": "error", "message": PRUNED_MESSAGE}
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers


@pytest.mark.parametrize(("path", "method_name"), PRUNED_DATA_ROUTES)
def test_routes_serving_pruned_data_still_answer_503_when_the_catalog_is_unavailable(
    path: str,
    method_name: str,
) -> None:
    reader = ResourceReader(
        {method_name: None},
        error=MetadataCatalogUnavailableError("catalog connection refused"),
    )

    response = metadata_route_client(lambda: reader).get(path)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 metadata catalog is unavailable",
    }
    assert "cache-control" not in response.headers


PRUNED_DATA_PATHS = (
    "/v2/parameter-values",
    "/v2/parameter-values/{value_id}",
    "/v2/parameters/children",
    "/v2/parameters/search-file",
    "/v2/model-catalog/variables",
    "/v2/model-catalog/parameters",
)


def test_openapi_describes_the_404_of_a_pruned_version() -> None:
    schema = (
        metadata_route_client(lambda: ResourceReader({})).get("/v2/openapi.json").json()
    )

    for path in PRUNED_DATA_PATHS:
        responses = schema["paths"][path]["get"]["responses"]
        not_found = responses["404"]["description"]
        assert "pruned" in not_found, path
        assert "no-store" in not_found, path
        assert responses["404"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/V2ErrorResponse"
        }, path
        unavailable = responses["503"]["description"]
        assert unavailable.startswith("The initialized v2 catalog is unavailable"), path
        assert "running PolicyEngine.py version" in unavailable, path
        assert "no-store" in unavailable, path
    for path in ("/v2/parameters", "/v2/variables"):
        responses = schema["paths"][path]["get"]["responses"]
        assert "pruned" not in responses["404"]["description"], path
        assert (
            "running PolicyEngine.py version" not in (responses["503"]["description"])
        ), path
