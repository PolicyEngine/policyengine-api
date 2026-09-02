"""Execute API v2 metadata reads and translate failures to HTTP responses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
)
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    v2_error_response,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2MetadataResourceReader,
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


def read_resource(
    dependencies: NativeRouteDependencies,
    response_type: type[ResponseT],
    operation: Callable[[V2MetadataResourceReader], object],
) -> ResponseT | JSONResponse:
    reader = None
    try:
        factory = dependencies.v2_metadata_reader_factory
        if factory is None:
            from policyengine_api.fastapi_routes.dependencies import (
                _default_v2_metadata_reader_factory,
            )

            factory = _default_v2_metadata_reader_factory
        reader = factory()
        return response_type(result=operation(reader))
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
    except Exception:  # noqa: BLE001 - preview must return typed errors
        return v2_error_response(500, "V2 metadata query failed")
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
