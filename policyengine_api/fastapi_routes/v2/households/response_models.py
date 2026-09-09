"""Strict HTTP response models for the native v2 household API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.households.document_models import (
    HouseholdDocument,
)
from policyengine_api.query_parameters import CountryId, DefaultYear
from policyengine_api.services.v2.households.types import HouseholdPage, HouseholdRead


class StrictHouseholdAPIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class HouseholdItem(StrictHouseholdAPIModel):
    id: UUID
    country_id: CountryId
    default_year: DefaultYear | None
    household_data: HouseholdDocument
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: HouseholdRead) -> "HouseholdItem":
        return cls.model_validate(item)


class HouseholdDetailResult(StrictHouseholdAPIModel):
    item: HouseholdItem


class HouseholdPageResult(StrictHouseholdAPIModel):
    items: list[HouseholdItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: HouseholdPage) -> "HouseholdPageResult":
        return cls(
            items=[HouseholdItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class HouseholdSuccessResponse(StrictHouseholdAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class HouseholdDetailResponse(HouseholdSuccessResponse[HouseholdDetailResult]):
    pass


class HouseholdPageResponse(HouseholdSuccessResponse[HouseholdPageResult]):
    pass


HOUSEHOLD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The household content or country selection is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The selected household does not exist.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": "Immutable household content conflicts with stored state.",
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The household request body exceeds 1 MiB.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the household schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "Stored household integrity validation failed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "Supabase household persistence is unavailable.",
    },
}
