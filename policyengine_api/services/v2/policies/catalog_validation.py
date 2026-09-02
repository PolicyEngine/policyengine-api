"""Database-independent catalog validation for immutable v2 policies."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.services.v2.policies.commands import (
    PolicyCreateCommand,
    ResolvedPolicyCreateCommand,
)


class PolicyCatalogValidationError(ValueError):
    """Raised when policy content does not belong to the selected catalog."""


def validate_policy_catalog(
    command: PolicyCreateCommand,
    *,
    selected: SelectedCatalog,
    resolved_parameter_ids: set[UUID],
) -> ResolvedPolicyCreateCommand:
    """Validate preloaded catalog records and bind them to policy content."""

    if command.tax_benefit_model_id != selected.model.id:
        raise PolicyCatalogValidationError(
            "tax_benefit_model_id does not match the selected country catalog"
        )

    requested_parameter_ids = {value.parameter_id for value in command.parameter_values}
    if resolved_parameter_ids != requested_parameter_ids:
        raise PolicyCatalogValidationError(
            "every parameter_id must belong to the selected model version"
        )

    return ResolvedPolicyCreateCommand(
        country_id=command.country_id,
        tax_benefit_model_id=selected.model.id,
        tax_benefit_model_version_id=selected.model_version.id,
        policyengine_version=selected.policyengine_version,
        parameter_values=command.parameter_values,
    )
