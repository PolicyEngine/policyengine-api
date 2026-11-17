"""Framework-independent data exchanged by v2 policy layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from policyengine_api.query_parameters import CountryId, PolicyEngineVersion
from policyengine_api.services.v2.policies.validators import (
    MAXIMUM_POLICY_PARAMETER_VALUES,
    normalize_utc,
    require_json_value,
)

StrictJsonValue = Annotated[JsonValue, BeforeValidator(require_json_value)]


class LegacyPolicyTranslationReason(StrEnum):
    """Why committed v1 content cannot be translated, as copy failure logs name it."""

    MISSING_PARAMETERS = "missing_parameters"
    INVALID_PARAMETER_VALUES = "invalid_parameter_values"
    EMPTY_PARAMETER_VALUES = "empty_parameter_values"
    INVALID_PERIOD = "invalid_period"
    CONFLICTING_VALUES = "conflicting_values"
    TOO_MANY_VALUES = "too_many_values"


UtcDateTime = Annotated[datetime, AfterValidator(normalize_utc)]


class StrictPolicyInput(BaseModel):
    """Reject undeclared policy input and non-finite numeric coercion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class PolicyParameterValueInput(StrictPolicyInput):
    """One normalized effective value for a catalog parameter UUID."""

    parameter_id: UUID
    value: StrictJsonValue
    start_date: UtcDateTime
    end_date: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> PolicyParameterValueInput:
        """Reject a value whose end date precedes its start date."""
        if self.end_date is not None and self.end_date < self.start_date:
            msg = "end_date must not precede start_date"
            raise ValueError(msg)
        return self


# A policy's or a dynamic's values, at most MAXIMUM_POLICY_PARAMETER_VALUES.
ParameterValueInputs = Annotated[
    list[PolicyParameterValueInput],
    Field(max_length=MAXIMUM_POLICY_PARAMETER_VALUES),
]


class PolicyCreationInput(StrictPolicyInput):
    """Complete immutable policy content accepted from any source.

    A dynamic's content has the same fields (``dynamics.types``).
    """

    country_id: CountryId
    tax_benefit_model_id: UUID
    parameter_values: ParameterValueInputs

    @field_validator("parameter_values")
    @classmethod
    def reject_duplicate_effective_values(
        cls,
        values: list[PolicyParameterValueInput],
    ) -> list[PolicyParameterValueInput]:
        """Reject two values for the same parameter with the same start date."""
        identities: set[tuple[UUID, datetime]] = set()
        for value in values:
            identity = (value.parameter_id, value.start_date)
            if identity in identities:
                msg = "parameter_values must not repeat a parameter_id/start_date"
                raise ValueError(msg)
            identities.add(identity)
        return values


class NativePolicyCreationInput(PolicyCreationInput):
    """Native policy content plus an optional catalog-version selection."""

    policyengine_version: PolicyEngineVersion | None = None


class ResolvedPolicyCreationInput(PolicyCreationInput):
    """Validated content bound to one exact initialized catalog version."""

    policyengine_version: PolicyEngineVersion
    tax_benefit_model_version_id: UUID


class LegacyPolicySnapshot(StrictPolicyInput):
    """Detached committed fields required by the v2 policy mirror."""

    country_id: CountryId
    legacy_policy_id: Annotated[int, Field(ge=0)]
    label: Annotated[str, Field(max_length=255)] | None = None
    api_version: Annotated[str, Field(min_length=1, max_length=255)]
    policy_json: StrictJsonValue
    source_policy_hash: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("policy_json")
    @classmethod
    def require_parameter_mapping(cls, value: object) -> object:
        """Reject a v1 policy_json that is not an object keyed by parameter path."""
        if type(value) is not dict:
            msg = "legacy policy_json must be a parameter-path object"
            raise ValueError(msg)
        return value


@dataclass(frozen=True)
class CanonicalPolicyContent:
    """Canonical bytes and SHA-256 identity for one resolved policy."""

    version: int
    document: bytes
    content_hash: str


@dataclass(frozen=True)
class PolicyCreationResult:
    """New or deduplicated immutable policy identity."""

    policy_id: UUID
    created: bool


@dataclass(frozen=True)
class LegacyPolicyTranslation:
    """A v1 policy translated against the running catalog, split in two.

    ``policy`` holds the values that stay in the policy, possibly none.
    ``dynamic`` holds the model's assumptions, the content of the dynamic
    the copy stores, or is None when the v1 policy sets none.
    """

    policy: ResolvedPolicyCreationInput
    dynamic: ResolvedPolicyCreationInput | None


@dataclass(frozen=True)
class LegacyPolicyMappingInput:
    """The mapping a copy records from a v1 policy to its v2 policy and dynamic."""

    country_id: str
    legacy_policy_id: int
    source_policy_hash: str
    policy_id: UUID
    dynamic_id: UUID | None


@dataclass(frozen=True)
class LegacyPolicyPersistenceResult:
    """Destination identity and insertion outcomes for one mirror attempt.

    ``dynamic_id`` is the dynamic the v1 policy's model assumptions were
    copied into, None when it sets none or was copied before the split
    existed; ``dynamic_created`` says whether this attempt inserted it.
    """

    policy_id: UUID
    policy_created: bool
    mapping_created: bool
    dynamic_id: UUID | None = None
    dynamic_created: bool = False


@dataclass(frozen=True)
class PolicyParameterValueRead:
    """One stored parameter value of a policy, with the parameter's name."""

    id: UUID
    parameter_id: UUID
    parameter_name: str
    value: Any
    start_date: datetime
    end_date: datetime | None


@dataclass(frozen=True)
class PolicyRead:
    """A stored v2 policy with its parameter values, as returned to routes."""

    id: UUID
    country_id: str
    tax_benefit_model_id: UUID
    tax_benefit_model_version_id: UUID
    created_at: datetime
    updated_at: datetime
    parameter_values: tuple[PolicyParameterValueRead, ...]


@dataclass(frozen=True)
class CheckedPolicyRead(PolicyRead):
    """A stored policy checked against the running catalog, as routes return it.

    ``missing_parameters`` lists the parameter names the policy sets that the
    running catalog lacks, sorted; it is None only when the running
    PolicyEngine.py version has no published catalog for the country.
    """

    missing_parameters: tuple[str, ...] | None


@dataclass(frozen=True)
class PolicyPage:
    """One page of policies in creation order; ``has_more`` says if more follow."""

    items: tuple[PolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class CheckedPolicyPage:
    """A page of policies, each checked against the running catalog."""

    items: tuple[CheckedPolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class NativePolicyCreation:
    """Complete policy read plus whether this request inserted it."""

    item: CheckedPolicyRead
    created: bool
