"""Route-independent commands for immutable v2 policy creation."""

from __future__ import annotations

from datetime import datetime, timezone
import math
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


MAXIMUM_POLICY_PARAMETER_VALUES = 1_000
MAXIMUM_JSON_NESTING = 100


def _require_json_value(
    value: Any,
    *,
    depth: int = 0,
    containers: frozenset[int] = frozenset(),
) -> Any:
    if depth > MAXIMUM_JSON_NESTING:
        raise ValueError("JSON values must not exceed 100 nested containers")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if type(value) not in {list, dict}:
        raise ValueError("value must contain only standards-compliant JSON types")
    identity = id(value)
    if identity in containers:
        raise ValueError("JSON values must not contain reference cycles")
    nested_containers = containers | {identity}
    if type(value) is list:
        for item in value:
            _require_json_value(
                item,
                depth=depth + 1,
                containers=nested_containers,
            )
        return value
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("JSON object keys must be strings")
        _require_json_value(
            item,
            depth=depth + 1,
            containers=nested_containers,
        )
    return value


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("effective dates must include a UTC offset")
    return value.astimezone(timezone.utc)


StrictJsonValue = Annotated[
    JsonValue,
    BeforeValidator(_require_json_value),
]
UtcDateTime = Annotated[datetime, AfterValidator(_normalize_utc)]


class StrictPolicyCommand(BaseModel):
    """Reject undeclared policy input and non-finite numeric coercion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class PolicyParameterValueCommand(StrictPolicyCommand):
    """One normalized effective value for a catalog parameter UUID."""

    parameter_id: UUID
    value: StrictJsonValue
    start_date: UtcDateTime
    end_date: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "PolicyParameterValueCommand":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class PolicyCreateCommand(StrictPolicyCommand):
    """Complete immutable content accepted from native and translated inputs."""

    country_id: CountryId
    tax_benefit_model_id: UUID
    parameter_values: Annotated[
        list[PolicyParameterValueCommand],
        Field(max_length=MAXIMUM_POLICY_PARAMETER_VALUES),
    ]

    @field_validator("parameter_values")
    @classmethod
    def reject_duplicate_effective_values(
        cls,
        values: list[PolicyParameterValueCommand],
    ) -> list[PolicyParameterValueCommand]:
        identities: set[tuple[UUID, datetime]] = set()
        for value in values:
            identity = (value.parameter_id, value.start_date)
            if identity in identities:
                raise ValueError(
                    "parameter_values must not repeat a parameter_id/start_date"
                )
            identities.add(identity)
        return values


class NativePolicyCreateCommand(PolicyCreateCommand):
    """Native content plus its optional catalog-version selection."""

    policyengine_version: PolicyEngineVersion | None = None


class ResolvedPolicyCreateCommand(PolicyCreateCommand):
    """Validated content bound to one exact initialized catalog version."""

    policyengine_version: PolicyEngineVersion
    tax_benefit_model_version_id: UUID
