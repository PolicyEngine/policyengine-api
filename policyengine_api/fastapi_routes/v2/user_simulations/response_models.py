"""Strict HTTP response models for v2 user-simulation associations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationPage,
        UserSimulationRead,
    )


class StrictUserSimulationAPIModel(BaseModel):
    """Base for user-simulation responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserSimulationItem(StrictUserSimulationAPIModel):
    """A simulation saved by a user, with the user's name and description for it.

    ``legacy_simulation_id`` is the v1 simulation it saves. Associations can be
    renamed, pointed at another v1 simulation of the same country, or deleted.
    """

    id: UUID
    country_id: CountryId
    user_id: UUID
    simulation_id: UUID | None
    legacy_simulation_id: int | None
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserSimulationRead) -> UserSimulationItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class UserSimulationDetailResult(StrictUserSimulationAPIModel):
    """Result holding one user-simulation association in ``item``."""

    item: UserSimulationItem


class UserSimulationPageResult(StrictUserSimulationAPIModel):
    """One page of user-simulation associations, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[UserSimulationItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserSimulationPage) -> UserSimulationPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[UserSimulationItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserSimulationSuccessResponse(StrictUserSimulationAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserSimulationDetailResponse(
    UserSimulationSuccessResponse[UserSimulationDetailResult]
):
    """Success response holding one user-simulation association."""


class UserSimulationPageResponse(
    UserSimulationSuccessResponse[UserSimulationPageResult]
):
    """Success response holding one page of user-simulation associations."""
