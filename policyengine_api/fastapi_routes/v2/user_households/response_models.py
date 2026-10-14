"""Strict HTTP response models for v2 user-household associations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
)
from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdPage,
    UserHouseholdRead,
)


class StrictUserHouseholdAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserHouseholdItem(StrictUserHouseholdAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UUID
    household_id: UUID | None
    legacy_household_id: int | None
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


USER_HOUSEHOLD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = (
    USER_RESOURCE_ERROR_RESPONSES
)
