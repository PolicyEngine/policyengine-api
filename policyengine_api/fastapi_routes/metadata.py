"""Native country/model metadata route."""

from __future__ import annotations

from typing import Literal, TypedDict

from fastapi import APIRouter
from policyengine_api.country_validation import (
    InvalidCountryError,
    ensure_supported_country,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.responses import (
    LegacyJSONResponse,
    render_legacy_json,
)
from policyengine_api.json_types import JSONObject
from policyengine_api.utils.streaming_json import (
    iter_body_chunks,
    should_stream_body,
)
from starlette.responses import Response, StreamingResponse


class MetadataSuccessPayload(TypedDict):
    status: Literal["ok"]
    message: None
    result: JSONObject


def build_metadata_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the selectable native metadata route."""
    router = APIRouter()
    metadata_reader = dependencies.metadata_reader_factory()

    @router.get(
        "/{country_id}/metadata",
        response_class=LegacyJSONResponse,
        include_in_schema=False,
    )
    def metadata(country_id: str) -> Response:
        try:
            ensure_supported_country(country_id)
        except InvalidCountryError as error:
            return LegacyJSONResponse(
                error.to_payload(),
                status_code=400,
                media_type="text/html",
            )

        payload: MetadataSuccessPayload = {
            "status": "ok",
            "message": None,
            "result": metadata_reader.get_metadata(country_id),
        }
        body = render_legacy_json(payload)
        if should_stream_body(body):
            return StreamingResponse(
                iter_body_chunks(body),
                media_type=LegacyJSONResponse.media_type,
            )
        return Response(body, media_type=LegacyJSONResponse.media_type)

    return router
