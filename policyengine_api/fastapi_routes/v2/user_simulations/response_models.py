"""Strict HTTP response models for signed-in v2 user-simulation associations."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationPage,
    UserSimulationRead,
)


class StrictUserSimulationAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserSimulationItem(StrictUserSimulationAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UUID
    simulation_id: UUID | None
    legacy_simulation_id: int | None
    name: str | None
    description: str | None
    client_ref: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserSimulationRead) -> "UserSimulationItem":
        return cls.model_validate(item)


class UserSimulationDetailResult(StrictUserSimulationAPIModel):
    item: UserSimulationItem


class UserSimulationPageResult(StrictUserSimulationAPIModel):
    items: list[UserSimulationItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserSimulationPage) -> "UserSimulationPageResult":
        return cls(
            items=[UserSimulationItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserSimulationSuccessResponse(StrictUserSimulationAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserSimulationDetailResponse(
    UserSimulationSuccessResponse[UserSimulationDetailResult]
):
    pass


class UserSimulationPageResponse(
    UserSimulationSuccessResponse[UserSimulationPageResult]
):
    pass
