"""Framework-independent data exchanged by v2 account layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.services.v2.identity.types import AccountConversionOutcome
    from policyengine_api.services.v2.user_households.types import UserHouseholdRead
    from policyengine_api.services.v2.user_policies.types import UserPolicyRead
    from policyengine_api.services.v2.user_reports.types import UserReportRead
    from policyengine_api.services.v2.user_simulations.types import UserSimulationRead

PersonName = Annotated[str, StringConstraints(max_length=255)]


class StrictAccountInput(BaseModel):
    """Reject fields outside the reviewed account contract; inputs are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountUpdateInput(StrictAccountInput):
    """Account fields to change; only the supplied ones are updated."""

    first_name: PersonName | None = None
    last_name: PersonName | None = None
    primary_country: CountryId | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> AccountUpdateInput:
        """Require a supplied field, and reject an explicit null primary_country."""
        supplied = self.model_fields_set.intersection(
            {"first_name", "last_name", "primary_country"}
        )
        if not supplied:
            msg = (
                "At least one of first_name, last_name, or primary_country must be "
                "supplied"
            )
            raise ValueError(msg)
        if "primary_country" in supplied and self.primary_country is None:
            msg = "primary_country must not be null"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class AccountRead:
    """A user's account as the service returns it to routes."""

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
    """A user's account and every association it owns, across countries."""

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
    """The deleted user, if any, and the Auth0 subjects removed with it."""

    user_id: UUID | None
    auth0_subjects: tuple[str, ...]


class Auth0UserDeleter(Protocol):
    """Removes users from Auth0 when an account is deleted."""

    def prepare_deletion(self) -> None:
        """Obtain working credentials; raise before any data is deleted."""

    def delete_user(self, subject: str) -> None:
        """Delete one Auth0 user; an already-absent user counts as deleted."""
        ...
