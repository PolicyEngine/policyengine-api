"""The process-wide store of whole catalog-version response bodies."""

from __future__ import annotations

import threading
import time

import pytest
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    MetadataResponseCache,
)


def _counting_build(body: bytes, builds: list[str]):
    def build() -> bytes:
        builds.append("built")
        return body

    return build


def test_a_body_is_built_once_per_key_and_reused() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []
    key = ("variables", "us", "6.10.0")

    first = cache.get_or_build(key, _counting_build(b'{"a":1}', builds))
    second = cache.get_or_build(key, _counting_build(b'{"b":2}', builds))

    assert first == b'{"a":1}'
    assert second == b'{"a":1}'
    assert builds == ["built"]


def test_different_routes_countries_and_versions_are_kept_apart() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []

    for key in (
        ("variables", "us", "6.10.0"),
        ("variables", "uk", "6.10.0"),
        ("variables", "us", None),
        ("model-catalog", "us", "6.10.0"),
    ):
        cache.get_or_build(key, _counting_build(repr(key).encode(), builds))

    assert len(builds) == 4


def test_a_failed_read_is_returned_but_not_kept() -> None:
    cache = MetadataResponseCache()
    failure = JSONResponse({"status": "error"}, status_code=503)
    builds: list[str] = []

    def failing_build() -> JSONResponse:
        builds.append("failed")
        return failure

    first = cache.get_or_build(("variables", "us", None), failing_build)
    second = cache.get_or_build(
        ("variables", "us", None), _counting_build(b"{}", builds)
    )

    assert first is failure
    assert second == b"{}"
    assert builds == ["failed", "built"]


def test_the_least_recently_used_body_is_dropped_beyond_capacity() -> None:
    cache = MetadataResponseCache(capacity=2)
    builds: list[str] = []
    oldest, middle, newest = (("variables", country, None) for country in "abc")

    cache.get_or_build(oldest, _counting_build(b"1", builds))
    cache.get_or_build(middle, _counting_build(b"2", builds))
    cache.get_or_build(oldest, _counting_build(b"1", builds))
    cache.get_or_build(newest, _counting_build(b"3", builds))
    cache.get_or_build(oldest, _counting_build(b"1", builds))
    cache.get_or_build(middle, _counting_build(b"2", builds))

    assert builds == ["built", "built", "built", "built"]


def test_concurrent_requests_for_one_key_build_it_once() -> None:
    cache = MetadataResponseCache()
    builds: list[str] = []
    started = threading.Barrier(4)

    def slow_build() -> bytes:
        builds.append("built")
        time.sleep(0.05)
        return b"{}"

    def request() -> None:
        started.wait()
        cache.get_or_build(("variables", "us", None), slow_build)

    threads = [threading.Thread(target=request) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert builds == ["built"]


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        MetadataResponseCache(capacity=0)
