"""Strict HTTP response models for v2 user-policy associations."""

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


class PolicyProvenanceItem(BaseModel):
    """Stored v3 reform provenance as responses publish it.

    It mirrors the contract without the input bounds and ignores unknown keys,
    so any stored row serializes.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    source: str
    ref: str | None = None
    confidence: str | None = None


class UserPolicyItem(StrictUserPolicyAPIModel):
    """A policy saved by a v2 user, with the user's name and description for it.

    Unlike policies, associations can be renamed or deleted.
    """

    id: UUID
    country_id: CountryId
    user_id: UUID
    policy_id: UUID | None
    legacy_policy_id: int | None
    name: str | None
    description: str | None
    baseline: UserPolicyBaseline | None
    provenance: PolicyProvenanceItem | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserPolicyRead) -> UserPolicyItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class UserPolicyDetailResult(StrictUserPolicyAPIModel):
    """Result holding one user-policy association in ``item``."""

    item: UserPolicyItem


class UserPolicyPageResult(StrictUserPolicyAPIModel):
    """One page of user-policy associations, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[UserPolicyItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserPolicyPage) -> UserPolicyPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[UserPolicyItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserPolicySuccessResponse(StrictUserPolicyAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserPolicyDetailResponse(UserPolicySuccessResponse[UserPolicyDetailResult]):
    """Success response holding one user-policy association."""


class UserPolicyPageResponse(UserPolicySuccessResponse[UserPolicyPageResult]):
    """Success response holding one page of user-policy associations."""


USER_POLICY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = (
    USER_RESOURCE_ERROR_RESPONSES
)
