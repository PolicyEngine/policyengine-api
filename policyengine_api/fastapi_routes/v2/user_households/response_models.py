"""Strict HTTP response models for v2 user-household associations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
)
from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_households.types import (
        UserHouseholdPage,
        UserHouseholdRead,
    )


class StrictUserHouseholdAPIModel(BaseModel):
    """Base for user-household responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserHouseholdItem(StrictUserHouseholdAPIModel):
    """A household saved by a v2 user, with the user's name and description for it.

    Unlike households, associations can be renamed, pointed at another
    household of the same country, or deleted.
    """

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
    def from_read(cls, item: UserHouseholdRead) -> UserHouseholdItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class UserHouseholdDetailResult(StrictUserHouseholdAPIModel):
    """Result holding one user-household association in ``item``."""

    item: UserHouseholdItem


class UserHouseholdPageResult(StrictUserHouseholdAPIModel):
    """One page of user-household associations, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[UserHouseholdItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserHouseholdPage) -> UserHouseholdPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[UserHouseholdItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserHouseholdSuccessResponse(StrictUserHouseholdAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserHouseholdDetailResponse(
    UserHouseholdSuccessResponse[UserHouseholdDetailResult]
):
    """Success response holding one user-household association."""


class UserHouseholdPageResponse(UserHouseholdSuccessResponse[UserHouseholdPageResult]):
    """Success response holding one page of user-household associations."""


USER_HOUSEHOLD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = (
    USER_RESOURCE_ERROR_RESPONSES
)
