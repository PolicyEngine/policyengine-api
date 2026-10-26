"""Database-independent validation for v2 policy operations."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Container, Iterable
    from uuid import UUID

    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
    from policyengine_api.data.v2.models import LegacyPolicyMapping
    from policyengine_api.services.v2.policies.types import (
        LegacyPolicyTranslationReason,
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
    """Raised when committed v1 content cannot be interpreted exactly.

    ``reason`` is a fixed code that copy failure logs record; the message is
    never logged.
    """

    def __init__(self, message: str, *, reason: LegacyPolicyTranslationReason) -> None:
        """Keep the message for debugging and the fixed reason for logs."""
        super().__init__(message)
        self.reason = reason


def parameters_missing_from_model(
    policy_parameter_names: Iterable[str],
    model_parameter_names: Container[str],
) -> tuple[str, ...]:
    """Return the parameter paths a policy sets that the model does not have.

    Each absent path appears once, in sorted order; an empty tuple means every
    path exists. The v2 copy of a v1 policy is refused when it is not empty.
    """
    return tuple(
        sorted(
            {
                name
                for name in policy_parameter_names
                if name not in model_parameter_names
            }
        )
    )


def require_json_value(
    value: Any,  # noqa: ANN401  # exact type() dispatch that mypy cannot narrow
    *,
    depth: int = 0,
    containers: frozenset[int] = frozenset(),
) -> object:
    """Reject values that cannot be represented as standards-compliant JSON."""
    if depth > MAXIMUM_JSON_NESTING:
        msg = "JSON values must not exceed 100 nested containers"
        raise ValueError(msg)
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            msg = "JSON numbers must be finite"
            raise ValueError(msg)
        return value
    if type(value) not in {list, dict}:
        msg = "value must contain only standards-compliant JSON types"
        raise ValueError(msg)
    _require_json_container(value, depth=depth, containers=containers)
    return value


def _require_json_container(
    container: list[Any] | dict[Any, Any],
    *,
    depth: int,
    containers: frozenset[int],
) -> None:
    """Check a JSON list's items or object's members, rejecting reference cycles.

    ``containers`` holds the identities of the containers enclosing this one.
    """
    identity = id(container)
    if identity in containers:
        msg = "JSON values must not contain reference cycles"
        raise ValueError(msg)
    nested_containers = containers | {identity}
    # The caller admits only exact lists and dicts, so isinstance is exact here.
    if isinstance(container, list):
        for item in container:
            require_json_value(item, depth=depth + 1, containers=nested_containers)
        return
    for key, item in container.items():
        if type(key) is not str:
            msg = "JSON object keys must be strings"
            raise ValueError(msg)
        require_json_value(item, depth=depth + 1, containers=nested_containers)


def normalize_utc(value: datetime) -> datetime:
    """Require a time-zone-aware value and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "effective dates must include a UTC offset"
        raise ValueError(msg)
    return value.astimezone(UTC)


def validate_policy_catalog(
    policy_input: PolicyCreationInput,
    *,
    selected: SelectedCatalog,
    resolved_parameter_ids: set[UUID],
) -> ResolvedPolicyCreationInput:
    """Validate preloaded catalog records and bind them to policy content."""
    from policyengine_api.services.v2.policies.types import (  # noqa: PLC0415  # types imports this module
        ResolvedPolicyCreationInput,
    )

    if policy_input.tax_benefit_model_id != selected.model.id:
        msg = "tax_benefit_model_id does not match the selected country catalog"
        raise PolicyCatalogValidationError(msg)
    requested_parameter_ids = {
        value.parameter_id for value in policy_input.parameter_values
    }
    if resolved_parameter_ids != requested_parameter_ids:
        msg = "every parameter_id must belong to the selected model version"
        raise PolicyCatalogValidationError(msg)
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
) -> None:
    """Require an existing mapping to come from the same v1 content, without SQL.

    v1 policies never change, so a mapping with the same source hash is the
    copy whichever catalog version translated it.
    """
    if mapping.source_policy_hash != source_policy_hash:
        msg = "legacy policy identity was presented with a different source hash"
        raise LegacyPolicyMappingIntegrityError(msg)
