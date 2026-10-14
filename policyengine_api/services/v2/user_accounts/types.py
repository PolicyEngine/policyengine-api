"""Framework-independent data exchanged by v2 account layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.identity.types import AccountConversionOutcome
from policyengine_api.services.v2.user_households.types import UserHouseholdRead
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
from policyengine_api.services.v2.user_simulations.types import UserSimulationRead


PersonName = Annotated[str, StringConstraints(max_length=255)]


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


@dataclass(frozen=True)
class AccountRead:
    id: UUID
    user_type: str
    # Null only for an unauthenticated user.
    primary_country: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    created_at: datetime


@dataclass(frozen=True)
class AccountExport:
    # Null when an unauthenticated principal has not saved anything yet.
    user: AccountRead | None
    policies: tuple[UserPolicyRead, ...]
    households: tuple[UserHouseholdRead, ...]
    simulations: tuple[UserSimulationRead, ...]
    reports: tuple[UserReportRead, ...]


@dataclass(frozen=True)
class AccountUpgrade:
    """The signed-in account after a browser's unauthenticated user moved in."""

    account: AccountRead
    outcome: AccountConversionOutcome


@dataclass(frozen=True)
class AccountDeletion:
    user_id: UUID | None
    auth0_subjects: tuple[str, ...]


class Auth0UserDeleter(Protocol):
    """Removes users from Auth0 when an account is deleted."""

    def prepare_deletion(self) -> None:
        """Obtain working credentials; raise before any data is deleted."""

    def delete_user(self, subject: str) -> None: ...
