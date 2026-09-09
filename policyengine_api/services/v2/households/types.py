"""Framework-independent data exchanged by v2 household layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

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
        if type(value) is not dict:
            raise ValueError("household_data must be an object")
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
        if type(value) is not dict:
            raise ValueError("legacy household_json must be an object")
        return value


@dataclass(frozen=True)
class CanonicalHouseholdContent:
    version: int
    document: bytes
    content_hash: str


@dataclass(frozen=True)
class HouseholdCreationResult:
    household_id: UUID
    created: bool


@dataclass(frozen=True)
class LegacyHouseholdPersistenceResult:
    household_id: UUID
    household_created: bool
    mapping_created: bool


@dataclass(frozen=True)
class HouseholdRead:
    id: UUID
    country_id: str
    default_year: int | None
    household_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HouseholdPage:
    items: tuple[HouseholdRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class NativeHouseholdCreation:
    item: HouseholdRead
    created: bool
