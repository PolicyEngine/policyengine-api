"""Dormant, read-only API v2 metadata preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.query import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataErrorResponse,
    MetadataSuccessResponse,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


ERROR_RESPONSES = {
    400: {
        "model": MetadataErrorResponse,
        "description": "The requested PolicyEngine.py version is invalid.",
    },
    404: {
        "model": MetadataErrorResponse,
        "description": "The requested PolicyEngine.py catalog is absent.",
    },
    405: {
        "model": MetadataErrorResponse,
        "description": "The preview supports GET only.",
    },
    503: {
        "model": MetadataErrorResponse,
        "description": "The initialized v2 catalog is unavailable.",
    },
    500: {
        "model": MetadataErrorResponse,
        "description": "The preview query failed internally.",
    },
}


def _error_response(status_code: int, message: str) -> JSONResponse:
    error = MetadataErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


def build_v2_metadata_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build isolated preview routes without loading v2 configuration."""

    router = APIRouter()

    @router.get(
        "/v2/openapi.json",
        include_in_schema=False,
        summary="OpenAPI document for dormant v2 preview routes",
    )
    def v2_preview_openapi(request: Request) -> JSONResponse:
        schema = request.app.openapi()
        preview_schema = {
            **schema,
            "paths": {
                path: operation
                for path, operation in schema.get("paths", {}).items()
                if path.startswith("/v2/")
            },
        }
        return JSONResponse(preview_schema)

    def read(
        country_id: str,
        policyengine_version: str | None,
    ) -> MetadataSuccessResponse | JSONResponse:
        reader = None
        try:
            factory = dependencies.v2_metadata_reader_factory
            if factory is None:
                from policyengine_api.fastapi_routes.dependencies import (
                    _default_v2_metadata_reader_factory,
                )

                factory = _default_v2_metadata_reader_factory
            reader = factory()
            result = reader.get_metadata(country_id, policyengine_version)
            return MetadataSuccessResponse(result=result)
        except InvalidPolicyEngineVersionError as error:
            return _error_response(400, str(error))
        except MetadataCatalogVersionNotFoundError as error:
            return _error_response(404, str(error))
        except (V2ConfigurationError, MetadataCatalogUnavailableError):
            return _error_response(503, "V2 metadata catalog is unavailable")
        except Exception:  # noqa: BLE001 - preview must return typed errors
            return _error_response(500, "V2 metadata query failed")
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass

    @router.get(
        "/v2/us/metadata",
        response_model=MetadataSuccessResponse,
        responses=ERROR_RESPONSES,
        summary="Preview US metadata from the v2 catalog",
    )
    def us_metadata_preview(
        policyengine_version: str | None = None,
    ) -> MetadataSuccessResponse | JSONResponse:
        return read("us", policyengine_version)

    @router.get(
        "/v2/uk/metadata",
        response_model=MetadataSuccessResponse,
        responses=ERROR_RESPONSES,
        summary="Preview UK metadata from the v2 catalog",
    )
    def uk_metadata_preview(
        policyengine_version: str | None = None,
    ) -> MetadataSuccessResponse | JSONResponse:
        return read("uk", policyengine_version)

    @router.get(
        "/v2/{country_id}/metadata",
        response_model=MetadataErrorResponse,
        status_code=404,
        responses={500: ERROR_RESPONSES[500]},
        summary="Reject an unsupported v2 metadata preview country",
    )
    def unsupported_country(country_id: str) -> MetadataErrorResponse:
        return MetadataErrorResponse(
            message=f"V2 metadata is not available for country {country_id}"
        )

    @router.api_route(
        "/v2/{country_id}/metadata",
        methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=MetadataErrorResponse,
        status_code=405,
        include_in_schema=False,
    )
    def unsupported_method(country_id: str) -> MetadataErrorResponse:
        return MetadataErrorResponse(
            message=f"V2 metadata for country {country_id} supports GET only"
        )

    return router
