"""Strict HTTP schemas for native v2 user-policy associations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from policyengine_api.data.v2.user_policies.query import (
    UserPolicyPage,
    UserPolicyRead,
)
from policyengine_api.data.v2.user_policies.schemas import (
    UserPolicyCreateCommand,
    UserPolicyPatchCommand,
)
from policyengine_api.query_parameters import CountryId, ResourceId, UserId


class StrictUserPolicyAPIModel(BaseModel):
    """Strict association contract with dataclass conversion support."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserPolicyCreateRequest(UserPolicyCreateCommand):
    """Association identity, immutable link fields, and presentation fields."""


class UserPolicyPatchRequest(UserPolicyPatchCommand):
    """Explicitly supplied mutable presentation fields."""


class UserPolicyItem(StrictUserPolicyAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UserId
    policy_id: ResourceId
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserPolicyRead) -> "UserPolicyItem":
        return cls.model_validate(item)


class UserPolicyDetailResult(StrictUserPolicyAPIModel):
    item: UserPolicyItem


class UserPolicyPageResult(StrictUserPolicyAPIModel):
    items: list[UserPolicyItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserPolicyPage) -> "UserPolicyPageResult":
        return cls(
            items=[UserPolicyItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserPolicySuccessResponse(StrictUserPolicyAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserPolicyDetailResponse(UserPolicySuccessResponse[UserPolicyDetailResult]):
    pass


class UserPolicyPageResponse(UserPolicySuccessResponse[UserPolicyPageResult]):
    pass


class UserPolicyErrorResponse(StrictUserPolicyAPIModel):
    status: Literal["error"] = "error"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


USER_POLICY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": UserPolicyErrorResponse,
        "description": "Association content or country selection is invalid.",
    },
    404: {
        "model": UserPolicyErrorResponse,
        "description": "The selected user, policy, or association does not exist.",
    },
    409: {
        "model": UserPolicyErrorResponse,
        "description": "Association state conflicts with stored state.",
    },
    422: {
        "model": UserPolicyErrorResponse,
        "description": "The request does not match the association schema.",
    },
    500: {
        "model": UserPolicyErrorResponse,
        "description": "The association operation could not be completed.",
    },
    503: {
        "model": UserPolicyErrorResponse,
        "description": "Supabase association persistence is unavailable.",
    },
}
