"""Framework-independent data exchanged by v2 user-report layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    JsonValue,
    StringConstraints,
    model_validator,
)

from policyengine_api.query_parameters import CountryId, ResourceId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationClientRef,
    AssociationName,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId


MAXIMUM_PROVISIONS_BYTES = 64 * 1024
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class StrictUserReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportProvisionInterval(StrictUserReportModel):
    parameter: str | None = None
    start_date: IsoDate
    end_date: IsoDate
    value: JsonValue


class ReportProvision(StrictUserReportModel):
    path: str
    breadcrumb: str
    unit: str | None = None
    baseline_value: JsonValue
    value: JsonValue
    intervals: list[ReportProvisionInterval] | None = None


class ReportCalibrationWorst(StrictUserReportModel):
    name: str
    source: str
    geography: str
    relative_error: float | None = None


class ReportCalibrationMatch(StrictUserReportModel):
    variable: str
    depth: int
    ring: Literal["primary", "mechanism", "downstream"]
    target_count: int
    mean_abs_relative_error: float
    worst: ReportCalibrationWorst


class ReportCalibration(StrictUserReportModel):
    release_id: str | None = None
    geography: str
    reached_count: int
    matches: list[ReportCalibrationMatch]


class ReportScorecard(StrictUserReportModel):
    programs: list[str]


class ReportValidation(StrictUserReportModel):
    matched_at: str
    map_model_version: str
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
    description: str | None = None
    source_note: str | None = None
    provisions: list[ReportProvision] | None = None
    validation: ReportValidation | None = None
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
    client_ref: AssociationClientRef | None = None


class UserReportCreationInput(StrictUserReportModel):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    legacy_report_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None
    user_policy_id: ResourceId | None = None
    source_note: str | None = None
    provisions: list[StoredJSONObject] | None = None
    validation: StoredJSONObject | None = None
    last_run_at: AwareDatetime | None = None
    client_ref: AssociationClientRef | None = None


class UserReportUpdateInput(_ReportPresentationFields):
    legacy_report_id: LegacyRecordId | None = None
    user_policy_id: ResourceId | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> "UserReportUpdateInput":
        mutable_fields = {
            "legacy_report_id",
            "name",
            "description",
            "user_policy_id",
            "source_note",
            "provisions",
            "validation",
            "last_run_at",
        }
        supplied = self.model_fields_set.intersection(mutable_fields)
        if not supplied:
            raise ValueError("At least one mutable user-report field must be supplied")
        if "legacy_report_id" in supplied and self.legacy_report_id is None:
            raise ValueError("legacy_report_id must not be null")
        return self


class UserReportImportItem(_ReportPresentationFields):
    """One browser-local saved report offered for idempotent import."""

    client_ref: AssociationClientRef
    legacy_report_id: LegacyRecordId
    user_policy_client_ref: AssociationClientRef | None = None


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
    source_note: str | None
    provisions: list[Any] | None
    validation: dict[str, Any] | None
    last_run_at: datetime | None
    client_ref: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserReportPage:
    items: tuple[UserReportRead, ...]
    offset: int
    limit: int
    has_more: bool
