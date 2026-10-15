"""Framework-independent data exchanged by v2 identity layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Protocol, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from datetime import datetime

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserType


IdentityText = Annotated[str, StringConstraints(min_length=1)]
IdentityEmail = Annotated[str, StringConstraints(min_length=1, max_length=320)]


class UserPrincipal(BaseModel):
    """A verified external sign-in identity; never derived from request data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: IdentityText
    subject: IdentityText
    email: IdentityEmail | None = None


class UnauthenticatedPrincipal(BaseModel):
    """A signed-out browser, identified by the UUID it sends as its credential.

    The UUID is a bearer credential, so it is excluded from ``repr`` and must
    never be logged.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID = Field(repr=False)


AccountPrincipal: TypeAlias = UserPrincipal | UnauthenticatedPrincipal


@dataclass(frozen=True)
class ResolvedUser:
    """The v2 user that one principal acts as."""

    # An unauthenticated user's ID is its credential, so it stays out of repr.
    user_id: UUID = field(repr=False)
    email: str | None
    user_type: UserType


class AccountProvisioningStrategy(Protocol):
    """Find or provision the v2 user for one principal inside a transaction."""

    def find_in_session(self, session: Session) -> ResolvedUser | None:
        """Return the principal's existing user without writing anything."""

    def resolve_in_session(
        self,
        session: Session,
        *,
        country_id: str,
        now: datetime | None = None,
    ) -> ResolvedUser:
        """Return the principal's user, provisioning it when it is absent."""

    def resolve_for_read_in_session(
        self,
        session: Session,
        *,
        country_id: str,
    ) -> ResolvedUser | None:
        """Return the user a read-only operation acts as, if one exists."""


class AccountConversionOutcome(StrEnum):
    # The unauthenticated user became the signed-in identity's user in place.
    CONVERTED = "converted"
    # Its records moved to the identity's existing user, and it was deleted.
    MERGED = "merged"
    # There was no unauthenticated user to convert.
    NONE = "none"


@dataclass(frozen=True)
class AccountConversion:
    owner: ResolvedUser
    outcome: AccountConversionOutcome
