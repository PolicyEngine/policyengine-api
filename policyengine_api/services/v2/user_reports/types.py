"""Framework-independent data exchanged by v2 user-report layers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

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

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

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
    """One dated value in a provision's schedule, from ``start_date`` to ``end_date``.

    Dates are ``YYYY-MM-DD`` strings and ``value`` is any finite JSON value.
    ``parameter`` is optional, and is left out of the stored report when unset.
    """

    # The contract makes this key optional rather than nullable.
    parameter: str | None = Field(default=None, exclude_if=lambda value: value is None)
    start_date: IsoDate
    end_date: IsoDate
    value: FiniteJsonValue


class ReportProvision(StrictUserReportModel):
    """One provision of the report's reform: a parameter's baseline and reform values.

    ``path`` is the parameter path and ``breadcrumb`` its readable label, and
    ``intervals`` optionally gives a dated schedule. ``growth`` says how a value
    set from one year on moves in later years (``fixed``, ``current_law`` or an
    index's parameter path); the other ``growth_*`` fields say when it moves and
    how grown values round. They are absent for a hand-set schedule.
    """

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
    """The calibration target a match fits worst, with its source and geography."""

    name: LongLabelText
    source: LongLabelText
    geography: ShortText
    relative_error: float | None = None


class ReportCalibrationMatch(StrictUserReportModel):
    """Calibration of one variable: how closely its targets are met.

    ``ring`` is ``primary``, ``mechanism`` or ``downstream``.
    ``mean_abs_relative_error`` is averaged over the variable's ``target_count``
    targets, and ``worst`` is the target with the largest error.
    """

    variable: LabelText
    depth: int
    ring: Literal["primary", "mechanism", "downstream"]
    target_count: int
    mean_abs_relative_error: float
    worst: ReportCalibrationWorst


class ReportCalibration(StrictUserReportModel):
    """Calibration results for one geography, with at most 500 variable matches."""

    release_id: LabelText | None = None
    geography: ShortText
    reached_count: int
    matches: Annotated[
        list[ReportCalibrationMatch],
        Field(max_length=MAXIMUM_CALIBRATION_MATCHES),
    ]


class ReportScorecard(StrictUserReportModel):
    """The programs on the report's validation scorecard, at most 200 names."""

    programs: Annotated[list[LabelText], Field(max_length=MAXIMUM_SCORECARD_PROGRAMS)]


class ReportValidation(StrictUserReportModel):
    """The validation snapshot saved with a report.

    ``calibration`` and ``scorecard`` are optional, and the stored snapshot keeps
    only the keys supplied.
    """

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
        msg = "provisions must not exceed 64 KiB when serialized"
        raise ValueError(msg)
    return stored


def stored_validation(
    validation: ReportValidation | None,
) -> StoredJSONObject | None:
    """Serialize the validation snapshot with only the keys supplied, or return None."""
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
    def bound_provisions(self) -> _ReportPresentationFields:
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
    """A partial update of a saved report; only supplied fields change.

    At least one field must be supplied. ``legacy_report_id`` repoints the saved
    report to another v1 report output and cannot be cleared; the saved-reform
    links are cleared with null.
    """

    legacy_report_id: LegacyRecordId | None = None
    user_policy_id: ResourceId | None = None
    baseline_user_policy_id: ResourceId | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> UserReportUpdateInput:
        """Require a supplied field and reject a null ``legacy_report_id``."""
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
            msg = "At least one mutable user-report field must be supplied"
            raise ValueError(msg)
        if "legacy_report_id" in supplied and self.legacy_report_id is None:
            msg = "legacy_report_id must not be null"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class UserReportRead:
    """A stored user-report association as the service returns it to its owner.

    Unlike SharedUserReportRead, it includes the owner, the description and the
    owner's saved-reform links.
    """

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
class UserReportListing:
    """One page of a user's associations to read, optionally for one v1 report."""

    country_id: str
    user_id: UUID
    legacy_report_id: int | None
    offset: int
    limit: int


@dataclass(frozen=True)
class UserReportPage:
    """One page of associations in creation order; ``has_more`` says if more follow."""

    items: tuple[UserReportRead, ...]
    offset: int
    limit: int
    has_more: bool
