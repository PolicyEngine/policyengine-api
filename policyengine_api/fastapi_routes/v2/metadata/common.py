"""Shared response handling for API v2 metadata routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel
from starlette.responses import JSONResponse

from policyengine_api.services.v2.metadata_service import (
    InvalidMetadataPageError,
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    MetadataResourceNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.catalog.schemas import MetadataErrorResponse
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


ERROR_RESPONSES = {
    400: {
        "model": MetadataErrorResponse,
        "description": "The resource request or PolicyEngine.py version is invalid.",
    },
    404: {
        "model": MetadataErrorResponse,
        "description": "The requested catalog resource is absent.",
    },
    405: {
        "model": MetadataErrorResponse,
        "description": "The dormant v2 metadata resources support GET only.",
    },
    422: {
        "model": MetadataErrorResponse,
        "description": "The request parameters do not match the resource schema.",
    },
    500: {
        "model": MetadataErrorResponse,
        "description": "The resource query failed internally.",
    },
    503: {
        "model": MetadataErrorResponse,
        "description": "The initialized v2 catalog is unavailable.",
    },
}


def error_response(status_code: int, message: str) -> JSONResponse:
    error = MetadataErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


ResponseT = TypeVar("ResponseT", bound=BaseModel)


def read_resource(
    dependencies: NativeRouteDependencies,
    response_type: type[ResponseT],
    operation: Callable[[object], object],
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
        return error_response(400, str(error))
    except UnsupportedPreviewCountryError as error:
        return error_response(400, f"Unsupported country: {error}")
    except (
        MetadataCatalogVersionNotFoundError,
        MetadataResourceNotFoundError,
    ) as error:
        return error_response(404, str(error))
    except (V2ConfigurationError, MetadataCatalogUnavailableError):
        return error_response(503, "V2 metadata catalog is unavailable")
    except Exception:  # noqa: BLE001 - preview must return typed errors
        return error_response(500, "V2 metadata query failed")
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
