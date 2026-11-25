"""Strict HTTP response models for users' saved dynamics."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.user_resources_support import (
    USER_RESOURCE_ERROR_RESPONSES,
)
from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_dynamics.types import (
        UserDynamicPage,
        UserDynamicRead,
    )


class StrictUserDynamicAPIModel(BaseModel):
    """Strict saved-dynamic contract with dataclass conversion support."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserDynamicItem(StrictUserDynamicAPIModel):
    """A dynamic saved by a v2 user, with the user's name and description for it.

    Unlike dynamics, saved dynamics can be renamed, repointed or deleted.
    """

    id: UUID
    country_id: CountryId
    user_id: UUID
    dynamic_id: UUID
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserDynamicRead) -> UserDynamicItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class UserDynamicDetailResult(StrictUserDynamicAPIModel):
    """Result holding one saved dynamic in ``item``."""

    item: UserDynamicItem


class UserDynamicPageResult(StrictUserDynamicAPIModel):
    """One page of saved dynamics, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[UserDynamicItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserDynamicPage) -> UserDynamicPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[UserDynamicItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserDynamicSuccessResponse(StrictUserDynamicAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserDynamicDetailResponse(UserDynamicSuccessResponse[UserDynamicDetailResult]):
    """Success response holding one saved dynamic."""


class UserDynamicPageResponse(UserDynamicSuccessResponse[UserDynamicPageResult]):
    """Success response holding one page of saved dynamics."""


USER_DYNAMIC_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = (
    USER_RESOURCE_ERROR_RESPONSES
)
