"""Execute API v2 metadata reads and translate failures to HTTP responses."""

from __future__ import annotations

import contextlib
import hashlib
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import Response
from starlette.status import HTTP_200_OK

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    v2_error_response,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from fastapi import Request
    from starlette.responses import JSONResponse

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2MetadataResourceReader,
    )
    from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
        ResponseKey,
    )

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The resource request or PolicyEngine.py version is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The requested catalog resource is absent.",
    },
    405: {
        "model": V2ErrorResponse,
        "description": "The dormant v2 metadata resources support GET only.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request parameters do not match the resource schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The resource query failed internally.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "The initialized v2 catalog is unavailable.",
    },
}


ResponseT = TypeVar("ResponseT", bound=BaseModel)
ReadT = TypeVar("ReadT")

EXPLICIT_VERSION_MAX_AGE_SECONDS = 86_400
"""How long a response for a named catalog version may be reused (a day).

A published catalog version never changes, so such a response stays valid
until its code's response format changes; the ETag lets a client revalidate
it cheaply after that.
"""
RUNNING_VERSION_MAX_AGE_SECONDS = 300
"""How long a response for the running catalog version may be reused.

Without ``policyengine_version`` the running PolicyEngine.py version answers,
and it changes whenever the API deploys a new one.
"""


class CacheableMetadataRoute(APIRoute):
    """A metadata route whose successful responses carry caching headers.

    See ``with_cache_headers``. Failures are served unchanged, without them.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap FastAPI's handler so a 200 response gains its caching headers."""
        handle = super().get_route_handler()

        async def handle_with_cache_headers(request: Request) -> Response:
            response = await handle(request)
            if response.status_code != HTTP_200_OK:
                return response
            return with_cache_headers(request, response)

        return handle_with_cache_headers


def with_cache_headers(request: Request, response: Response) -> Response:
    """Give a JSON response a strong ETag and a public cache lifetime.

    The ETag is a hash of the exact body, so it changes with any change to the
    content, including the catalog format. A request naming its catalog with
    ``policyengine_version`` may be reused for a day, one that takes the
    running version for five minutes. A request whose ``If-None-Match`` names
    the ETag gets a 304 with no body.
    """
    entity_tag = f'"{hashlib.sha256(response.body).hexdigest()[:32]}"'
    max_age = (
        EXPLICIT_VERSION_MAX_AGE_SECONDS
        if "policyengine_version" in request.query_params
        else RUNNING_VERSION_MAX_AGE_SECONDS
    )
    headers = {"Cache-Control": f"public, max-age={max_age}", "ETag": entity_tag}
    if _names_entity_tag(request.headers.get("if-none-match"), entity_tag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return response


def _names_entity_tag(if_none_match: str | None, entity_tag: str) -> bool:
    if if_none_match is None:
        return False
    candidates = {candidate.strip() for candidate in if_none_match.split(",")}
    return "*" in candidates or bool(
        {entity_tag, f"W/{entity_tag}"}.intersection(candidates)
    )


def read_resource(
    dependencies: NativeRouteDependencies,
    response_type: type[ResponseT],
    operation: Callable[[V2MetadataResourceReader], object],
) -> ResponseT | JSONResponse:
    """Run one metadata read and wrap its result in ``response_type``.

    Version, pagination and catalog failures become typed v2 error responses
    (400, 404 or 503, and 500 for anything unexpected), and the reader is
    closed whatever happens.
    """
    return run_metadata_read(
        dependencies, lambda reader: response_type(result=operation(reader))
    )


def read_whole_version_resource(
    dependencies: NativeRouteDependencies,
    key: ResponseKey,
    response_type: type[ResponseT],
    operation: Callable[[V2MetadataResourceReader], object],
) -> ResponseT | Response:
    """Serve a whole catalog-version response, built once per process when kept.

    With the dependencies' response cache, the serialized body for ``key`` is
    read and built only on the first successful request; failures are served
    as ``read_resource`` serves them and never kept. Without a cache this is
    ``read_resource``.
    """
    cache = dependencies.v2_metadata_response_cache
    if cache is None:
        return read_resource(dependencies, response_type, operation)

    def build() -> bytes | JSONResponse:
        result = read_resource(dependencies, response_type, operation)
        if isinstance(result, BaseModel):
            return result.model_dump_json().encode()
        return result

    built = cache.get_or_build(key, build)
    if isinstance(built, bytes):
        return Response(content=built, media_type="application/json")
    return built


def run_metadata_read(
    dependencies: NativeRouteDependencies,
    operation: Callable[[V2MetadataResourceReader], ReadT],
) -> ReadT | JSONResponse:
    """Run one metadata read and return its result unchanged.

    Failures become the typed v2 error responses described by read_resource,
    and the reader is closed whatever happens.
    """
    reader = None
    try:
        factory = dependencies.v2_metadata_reader_factory
        if factory is None:
            from policyengine_api.fastapi_routes.dependencies import (  # noqa: PLC0415  # looked up per request, so tests can replace the default factory
                _default_v2_metadata_reader_factory,
            )

            factory = _default_v2_metadata_reader_factory
        reader = factory()
        return operation(reader)
    except (InvalidMetadataPageError, InvalidPolicyEngineVersionError) as error:
        return v2_error_response(400, str(error))
    except UnsupportedPreviewCountryError as error:
        return v2_error_response(400, f"Unsupported country: {error}")
    except (
        MetadataCatalogVersionNotFoundError,
        MetadataResourceNotFoundError,
    ) as error:
        return v2_error_response(404, str(error))
    except (V2ConfigurationError, MetadataCatalogUnavailableError):
        return v2_error_response(503, "V2 metadata catalog is unavailable")
    except Exception:  # noqa: BLE001  # preview must return typed errors
        return v2_error_response(500, "V2 metadata query failed")
    finally:
        if reader is not None:
            # Best-effort close must not replace the typed response.
            with contextlib.suppress(Exception):
                reader.close()
