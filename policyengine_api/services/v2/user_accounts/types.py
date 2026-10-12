"""Framework-independent data exchanged by v2 account layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StringConstraints,
    model_validator,
)

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_households.types import UserHouseholdRead
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
from policyengine_api.services.v2.user_simulations.types import UserSimulationRead


MAXIMUM_IMPORT_ITEMS = 500
PersonName = Annotated[str, StringConstraints(max_length=255)]
ImportedRecord = dict[str, JsonValue]


class StrictAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountUpdateInput(StrictAccountInput):
    first_name: PersonName | None = None
    last_name: PersonName | None = None
    primary_country: CountryId | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> "AccountUpdateInput":
        supplied = self.model_fields_set.intersection(
            {"first_name", "last_name", "primary_country"}
        )
        if not supplied:
            raise ValueError(
                "At least one of first_name, last_name, or primary_country must be "
                "supplied"
            )
        if "primary_country" in supplied and self.primary_country is None:
            raise ValueError("primary_country must not be null")
        return self


class AccountImportInput(StrictAccountInput):
    """Browser-local records; each item is validated individually."""

    policies: list[ImportedRecord] = []
    households: list[ImportedRecord] = []
    simulations: list[ImportedRecord] = []
    reports: list[ImportedRecord] = []

    @model_validator(mode="after")
    def bound_item_count(self) -> "AccountImportInput":
        total = (
            len(self.policies)
            + len(self.households)
            + len(self.simulations)
            + len(self.reports)
        )
        if total > MAXIMUM_IMPORT_ITEMS:
            raise ValueError(
                f"An import may contain at most {MAXIMUM_IMPORT_ITEMS} items"
            )
        return self


class ImportSkipReason(StrEnum):
    INVALID = "invalid"
    UNKNOWN_LEGACY_REFERENCE = "unknown_legacy_reference"


@dataclass(frozen=True)
class ImportSkip:
    client_ref: str | None
    reason: ImportSkipReason


@dataclass(frozen=True)
class AccountImportResult:
    id_map: dict[str, UUID]
    skipped: tuple[ImportSkip, ...]


@dataclass(frozen=True)
class AccountRead:
    id: UUID
    primary_country: str
    first_name: str | None
    last_name: str | None
    email: str | None
    created_at: datetime


@dataclass(frozen=True)
class AccountExport:
    user: AccountRead
    policies: tuple[UserPolicyRead, ...]
    households: tuple[UserHouseholdRead, ...]
    simulations: tuple[UserSimulationRead, ...]
    reports: tuple[UserReportRead, ...]


@dataclass(frozen=True)
class AccountDeletion:
    user_id: UUID | None
    auth0_subjects: tuple[str, ...]
