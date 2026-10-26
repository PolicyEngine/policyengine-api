"""Route coverage for the parameter search file at /v2/parameters/search-file."""

from __future__ import annotations

import gzip
from datetime import date
from typing import get_type_hints

import pytest

from policyengine_api.data.v2.catalog.parameter_search_file import (
    EditabilityChange,
    EditabilityChangeEntry,
    ParameterSearchFileDocument,
    SearchFileLabelEntry,
    SearchFileNodeEntry,
    SearchFileParameterEntry,
    SearchParameterSource,
    build_parameter_search_file,
    encode_parameter_search_file,
)
from policyengine_api.data.v2.catalog.parameter_tree import TreeNodeSource
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataParameterSearchFileContent,
    MetadataParameterSearchFileEditabilityChange,
    MetadataParameterSearchFileLabel,
    MetadataParameterSearchFileNode,
    MetadataParameterSearchFileParameter,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataParameterSearchFile,
)
from policyengine_api.services.v2.metadata.validators import (
    ParameterSearchFileUnavailableError,
)
from tests.fixtures.v2_metadata_routes import ResourceReader, metadata_route_client

SEARCH_FILE_PATH = "/v2/parameters/search-file"


SEARCH_FILE_CONTENT: ParameterSearchFileDocument = {
    "format": 1,
    "country_id": "us",
    "policyengine_version": "4.20.3",
    "parameters": [
        {
            "path": "gov.example.rate",
            "label": "Rate",
            "unit": "/1",
            "description": None,
            "editable": True,
        }
    ],
    "other_parameters": [],
    "nodes": [{"path": "gov.example", "label": "Example"}],
}


def _search_file_reader(*, error: Exception | None = None) -> ResourceReader:
    encoded = encode_parameter_search_file(SEARCH_FILE_CONTENT)
    stored = MetadataParameterSearchFile(
        policyengine_version="4.20.3",
        file_format=1,
        compressed_content=encoded.compressed_content,
        content_sha256=encoded.content_sha256,
        uncompressed_size=encoded.uncompressed_size,
        compressed_size=encoded.compressed_size,
    )
    return ResourceReader({"get_parameter_search_file": stored}, error=error)


def _content_sha256() -> str:
    return encode_parameter_search_file(SEARCH_FILE_CONTENT).content_sha256


def test_search_file_route_sends_the_stored_gzip_bytes_to_a_gzip_client() -> None:
    reader = _search_file_reader()

    response = metadata_route_client(lambda: reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "US", "policyengine_version": "4.20.3"},
        headers={"Accept-Encoding": "gzip, deflate"},
    )

    encoded = encode_parameter_search_file(SEARCH_FILE_CONTENT)
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-length"] == str(encoded.compressed_size)
    assert response.headers["content-type"] == "application/json"
    assert response.headers["etag"] == f'"{encoded.content_sha256}-gzip"'
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.headers["vary"] == "Origin, Accept-Encoding"
    assert response.json() == SEARCH_FILE_CONTENT
    assert reader.calls == [("get_parameter_search_file", ("us", "4.20.3"), {})]
    assert reader.closed


def test_search_file_route_sends_uncompressed_json_to_other_clients() -> None:
    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us", "policyengine_version": "4.20.3"},
        headers={"Accept-Encoding": "identity"},
    )

    encoded = encode_parameter_search_file(SEARCH_FILE_CONTENT)
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.content == gzip.decompress(encoded.compressed_content)
    assert response.headers["etag"] == f'"{encoded.content_sha256}"'


def test_a_large_uncompressed_search_file_names_accept_encoding_once_in_vary() -> None:
    content = {
        **SEARCH_FILE_CONTENT,
        "parameters": [
            {
                "path": f"gov.example.rate_{index}",
                "label": f"Rate {index}",
                "unit": "/1",
                "description": None,
                "editable": True,
            }
            for index in range(200)
        ],
    }
    encoded = encode_parameter_search_file(content)
    stored = MetadataParameterSearchFile(
        policyengine_version="4.20.3",
        file_format=1,
        compressed_content=encoded.compressed_content,
        content_sha256=encoded.content_sha256,
        uncompressed_size=encoded.uncompressed_size,
        compressed_size=encoded.compressed_size,
    )

    response = metadata_route_client(
        lambda: ResourceReader({"get_parameter_search_file": stored})
    ).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us"},
        headers={"Accept-Encoding": "identity"},
    )

    assert encoded.uncompressed_size > 1000
    assert response.status_code == 200
    assert response.headers["vary"] == "Origin, Accept-Encoding"
    assert response.json() == content


@pytest.mark.parametrize("accept_encoding", ["gzip;q=0", "br, gzip;q=0.0"])
def test_search_file_route_respects_a_refused_gzip_encoding(
    accept_encoding: str,
) -> None:
    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us"},
        headers={"Accept-Encoding": accept_encoding},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["etag"] == f'"{_content_sha256()}"'


def test_search_file_route_lets_the_running_version_be_cached_briefly() -> None:
    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH, params={"country_id": "us"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"


@pytest.mark.parametrize(
    ("if_none_match", "accept_encoding", "expected_etag_suffix"),
    [
        ('"{sha}-gzip"', "gzip", "-gzip"),
        ('W/"{sha}-gzip"', "gzip", "-gzip"),
        ('"other", "{sha}"', "identity", ""),
        ("*", "identity", ""),
    ],
)
def test_search_file_route_answers_a_matching_revalidation_with_304(
    if_none_match: str,
    accept_encoding: str,
    expected_etag_suffix: str,
) -> None:
    sha = _content_sha256()

    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us", "policyengine_version": "4.20.3"},
        headers={
            "If-None-Match": if_none_match.format(sha=sha),
            "Accept-Encoding": accept_encoding,
        },
    )

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == f'"{sha}{expected_etag_suffix}"'
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.headers["vary"] == "Origin, Accept-Encoding"
    assert "content-encoding" not in response.headers


def test_a_tag_of_the_other_representation_does_not_revalidate() -> None:
    # Strong tags differ by encoding, so a client switching to gzip refetches.
    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us"},
        headers={"If-None-Match": f'"{_content_sha256()}"', "Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{_content_sha256()}-gzip"'


def test_search_file_route_sends_the_file_when_the_etag_differs() -> None:
    response = metadata_route_client(_search_file_reader).get(
        SEARCH_FILE_PATH,
        params={"country_id": "us"},
        headers={"If-None-Match": '"0000"', "Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.json() == SEARCH_FILE_CONTENT


def test_search_file_route_reports_a_missing_file_as_unavailable() -> None:
    reader = _search_file_reader(
        error=ParameterSearchFileUnavailableError("search file not written")
    )

    response = metadata_route_client(lambda: reader).get(
        SEARCH_FILE_PATH, params={"country_id": "us"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 metadata catalog is unavailable",
    }
    assert "etag" not in response.headers
    assert "cache-control" not in response.headers
    assert reader.closed


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&format=1",
        "country_id=us&country_id=uk",
        "country_id=ca",
        "",
        "country_id=us&policyengine_version=4.20.3&policyengine_version=4.20.4",
    ],
)
def test_search_file_route_rejects_invalid_queries(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        return _search_file_reader()

    response = metadata_route_client(factory).get(f"{SEARCH_FILE_PATH}?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert calls == []


def test_search_file_openapi_declares_its_query_and_content() -> None:
    schema = metadata_route_client(_search_file_reader).get("/v2/openapi.json").json()

    operation = schema["paths"][SEARCH_FILE_PATH]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"country_id", "policyengine_version"}
    assert parameters["country_id"]["required"] is True
    assert parameters["policyengine_version"]["required"] is False
    ok = operation["responses"]["200"]
    assert ok["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MetadataParameterSearchFileContent"
    }
    assert {"ETag", "Cache-Control", "Content-Encoding", "Vary"} <= set(ok["headers"])
    assert "304" in operation["responses"]
    assert "MetadataParameterSearchFileParameter" in schema["components"]["schemas"]


def test_the_built_search_file_matches_the_declared_content_schema() -> None:
    search_file = build_parameter_search_file(
        country_id="uk",
        policyengine_version="6.10.0",
        parameters=[
            SearchParameterSource(
                name="gov.hmrc.stamp_duty.rate[1].rate",
                label=None,
                unit="/1",
                description="A band's rate.",
                economy=True,
                household=True,
            ),
            SearchParameterSource(
                name="gov.economic_assumptions.cpi",
                label="CPI",
                unit=None,
                description=None,
                economy=False,
                household=False,
            ),
        ],
        nodes=[TreeNodeSource(name="gov.hmrc", label="HMRC")],
        editability=[
            EditabilityChange(
                "gov.hmrc.stamp_duty.rate[1].rate", date(2015, 1, 1), editable=True
            ),
            EditabilityChange(
                "gov.hmrc.stamp_duty.rate[1].rate", date(2020, 7, 8), editable=False
            ),
        ],
    )

    content = MetadataParameterSearchFileContent.model_validate(search_file)

    assert content.model_dump(mode="json", exclude_unset=True) == search_file
    assert content.parameters[0].editable_changes is not None


def test_the_search_file_shapes_match_the_declared_content_models() -> None:
    """The builder's typed shapes and the OpenAPI models name the same fields."""
    pairs = (
        (ParameterSearchFileDocument, MetadataParameterSearchFileContent),
        (SearchFileParameterEntry, MetadataParameterSearchFileParameter),
        (EditabilityChangeEntry, MetadataParameterSearchFileEditabilityChange),
        (SearchFileLabelEntry, MetadataParameterSearchFileLabel),
        (SearchFileNodeEntry, MetadataParameterSearchFileNode),
    )
    for typed_shape, model in pairs:
        assert set(get_type_hints(typed_shape)) == set(model.model_fields), model
    assert SearchFileParameterEntry.__optional_keys__ == {"editable_changes"}
