"""Entity tags, cache lifetimes, kept responses and Vary on v2 metadata routes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.fastapi_routes import dependencies as route_dependencies
from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    MetadataResponseCache,
)
from policyengine_api.services.v2.metadata.validators import (
    MetadataResourceNotFoundError,
)
from tests.fixtures.v2_metadata_routes import (
    ResourceReader,
    every_resource_path,
    metadata_route_client,
    resource_results,
    vary_values,
)


def test_every_resource_route_serves_an_entity_tag_and_cache_lifetime() -> None:
    results, ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))

    for path in every_resource_path(ids):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "public, max-age=300", path
        assert response.headers["etag"].startswith('"'), path
        assert response.headers["etag"].endswith('"'), path


def test_a_named_catalog_version_is_reusable_for_a_day() -> None:
    results, _ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))
    query = {"country_id": "us", "policyengine_version": "4.20.3"}

    first = client.get("/v2/variables", params=query)
    second = client.get("/v2/variables", params=query)

    assert first.headers["cache-control"] == "public, max-age=86400"
    assert first.headers["etag"] == second.headers["etag"]


def test_a_matching_entity_tag_gets_a_not_modified_response_without_a_body() -> None:
    results, _ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))
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
    results, _ids = resource_results()
    changed_results, _changed_ids = resource_results()

    first = metadata_route_client(lambda: ResourceReader(results)).get(
        "/v2/variables?country_id=us"
    )
    changed = metadata_route_client(lambda: ResourceReader(changed_results)).get(
        "/v2/variables?country_id=us"
    )

    assert first.headers["etag"] != changed.headers["etag"]


def test_failed_reads_carry_no_cache_headers() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results, error=MetadataResourceNotFoundError("missing"))

    response = metadata_route_client(lambda: reader).get(
        "/v2/variables?country_id=us&policyengine_version=4.20.3"
    )

    assert response.status_code == 404
    assert "etag" not in response.headers
    assert "cache-control" not in response.headers


def test_whole_version_responses_are_read_once_per_process_and_version() -> None:
    results, _ids = resource_results()
    readers: list[ResourceReader] = []

    def factory() -> ResourceReader:
        readers.append(ResourceReader(results))
        return readers[-1]

    client = metadata_route_client(factory, response_cache=MetadataResponseCache())
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
    results, _ids = resource_results()
    readers = [
        ResourceReader(results, error=MetadataCatalogUnavailableError("down")),
        ResourceReader(results),
    ]
    client = metadata_route_client(
        lambda: readers.pop(0), response_cache=MetadataResponseCache()
    )

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
    results, _ids = resource_results()

    response = metadata_route_client(lambda: ResourceReader(results)).get(
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
    results, _ids = resource_results()
    client = metadata_route_client(
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


def test_browser_scripts_can_read_a_metadata_response_entity_tag() -> None:
    results, _ids = resource_results()

    response = metadata_route_client(lambda: ResourceReader(results)).get(
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
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/parameter-values?country_id=us&policyengine_version=4.20.3&current=true"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0"
    _name, _args, kwargs = reader.calls[0]
    assert kwargs["value_filter"].now == read_instant


@pytest.mark.parametrize("origin", [None, "https://app.policyengine.org"])
def test_cacheable_metadata_responses_vary_by_origin(origin: str | None) -> None:
    # The API reflects any origin, so a shared cache must not reuse a response
    # stored for a request without Origin (no Access-Control-Allow-Origin) for
    # a cross-origin one, or the reverse.
    results, _ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))
    headers = {} if origin is None else {"Origin": origin}

    small = client.get("/v2/tax-benefit-models?country_id=us", headers=headers)
    large = client.get("/v2/model-catalog?country_id=us", headers=headers)
    revalidated = client.get(
        "/v2/model-catalog?country_id=us",
        headers={**headers, "If-None-Match": large.headers["etag"]},
    )

    assert revalidated.status_code == 304
    for response in (small, large, revalidated):
        assert "origin" in vary_values(response)
    assert "accept-encoding" in vary_values(large)


def test_failed_metadata_reads_do_not_add_vary_by_origin() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results, error=MetadataResourceNotFoundError("missing"))

    response = metadata_route_client(lambda: reader).get("/v2/variables?country_id=us")

    assert response.status_code == 404
    assert "origin" not in vary_values(response)


def test_openapi_declares_caching_headers_and_not_modified_responses() -> None:
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
    results, _ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))
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
