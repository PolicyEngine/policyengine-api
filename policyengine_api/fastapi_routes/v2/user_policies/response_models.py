"""Strict HTTP response models for signed-in v2 user-policy associations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
)
from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_policies.types import (
    UserPolicyBaseline,
    UserPolicyPage,
    UserPolicyRead,
)


class StrictUserPolicyAPIModel(BaseModel):
    """Strict association contract with dataclass conversion support."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserPolicyItem(StrictUserPolicyAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UUID
    policy_id: UUID | None
    legacy_policy_id: int | None
    name: str | None
    description: str | None
    baseline: UserPolicyBaseline | None
    provenance: dict[str, Any] | None
    client_ref: str | None
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


USER_POLICY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = (
    USER_RESOURCE_ERROR_RESPONSES
)
