"""The process-wide store of whole catalog-version responses."""

from __future__ import annotations

import threading

import pytest
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    BuiltResponse,
    KeptResponse,
    MetadataResponseCache,
    body_entity_tag,
)

RUNNING_VERSION = "6.10.0"


def _counting_build(
    builds: list[str], *, body: bytes = b'{"a":1}', version: str = RUNNING_VERSION
):
    def build() -> BuiltResponse:
        builds.append("built")
        return BuiltResponse(body=body, policyengine_version=version)

    return build


def test_a_response_is_built_once_and_kept_with_its_entity_tag() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []

    first = cache.get_or_build(
        "variables", "us", RUNNING_VERSION, _counting_build(builds)
    )
    second = cache.get_or_build(
        "variables", "us", RUNNING_VERSION, _counting_build(builds, body=b"{}")
    )

    assert first == KeptResponse(
        body=b'{"a":1}', entity_tag=body_entity_tag(b'{"a":1}')
    )
    assert second is first
    assert builds == ["built"]


@pytest.mark.parametrize("requested_first", [None, RUNNING_VERSION])
def test_the_running_version_and_its_number_share_one_kept_response(
    requested_first: str | None,
) -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []
    requested_second = RUNNING_VERSION if requested_first is None else None

    first = cache.get_or_build(
        "variables", "us", requested_first, _counting_build(builds)
    )
    second = cache.get_or_build(
        "variables", "us", requested_second, _counting_build(builds)
    )
    third = cache.get_or_build(
        "variables", "us", requested_second, _counting_build(builds)
    )

    assert second is first
    assert third is first
    assert builds == (["built"] if requested_first is None else ["built", "built"])


def test_different_routes_countries_and_versions_are_kept_apart() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []

    for route, country_id, version in (
        ("variables", "us", "6.10.0"),
        ("variables", "uk", "6.10.0"),
        ("variables", "us", "6.9.0"),
        ("model-catalog", "us", "6.10.0"),
    ):
        cache.get_or_build(
            route, country_id, version, _counting_build(builds, version=version)
        )

    assert len(builds) == 4


def test_a_failed_read_is_returned_but_not_kept() -> None:
    cache = MetadataResponseCache()
    failure = JSONResponse({"status": "error"}, status_code=503)
    builds: list[str] = []

    def failing_build() -> JSONResponse:
        builds.append("failed")
        return failure

    first = cache.get_or_build("variables", "us", None, failing_build)
    second = cache.get_or_build("variables", "us", None, _counting_build(builds))

    assert first is failure
    assert isinstance(second, KeptResponse)
    assert builds == ["failed", "built"]


def test_the_least_recently_used_response_is_dropped_beyond_capacity() -> None:
    cache = MetadataResponseCache(capacity=2)
    builds: list[str] = []

    def get(country_id: str) -> None:
        cache.get_or_build("variables", country_id, "6.10.0", _counting_build(builds))

    for country_id in ("a", "b", "a", "c", "a", "b"):
        get(country_id)

    assert builds == ["built", "built", "built", "built"]


def test_concurrent_requests_for_one_response_build_it_once() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []
    building = threading.Event()
    release = threading.Event()

    def blocked_build() -> BuiltResponse:
        builds.append("built")
        building.set()
        release.wait()
        return BuiltResponse(body=b"{}", policyengine_version=RUNNING_VERSION)

    def request() -> None:
        cache.get_or_build("variables", "us", None, blocked_build)

    first = threading.Thread(target=request)
    first.start()
    building.wait()
    others = [threading.Thread(target=request) for _ in range(3)]
    for thread in others:
        thread.start()
    release.set()
    for thread in [first, *others]:
        thread.join()

    # Whether the others waited on the build or arrived after it, none read.
    assert builds == ["built"]


def test_a_request_arriving_while_a_response_is_stored_waits_for_it() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []
    second_results: list[object] = []
    second_requests: list[threading.Thread] = []
    original_keep = cache._keep

    def keep_after_another_request_arrives(*keep_arguments: object) -> KeptResponse:
        second_request = threading.Thread(
            target=lambda: second_results.append(
                cache.get_or_build("variables", "us", None, _counting_build(builds))
            )
        )
        second_requests.append(second_request)
        second_request.start()
        # The second request may not build while this one stores its result:
        # it waits on the build, whatever the timing.
        second_request.join(timeout=0.2)
        return original_keep(*keep_arguments)

    cache._keep = keep_after_another_request_arrives  # type: ignore[method-assign]

    first = cache.get_or_build("variables", "us", None, _counting_build(builds))
    second_requests[0].join()

    assert builds == ["built"]
    assert second_results == [first]


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        MetadataResponseCache(capacity=0)
