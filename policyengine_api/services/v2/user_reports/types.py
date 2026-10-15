"""Framework-independent data exchanged by v2 user-report layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from policyengine_api.query_parameters import CountryId, ResourceId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationDescription,
    AssociationName,
    FiniteJsonValue,
    StrictAssociationModel,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId
from policyengine_api.utils.budget_window import BUDGET_WINDOW_MAX_YEARS


MAXIMUM_PROVISIONS_BYTES = 64 * 1024
REPORT_SOURCE_NOTE_MAX_LENGTH = 10_000
MAXIMUM_CALIBRATION_MATCHES = 500
MAXIMUM_SCORECARD_PROGRAMS = 200
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
ReportSourceNote = Annotated[
    str, StringConstraints(max_length=REPORT_SOURCE_NOTE_MAX_LENGTH)
]
# A window of one year is the report itself, so it is stored as no window.
BudgetWindowYears = Annotated[int, Field(ge=2, le=BUDGET_WINDOW_MAX_YEARS)]
ShortText = Annotated[str, StringConstraints(max_length=64)]
LabelText = Annotated[str, StringConstraints(max_length=255)]
LongLabelText = Annotated[str, StringConstraints(max_length=1024)]


class StrictUserReportModel(StrictAssociationModel):
    """Reject fields outside the reviewed user-report contract."""


class ReportProvisionInterval(StrictUserReportModel):
    # The contract makes this key optional rather than nullable.
    parameter: str | None = Field(default=None, exclude_if=lambda value: value is None)
    start_date: IsoDate
    end_date: IsoDate
    value: FiniteJsonValue


class ReportProvision(StrictUserReportModel):
    path: str
    breadcrumb: str
    unit: str | None = None
    baseline_value: FiniteJsonValue
    value: FiniteJsonValue
    intervals: list[ReportProvisionInterval] | None = None
    # How a value set from one year on moves after it: 'fixed',
    # 'current_law', or an index's parameter path. The rest say when it
    # moves and how grown values round. Absent for a hand-set schedule.
    growth: LongLabelText | None = None
    growth_start: int | None = None
    growth_base: int | None = None
    growth_round_to: float | None = None
    growth_round: Literal["nearest", "down", "up"] | None = None


class ReportCalibrationWorst(StrictUserReportModel):
    name: LongLabelText
    source: LongLabelText
    geography: ShortText
    relative_error: float | None = None


class ReportCalibrationMatch(StrictUserReportModel):
    variable: LabelText
    depth: int
    ring: Literal["primary", "mechanism", "downstream"]
    target_count: int
    mean_abs_relative_error: float
    worst: ReportCalibrationWorst


class ReportCalibration(StrictUserReportModel):
    release_id: LabelText | None = None
    geography: ShortText
    reached_count: int
    matches: Annotated[
        list[ReportCalibrationMatch],
        Field(max_length=MAXIMUM_CALIBRATION_MATCHES),
    ]


class ReportScorecard(StrictUserReportModel):
    programs: Annotated[list[LabelText], Field(max_length=MAXIMUM_SCORECARD_PROGRAMS)]


class ReportValidation(StrictUserReportModel):
    matched_at: ShortText
    map_model_version: LabelText
    calibration: ReportCalibration | None = None
    scorecard: ReportScorecard | None = None


StoredJSONObject = dict[str, JsonValue]


def stored_provisions(
    provisions: list[ReportProvision] | None,
) -> list[StoredJSONObject] | None:
    """Serialize provisions exactly as supplied, enforcing the 64 KiB cap."""

    if provisions is None:
        return None
    stored = [
        provision.model_dump(mode="json", exclude_unset=True)
        for provision in provisions
    ]
    encoded = json.dumps(stored, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAXIMUM_PROVISIONS_BYTES:
        raise ValueError("provisions must not exceed 64 KiB when serialized")
    return stored


def stored_validation(
    validation: ReportValidation | None,
) -> StoredJSONObject | None:
    if validation is None:
        return None
    return validation.model_dump(mode="json", exclude_unset=True)


class _ReportPresentationFields(StrictUserReportModel):
    name: AssociationName | None = None
    description: AssociationDescription | None = None
    source_note: ReportSourceNote | None = None
    provisions: list[ReportProvision] | None = None
    validation: ReportValidation | None = None
    budget_window_years: BudgetWindowYears | None = None
    last_run_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def bound_provisions(self) -> "_ReportPresentationFields":
        stored_provisions(self.provisions)
        return self


class UserReportCreateFields(_ReportPresentationFields):
    """Caller-supplied fields; Stage 12A accepts only v1 report references."""

    country_id: CountryId
    legacy_report_id: LegacyRecordId
    user_policy_id: ResourceId | None = None
    baseline_user_policy_id: ResourceId | None = None


class UserReportCreationInput(StrictUserReportModel):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    legacy_report_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None
    user_policy_id: ResourceId | None = None
    baseline_user_policy_id: ResourceId | None = None
    source_note: str | None = None
    provisions: list[StoredJSONObject] | None = None
    validation: StoredJSONObject | None = None
    budget_window_years: int | None = None
    last_run_at: AwareDatetime | None = None


class UserReportUpdateInput(_ReportPresentationFields):
    legacy_report_id: LegacyRecordId | None = None
    user_policy_id: ResourceId | None = None
    baseline_user_policy_id: ResourceId | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> "UserReportUpdateInput":
        mutable_fields = {
            "legacy_report_id",
            "name",
            "description",
            "user_policy_id",
            "baseline_user_policy_id",
            "source_note",
            "provisions",
            "validation",
            "budget_window_years",
            "last_run_at",
        }
        supplied = self.model_fields_set.intersection(mutable_fields)
        if not supplied:
            raise ValueError("At least one mutable user-report field must be supplied")
        if "legacy_report_id" in supplied and self.legacy_report_id is None:
            raise ValueError("legacy_report_id must not be null")
        return self


@dataclass(frozen=True)
class UserReportRead:
    id: UUID
    country_id: str
    user_id: UUID
    report_id: UUID | None
    legacy_report_id: int | None
    name: str | None
    description: str | None
    user_policy_id: UUID | None
    baseline_user_policy_id: UUID | None
    source_note: str | None
    provisions: list[StoredJSONObject] | None
    validation: StoredJSONObject | None
    budget_window_years: int | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SharedBaselineReformRead:
    """The saved reform a shared report was compared with, by name only."""

    name: str | None


@dataclass(frozen=True)
class SharedUserReportRead:
    """What anyone holding a saved report's link may read.

    The owner and the owner's saved-reform IDs stay private; the reform the
    report was compared with is named instead of linked.
    """

    id: UUID
    country_id: str
    legacy_report_id: int | None
    name: str | None
    source_note: str | None
    provisions: list[StoredJSONObject] | None
    validation: StoredJSONObject | None
    budget_window_years: int | None
    baseline_reform: SharedBaselineReformRead | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserReportPage:
    items: tuple[UserReportRead, ...]
    offset: int
    limit: int
    has_more: bool
