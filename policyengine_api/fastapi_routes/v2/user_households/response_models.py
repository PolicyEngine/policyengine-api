"""Strict HTTP response models for native v2 user-household associations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.query_parameters import CountryId, ResourceId, UserId
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdPage,
    UserHouseholdRead,
)


class StrictUserHouseholdAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserHouseholdItem(StrictUserHouseholdAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UserId
    household_id: ResourceId
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserHouseholdRead) -> "UserHouseholdItem":
        return cls.model_validate(item)


class UserHouseholdDetailResult(StrictUserHouseholdAPIModel):
    item: UserHouseholdItem


class UserHouseholdPageResult(StrictUserHouseholdAPIModel):
    items: list[UserHouseholdItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserHouseholdPage) -> "UserHouseholdPageResult":
        return cls(
            items=[UserHouseholdItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserHouseholdSuccessResponse(StrictUserHouseholdAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserHouseholdDetailResponse(
    UserHouseholdSuccessResponse[UserHouseholdDetailResult]
):
    pass


class UserHouseholdPageResponse(UserHouseholdSuccessResponse[UserHouseholdPageResult]):
    pass


USER_HOUSEHOLD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "Association content or country selection is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The selected user, household, or association does not exist.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": "Association state conflicts with stored state.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the association schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The association operation could not be completed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "Supabase association persistence is unavailable.",
    },
}
