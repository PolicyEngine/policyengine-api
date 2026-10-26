"""Execute API v2 metadata reads and translate failures to HTTP responses."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

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
from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    BuiltResponse,
    KeptResponse,
    body_entity_tag,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataResourceSuccessResponse,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    ParameterTreeUnavailableError,
)
from policyengine_api.vary_headers import unique_vary_values

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from fastapi import Request
    from starlette.responses import JSONResponse

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2MetadataResourceReader,
    )
    from policyengine_api.query_parameters import CatalogQuery

PATH_COUNTRY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": (
            "The country in the path is not supported. Query parameters are "
            "checked first: an invalid one, including the PolicyEngine.py "
            "version, returns 422."
        ),
    },
}
"""The extra response of the one metadata route that takes the country in its path."""

PARAMETER_TREE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    503: {
        "model": V2ErrorResponse,
        "description": (
            "The initialized v2 catalog is unavailable, or the catalog version "
            "has no parameter tree because it was published before the tree "
            "existed; the message then names the version."
        ),
    },
}
"""The parameter tree route's 503, which also covers a version without a tree."""

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
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
        "description": (
            "The query parameters do not match the resource schema, for example "
            "an unknown parameter or a malformed PolicyEngine.py version."
        ),
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


CACHE_HEADER_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "ETag": {
        "description": "Strong validator: a hash of the exact response body.",
        "schema": {"type": "string"},
    },
    "Cache-Control": {
        "description": (
            "public, with max-age 86400 when the request names "
            "policyengine_version and 300 otherwise; current parameter values "
            "expire at the next UTC midnight."
        ),
        "schema": {"type": "string"},
    },
    "Vary": {
        "description": (
            "Origin, Accept-Encoding: caches keep responses apart by origin "
            "and by compression; a 304 carries the same value."
        ),
        "schema": {"type": "string"},
    },
}

METADATA_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    200: {"headers": CACHE_HEADER_DESCRIPTIONS},
    304: {
        "description": (
            "Not modified: If-None-Match names the current ETag. No body is sent."
        ),
        "headers": CACHE_HEADER_DESCRIPTIONS,
    },
}
"""Every metadata route's documented responses, with its caching headers."""


class CatalogVersionResult(Protocol):
    """A whole-version result, which names the catalog version it was read from."""

    @property
    def policyengine_version(self) -> str:
        """The exact PolicyEngine.py version of the catalog read."""
        ...


ResponseT = TypeVar("ResponseT", bound=BaseModel)
ReadT = TypeVar("ReadT")
CatalogResultT = TypeVar("CatalogResultT", bound=CatalogVersionResult)

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


UTC_DAY_READ = "utc_day_read"
"""The ``request.state`` attribute holding the instant a day-dependent read used.

A route whose result depends on the UTC day, such as current parameter values,
sets it with ``take_utc_instant_for_read`` and reads with that same instant;
its response may then be reused only until the next UTC midnight after it.
"""


def utc_now() -> datetime:
    """Return the current time in UTC; tests replace it to fix the clock."""
    return datetime.now(UTC)


def take_utc_instant_for_read(request: Request) -> datetime:
    """Take the instant a day-dependent read uses, and record it on the request.

    The read and its response's cache lifetime then use the same UTC day.
    """
    instant = utc_now()
    setattr(request.state, UTC_DAY_READ, instant)
    return instant


def _seconds_left_in_utc_day(read_instant: datetime, now: datetime) -> int:
    """Return the seconds from ``now`` to the UTC midnight after ``read_instant``.

    Zero when that midnight has passed, so values read for one day are never
    reused into the next.
    """
    next_midnight = (read_instant.astimezone(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(int((next_midnight - now).total_seconds()), 0)


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
    running version for five minutes, and one whose route read for a UTC day
    (``UTC_DAY_READ``) no later than the midnight after that day. Every such
    response, and the 304 a request whose ``If-None-Match`` names the ETag
    gets instead, varies by ``Origin`` and ``Accept-Encoding``.
    """
    entity_tag = response.headers.get("etag") or body_entity_tag(response.body)
    max_age = (
        EXPLICIT_VERSION_MAX_AGE_SECONDS
        if "policyengine_version" in request.query_params
        else RUNNING_VERSION_MAX_AGE_SECONDS
    )
    read_instant = getattr(request.state, UTC_DAY_READ, None)
    if read_instant is not None:
        max_age = min(max_age, _seconds_left_in_utc_day(read_instant, utc_now()))
    headers = {"Cache-Control": f"public, max-age={max_age}", "ETag": entity_tag}
    if _names_entity_tag(request.headers.get("if-none-match"), entity_tag):
        not_modified = Response(status_code=304, headers=headers)
        not_modified.headers["Vary"] = _cacheable_vary(None)
        return not_modified
    response.headers.update(headers)
    response.headers["Vary"] = _cacheable_vary(response.headers.get("vary"))
    return response


CACHEABLE_VARY_VALUES = ("Origin", "Accept-Encoding")
"""What every cacheable metadata response, and its 304, varies by.

The API reflects every origin in Access-Control-Allow-Origin, and a request
without Origin gets no such header, so a shared cache must keep responses
apart by Origin; gzip compresses the body for clients that accept it. A 304
carries the Vary its 200 would.
"""


def _cacheable_vary(existing: str | None) -> str:
    """Return ``existing`` with Origin and Accept-Encoding added if absent.

    The CORS and gzip middleware may append them again; the application's
    outermost middleware (UniqueVaryMiddleware) then lists each value once.
    """
    return unique_vary_values(", ".join([existing or "", *CACHEABLE_VARY_VALUES]))


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
    route: str,
    query: CatalogQuery,
    response_type: type[MetadataResourceSuccessResponse[CatalogResultT]],
    operation: Callable[[V2MetadataResourceReader], CatalogResultT],
) -> MetadataResourceSuccessResponse[CatalogResultT] | Response:
    """Serve a whole catalog-version response, built once per process when kept.

    With the dependencies' response cache, the serialized body and its ETag
    for ``route``, the query's country and the version it selects are read
    and built only on the first successful request; failures are served as
    ``read_resource`` serves them and never kept. Without a cache this is
    ``read_resource``.
    """
    cache = dependencies.v2_metadata_response_cache
    if cache is None:
        return read_resource(dependencies, response_type, operation)

    def build() -> BuiltResponse | Response:
        result = read_resource(dependencies, response_type, operation)
        if isinstance(result, MetadataResourceSuccessResponse):
            return BuiltResponse(
                body=result.model_dump_json().encode(),
                policyengine_version=result.result.policyengine_version,
            )
        return result

    kept = cache.get_or_build(
        route, query.country_id, query.policyengine_version, build
    )
    if isinstance(kept, KeptResponse):
        return Response(
            content=kept.body,
            media_type="application/json",
            headers={"ETag": kept.entity_tag},
        )
    return kept


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
    except (V2ConfigurationError, MetadataCatalogUnavailableError) as error:
        # Only a missing parameter tree has a message written for callers.
        message = (
            str(error)
            if isinstance(error, ParameterTreeUnavailableError)
            else "V2 metadata catalog is unavailable"
        )
        return v2_error_response(503, message)
    except Exception:  # noqa: BLE001  # preview must return typed errors
        return v2_error_response(500, "V2 metadata query failed")
    finally:
        if reader is not None:
            # Best-effort close must not replace the typed response.
            with contextlib.suppress(Exception):
                reader.close()
