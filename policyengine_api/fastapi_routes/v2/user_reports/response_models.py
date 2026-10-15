"""Strict HTTP response models for v2 user-report associations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_reports.types import (
        SharedUserReportRead,
        UserReportPage,
        UserReportRead,
    )


class StrictUserReportAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class StoredSnapshotItem(BaseModel):
    """A stored v3 report snapshot as responses publish it.

    These shapes mirror the contract but not the input bounds: they ignore
    unknown keys and accept any stored length, count, or label, so a row saved
    under older or looser input rules still serializes and one row can never
    fail a list or an export.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)


class ReportProvisionIntervalItem(StoredSnapshotItem):
    # The contract makes this key optional rather than nullable.
    parameter: str | None = Field(default=None, exclude_if=lambda value: value is None)
    start_date: str
    end_date: str
    value: JsonValue


class ReportProvisionItem(StoredSnapshotItem):
    path: str
    breadcrumb: str
    unit: str | None = None
    baseline_value: JsonValue
    value: JsonValue
    intervals: list[ReportProvisionIntervalItem] | None = None
    # Optional rather than nullable: absent unless the provision grows.
    growth: str | None = Field(default=None, exclude_if=lambda value: value is None)
    growth_start: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    growth_base: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    growth_round_to: float | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    growth_round: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ReportCalibrationWorstItem(StoredSnapshotItem):
    name: str
    source: str
    geography: str
    relative_error: float | None = None


class ReportCalibrationMatchItem(StoredSnapshotItem):
    variable: str
    depth: int
    ring: str
    target_count: int
    mean_abs_relative_error: float
    worst: ReportCalibrationWorstItem


class ReportCalibrationItem(StoredSnapshotItem):
    release_id: str | None = None
    geography: str
    reached_count: int
    matches: list[ReportCalibrationMatchItem]


class ReportScorecardItem(StoredSnapshotItem):
    programs: list[str]


class ReportValidationItem(StoredSnapshotItem):
    matched_at: str
    map_model_version: str
    calibration: ReportCalibrationItem | None = None
    scorecard: ReportScorecardItem | None = None


class UserReportItem(StrictUserReportAPIModel):
    id: UUID
    country_id: CountryId
    user_id: UUID
    report_id: UUID | None
    legacy_report_id: int | None
    name: str | None
    description: str | None
    user_policy_id: UUID | None
    baseline_user_policy_id: UUID | None
    source_note: str | None
    provisions: list[ReportProvisionItem] | None
    validation: ReportValidationItem | None
    budget_window_years: int | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: UserReportRead) -> UserReportItem:
        return cls.model_validate(item)


class SharedBaselineReformItem(StrictUserReportAPIModel):
    name: str | None


class SharedUserReportItem(StrictUserReportAPIModel):
    """A saved report as anyone holding its link reads it."""

    id: UUID
    country_id: CountryId
    legacy_report_id: int | None
    name: str | None
    source_note: str | None
    provisions: list[ReportProvisionItem] | None
    validation: ReportValidationItem | None
    budget_window_years: int | None
    baseline_reform: SharedBaselineReformItem | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: SharedUserReportRead) -> SharedUserReportItem:
        return cls.model_validate(item)


class SharedUserReportDetailResult(StrictUserReportAPIModel):
    item: SharedUserReportItem


class UserReportDetailResult(StrictUserReportAPIModel):
    item: UserReportItem


class UserReportPageResult(StrictUserReportAPIModel):
    items: list[UserReportItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserReportPage) -> UserReportPageResult:
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


class SharedUserReportDetailResponse(
    UserReportSuccessResponse[SharedUserReportDetailResult]
):
    pass
