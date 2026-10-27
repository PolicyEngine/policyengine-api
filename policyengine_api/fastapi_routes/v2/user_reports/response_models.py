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
    """Base for user-report responses; rejects unknown fields."""

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
    """A provision's value for the dates from ``start_date`` to ``end_date``."""

    # The contract makes this key optional rather than nullable.
    parameter: str | None = Field(default=None, exclude_if=lambda value: value is None)
    start_date: str
    end_date: str
    value: JsonValue


class ReportProvisionItem(StoredSnapshotItem):
    """One parameter the report's reform changes, with its baseline and reform values.

    ``intervals`` gives the reform's dated values when they vary over time. The
    ``growth`` keys, present only when set, say how a value set from one year on
    moves in later years and how grown values round.
    """

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
    """The calibration target that one match fits worst, with its relative error."""

    name: str
    source: str
    geography: str
    relative_error: float | None = None


class ReportCalibrationMatchItem(StoredSnapshotItem):
    """One variable's calibration match: its targets, mean error and worst target."""

    variable: str
    depth: int
    ring: str
    target_count: int
    mean_abs_relative_error: float
    worst: ReportCalibrationWorstItem


class ReportCalibrationItem(StoredSnapshotItem):
    """Calibration results saved with a report, for one geography and data release."""

    release_id: str | None = None
    geography: str
    reached_count: int
    matches: list[ReportCalibrationMatchItem]


class ReportScorecardItem(StoredSnapshotItem):
    """The programs on the scorecard saved with a report's validation."""

    programs: list[str]


class ReportValidationItem(StoredSnapshotItem):
    """The validation snapshot saved with a report.

    It records when the report was matched and with which map model version,
    and optionally the calibration results and scorecard.
    """

    matched_at: str
    map_model_version: str
    calibration: ReportCalibrationItem | None = None
    scorecard: ReportScorecardItem | None = None


class UserReportItem(StrictUserReportAPIModel):
    """A report saved by a user, with the user's name, notes and saved presentation.

    ``report_id`` is the v2 report it shows and ``legacy_report_id`` the v1
    report output; a report migrated from v1 has both. ``user_policy_id`` is
    the user's saved reform the report was run from, and
    ``baseline_user_policy_id`` the saved reform it was compared with instead of
    current law; each is null when not set or once that reform is deleted.
    ``budget_window_years`` is null for a report without a budget window.
    """

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
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class SharedBaselineReformItem(StrictUserReportAPIModel):
    """The saved reform a shared report was compared with, named but not linked."""

    name: str | None


class SharedUserReportItem(StrictUserReportAPIModel):
    """A saved report as anyone holding its link reads it.

    ``report_id`` is the v2 report it shows and ``legacy_report_id`` the v1
    report output.
    """

    id: UUID
    country_id: CountryId
    report_id: UUID | None
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
        """Build the shared item by validating the service read record's fields."""
        return cls.model_validate(item)


class SharedUserReportDetailResult(StrictUserReportAPIModel):
    """Result holding one shared report in ``item``."""

    item: SharedUserReportItem


class UserReportDetailResult(StrictUserReportAPIModel):
    """Result holding one user-report association in ``item``."""

    item: UserReportItem


class UserReportPageResult(StrictUserReportAPIModel):
    """One page of user-report associations, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[UserReportItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: UserReportPage) -> UserReportPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[UserReportItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class UserReportSuccessResponse(StrictUserReportAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class UserReportDetailResponse(UserReportSuccessResponse[UserReportDetailResult]):
    """Success response holding one user-report association."""


class UserReportPageResponse(UserReportSuccessResponse[UserReportPageResult]):
    """Success response holding one page of user-report associations."""


class SharedUserReportDetailResponse(
    UserReportSuccessResponse[SharedUserReportDetailResult]
):
    """Success response holding one shared report."""
