"""Pure representation transformations for v2 dynamic operations.

A dynamic's canonical bytes and content hash are a policy's
(``policies.transformations.canonicalize_policy``), so a dynamic needs no
canonicalization of its own.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING

from policyengine_api.services.v2.dynamics.types import (
    CheckedDynamicRead,
    DynamicRead,
    ResolvedDynamicCreationInput,
)
from policyengine_api.services.v2.policies.types import PolicyParameterValueRead

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import Dynamic, ParameterValue
    from policyengine_api.services.v2.policies.types import (
        ResolvedPolicyCreationInput,
    )


def dynamic_creation_input(
    content: ResolvedPolicyCreationInput,
) -> ResolvedDynamicCreationInput:
    """Return resolved content as a dynamic's; it must set at least one value."""
    return ResolvedDynamicCreationInput.model_validate(dict(content))


def dynamic_parameter_values_by_dynamic(
    dynamic_ids: list[UUID],
    rows: list[tuple[ParameterValue, str]],
) -> dict[UUID, tuple[PolicyParameterValueRead, ...]]:
    """Group named value rows by dynamic id; every requested dynamic gets an entry."""
    grouped: dict[UUID, list[PolicyParameterValueRead]] = {
        dynamic_id: [] for dynamic_id in dynamic_ids
    }
    for value, parameter_name in rows:
        if value.dynamic_id is None:
            continue
        grouped[value.dynamic_id].append(
            PolicyParameterValueRead(
                id=value.id,
                parameter_id=value.parameter_id,
                parameter_name=parameter_name,
                value=value.value_json,
                start_date=value.start_date,
                end_date=value.end_date,
            )
        )
    return {dynamic_id: tuple(values) for dynamic_id, values in grouped.items()}


def dynamic_read(
    dynamic: Dynamic,
    values: dict[UUID, tuple[PolicyParameterValueRead, ...]],
) -> DynamicRead:
    """Convert a stored dynamic and its grouped values to the service's read model."""
    return DynamicRead(
        id=dynamic.id,
        country_id=dynamic.country_id,
        tax_benefit_model_id=dynamic.tax_benefit_model_id,
        tax_benefit_model_version_id=dynamic.tax_benefit_model_version_id,
        created_at=dynamic.created_at,
        updated_at=dynamic.updated_at,
        parameter_values=values.get(dynamic.id, ()),
    )


def checked_dynamic_read(
    dynamic: DynamicRead, missing_parameters: tuple[str, ...] | None
) -> CheckedDynamicRead:
    """Return the dynamic read with the result of its missing-parameter check."""
    return CheckedDynamicRead(
        **{
            field.name: getattr(dynamic, field.name)
            for field in dataclass_fields(DynamicRead)
        },
        missing_parameters=missing_parameters,
    )
