"""Catalog resolution and validation for immutable v2 policy commands."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.catalog.catalog_selection import select_catalog
from policyengine_api.data.v2.models import Parameter
from policyengine_api.services.v2.policies.commands import (
    PolicyCreateCommand,
    ResolvedPolicyCreateCommand,
)


class PolicyCatalogValidationError(ValueError):
    """Raised when policy content does not belong to the selected catalog."""


def _version_parameter_ids(
    session: Session,
    *,
    model_version_id: UUID,
    requested_ids: set[UUID],
) -> set[UUID]:
    if not requested_ids:
        return set()
    return set(
        session.exec(
            select(Parameter.id).where(
                Parameter.tax_benefit_model_version_id == model_version_id,
                col(Parameter.id).in_(requested_ids),
            )
        ).all()
    )


def resolve_policy_catalog(
    session: Session,
    command: PolicyCreateCommand,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> ResolvedPolicyCreateCommand:
    """Bind validated content to one exact initialized catalog."""

    selected = select_catalog(
        session,
        country_id=command.country_id,
        running_policyengine_version=running_policyengine_version,
        policyengine_version=policyengine_version,
    )
    if command.tax_benefit_model_id != selected.model.id:
        raise PolicyCatalogValidationError(
            "tax_benefit_model_id does not match the selected country catalog"
        )

    requested_parameter_ids = {value.parameter_id for value in command.parameter_values}
    resolved_parameter_ids = _version_parameter_ids(
        session,
        model_version_id=selected.model_version.id,
        requested_ids=requested_parameter_ids,
    )
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
