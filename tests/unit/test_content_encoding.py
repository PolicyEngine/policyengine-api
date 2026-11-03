"""Gzip negotiation that weighs Accept-Encoding qualities."""

from __future__ import annotations

import inspect

import pytest
from starlette.applications import Starlette
from starlette.middleware import gzip as starlette_gzip
from starlette.responses import StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from policyengine_api.content_encoding import NegotiatedGZipMiddleware, accepts_gzip

STREAMED_CHUNK = b"x" * 1_500


@pytest.mark.parametrize(
    ("accept_encoding", "accepted"),
    [
        ("gzip", True),
        ("GZIP", True),
        ("x-gzip", True),
        ("gzip;q=0.001", True),
        ("gzip;q=0", False),
        ("gzip;q=not-a-number", False),
        ("*", True),
        ("*;q=0", False),
        # An explicit gzip entry decides over the wildcard either way.
        ("*, gzip;q=0", False),
        ("*;q=0, gzip", True),
        ("br, deflate", False),
        ("gzipped", False),
        ("", False),
        (None, False),
    ],
)
def test_accepts_gzip_weighs_qualities_and_exact_coding_names(
    accept_encoding: str | None, *, accepted: bool
) -> None:
    assert accepts_gzip(accept_encoding) is accepted


async def _streamed(_request) -> StreamingResponse:
    async def chunks():
        for _ in range(3):
            yield STREAMED_CHUNK

    return StreamingResponse(chunks(), media_type="text/plain")


def _streaming_client() -> TestClient:
    application = Starlette(routes=[Route("/streamed", _streamed)])
    return TestClient(
        NegotiatedGZipMiddleware(application, minimum_size=1_000, compresslevel=4)
    )


def test_a_streamed_body_stays_uncompressed_when_gzip_is_refused() -> None:
    response = _streaming_client().get(
        "/streamed", headers={"Accept-Encoding": "gzip;q=0"}
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.content == STREAMED_CHUNK * 3


def test_a_streamed_body_is_gzipped_when_gzip_is_accepted() -> None:
    response = _streaming_client().get("/streamed", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.content == STREAMED_CHUNK * 3


def test_starlette_still_provides_the_responders_the_middleware_uses() -> None:
    """NegotiatedGZipMiddleware builds Starlette's undocumented responders.

    If a Starlette upgrade renames them or changes how they are built, this
    test names what changed.
    """
    identity_responder = getattr(starlette_gzip, "IdentityResponder", None)
    gzip_responder = getattr(starlette_gzip, "GZipResponder", None)
    assert identity_responder is not None, "starlette.middleware.gzip.IdentityResponder"
    assert gzip_responder is not None, "starlette.middleware.gzip.GZipResponder"
    assert list(inspect.signature(identity_responder).parameters) == [
        "app",
        "minimum_size",
    ]
    assert list(inspect.signature(gzip_responder).parameters) == [
        "app",
        "minimum_size",
        "compresslevel",
    ]
