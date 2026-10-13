"""Strict HTTP response models for signed-in v2 user-report associations."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_reports.types import (
    ReportProvision,
    ReportValidation,
    UserReportPage,
    UserReportRead,
)


class StrictUserReportAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserReportItem(StrictUserReportAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UUID
    report_id: UUID | None
    legacy_report_id: int | None
    name: str | None
    description: str | None
    user_policy_id: UUID | None
    source_note: str | None
    provisions: list[ReportProvision] | None
    validation: ReportValidation | None
    last_run_at: datetime | None
    client_ref: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserReportRead) -> "UserReportItem":
        return cls.model_validate(item)


class UserReportDetailResult(StrictUserReportAPIModel):
    item: UserReportItem


class UserReportPageResult(StrictUserReportAPIModel):
    items: list[UserReportItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserReportPage) -> "UserReportPageResult":
        return cls(
            items=[UserReportItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserReportSuccessResponse(StrictUserReportAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserReportDetailResponse(UserReportSuccessResponse[UserReportDetailResult]):
    pass


class UserReportPageResponse(UserReportSuccessResponse[UserReportPageResult]):
    pass
