"""Framework-independent data exchanged by the layers of users' saved dynamics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import model_validator

from policyengine_api.query_parameters import CountryId, ResourceId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationDescription,
    AssociationName,
    StrictAssociationModel,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class StrictUserDynamicInput(StrictAssociationModel):
    """Reject fields outside the reviewed saved-dynamic contract."""


class UserDynamicCreateFields(StrictUserDynamicInput):
    """Caller-supplied saved-dynamic fields; the owner comes from the session."""

    country_id: CountryId
    dynamic_id: ResourceId
    name: AssociationName | None = None
    description: AssociationDescription | None = None


class UserDynamicCreationInput(StrictUserDynamicInput):
    """Complete persisted saved-dynamic values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    dynamic_id: ResourceId
    name: AssociationName | None = None
    description: AssociationDescription | None = None


class UserDynamicUpdateInput(StrictUserDynamicInput):
    """A partial update of a saved dynamic; only supplied fields are changed.

    At least one field must be supplied. ``dynamic_id`` points the saved
    dynamic at another dynamic in its country, and can't be set to null.
    """

    dynamic_id: ResourceId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_supplied_field(self) -> UserDynamicUpdateInput:
        """Require a supplied field, and reject an explicit null ``dynamic_id``."""
        if not self.model_fields_set & {"dynamic_id", "name", "description"}:
            msg = "At least one of dynamic_id, name, or description must be supplied"
            raise ValueError(msg)
        if "dynamic_id" in self.model_fields_set and self.dynamic_id is None:
            msg = "dynamic_id must not be null"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class UserDynamicRead:
    """A stored saved dynamic as the service returns it to routes."""

    id: UUID
    country_id: str
    user_id: UUID
    dynamic_id: UUID
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserDynamicFilter:
    """Which of the caller's saved dynamics a listing keeps.

    ``dynamic_id`` keeps those naming one dynamic; without it, every saved
    dynamic is kept.
    """

    dynamic_id: UUID | None = None


@dataclass(frozen=True)
class UserDynamicListing:
    """One page of a user's saved dynamics to read, optionally for one dynamic."""

    country_id: str
    user_id: UUID
    dynamic_id: UUID | None
    offset: int
    limit: int


@dataclass(frozen=True)
class UserDynamicPage:
    """One page of saved dynamics in creation order.

    ``has_more`` says whether more follow.
    """

    items: tuple[UserDynamicRead, ...]
    offset: int
    limit: int
    has_more: bool
