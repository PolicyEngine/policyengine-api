"""Framework-independent data exchanged by v2 household layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

from policyengine_api.query_parameters import CountryId, DefaultYear
from policyengine_api.services.v2.households.validators import require_json_value

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

StrictJsonValue = Annotated[JsonValue, BeforeValidator(require_json_value)]


class StrictHouseholdInput(BaseModel):
    """Reject undeclared fields and non-finite numeric coercion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class HouseholdCreationInput(StrictHouseholdInput):
    """Complete normalized immutable household content accepted from any source."""

    country_id: CountryId
    default_year: DefaultYear | None
    household_data: StrictJsonValue

    @field_validator("household_data")
    @classmethod
    def require_document(cls, value: object) -> object:
        """Reject household_data that is not a JSON object."""
        if type(value) is not dict:
            msg = "household_data must be an object"
            raise ValueError(msg)
        return value


class NativeHouseholdCreationInput(HouseholdCreationInput):
    """Native household content with a required default year."""

    default_year: DefaultYear


class LegacyHouseholdSnapshot(StrictHouseholdInput):
    """Detached committed v1 fields required for household copying."""

    country_id: CountryId
    legacy_household_id: Annotated[int, Field(ge=0)]
    label: Annotated[str, Field(max_length=255)] | None = None
    api_version: Annotated[str, Field(min_length=1, max_length=255)]
    household_json: StrictJsonValue
    source_household_hash: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("household_json")
    @classmethod
    def require_legacy_document(cls, value: object) -> object:
        """Reject a v1 household_json that is not a JSON object."""
        if type(value) is not dict:
            msg = "legacy household_json must be an object"
            raise ValueError(msg)
        return value


@dataclass(frozen=True)
class CanonicalHouseholdContent:
    """Canonical bytes of one household and the SHA-256 digest that deduplicates it.

    ``version`` is the canonicalization version; the same content hashed under
    a different version is a different stored household.
    """

    version: int
    document: bytes
    content_hash: str


@dataclass(frozen=True)
class HouseholdCreationResult:
    """The stored household id, and whether this call inserted it or found it."""

    household_id: UUID
    created: bool


@dataclass(frozen=True)
class LegacyHouseholdPersistenceResult:
    """Outcome of copying one v1 household into v2.

    ``household_id`` is the v2 household the v1 id maps to; the flags say whether
    this call created the household and the v1-to-v2 mapping or found them.
    """

    household_id: UUID
    household_created: bool
    mapping_created: bool


@dataclass(frozen=True)
class HouseholdRead:
    """A stored v2 household as the service returns it to routes."""

    id: UUID
    country_id: str
    default_year: int | None
    household_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NativeHouseholdCreation:
    """A created-or-found household, with ``created`` choosing 201 or 200."""

    item: HouseholdRead
    created: bool
