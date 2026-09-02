"""Database-independent validation for v2 policy operations."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import TYPE_CHECKING, Any
from uuid import UUID

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.models import LegacyPolicyMapping

if TYPE_CHECKING:
    from policyengine_api.services.v2.policies.types import (
        PolicyCreationInput,
        ResolvedPolicyCreationInput,
    )


MAXIMUM_POLICY_PARAMETER_VALUES = 1_000
MAXIMUM_JSON_NESTING = 100


class PolicyCatalogValidationError(ValueError):
    """Raised when policy content does not belong to the selected catalog."""


class PolicyNotFoundError(LookupError):
    """Raised when a policy UUID is absent from the selected country."""


class PolicyCreationIntegrityError(RuntimeError):
    """Raised when stored policy content cannot support safe deduplication."""


class PolicyContentHashCollisionError(PolicyCreationIntegrityError):
    """Raised when equal version/hash keys identify different canonical bytes."""


class LegacyPolicyMappingIntegrityError(RuntimeError):
    """Raised when one immutable v1 identity maps inconsistently."""


class LegacyPolicyTranslationError(ValueError):
    """Raised when committed v1 content cannot be interpreted exactly."""


def require_json_value(
    value: Any,
    *,
    depth: int = 0,
    containers: frozenset[int] = frozenset(),
) -> Any:
    """Reject values that cannot be represented as standards-compliant JSON."""

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
            require_json_value(item, depth=depth + 1, containers=nested_containers)
        return value
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("JSON object keys must be strings")
        require_json_value(item, depth=depth + 1, containers=nested_containers)
    return value


def normalize_utc(value: datetime) -> datetime:
    """Require a time-zone-aware value and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("effective dates must include a UTC offset")
    return value.astimezone(timezone.utc)


def validate_policy_catalog(
    policy_input: "PolicyCreationInput",
    *,
    selected: SelectedCatalog,
    resolved_parameter_ids: set[UUID],
) -> "ResolvedPolicyCreationInput":
    """Validate preloaded catalog records and bind them to policy content."""

    from policyengine_api.services.v2.policies.types import ResolvedPolicyCreationInput

    if policy_input.tax_benefit_model_id != selected.model.id:
        raise PolicyCatalogValidationError(
            "tax_benefit_model_id does not match the selected country catalog"
        )
    requested_parameter_ids = {
        value.parameter_id for value in policy_input.parameter_values
    }
    if resolved_parameter_ids != requested_parameter_ids:
        raise PolicyCatalogValidationError(
            "every parameter_id must belong to the selected model version"
        )
    return ResolvedPolicyCreationInput(
        country_id=policy_input.country_id,
        tax_benefit_model_id=selected.model.id,
        tax_benefit_model_version_id=selected.model_version.id,
        policyengine_version=selected.policyengine_version,
        parameter_values=policy_input.parameter_values,
    )


def verify_legacy_policy_mapping(
    mapping: LegacyPolicyMapping,
    *,
    source_policy_hash: str,
    expected_policy_id: UUID | None = None,
) -> None:
    """Validate an existing mapping without performing SQL."""

    if mapping.source_policy_hash != source_policy_hash:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy identity was presented with a different source hash"
        )
    if expected_policy_id is not None and mapping.policy_id != expected_policy_id:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping does not match translated immutable content"
        )
