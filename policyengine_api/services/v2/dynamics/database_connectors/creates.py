"""Database inserts used by immutable v2 dynamic operations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import Dynamic, DynamicParameterValue

if TYPE_CHECKING:
    from policyengine_api.services.v2.dynamics.types import (
        ResolvedDynamicCreationInput,
    )


def create_dynamic(
    session: Session,
    dynamic_input: ResolvedDynamicCreationInput,
    *,
    canonicalization_version: int,
    content_hash: str,
) -> UUID | None:
    """Insert a dynamic unless one with the same canonical version and hash exists.

    Return the new id, or None when the unique content-hash constraint made the
    insert a no-op; the caller then reads the existing row. Parameter values are
    inserted separately by create_dynamic_parameter_values.
    """
    dynamic_id = uuid4()
    statement = (
        insert(Dynamic)
        .values(
            id=dynamic_id,
            country_id=dynamic_input.country_id,
            tax_benefit_model_id=dynamic_input.tax_benefit_model_id,
            tax_benefit_model_version_id=dynamic_input.tax_benefit_model_version_id,
            canonicalization_version=canonicalization_version,
            content_hash=content_hash,
        )
        .on_conflict_do_nothing(constraint="uq_dynamics_canonicalization_content_hash")
        .returning(col(Dynamic.id))
    )
    return session.execute(statement).scalar_one_or_none()


def create_dynamic_parameter_values(
    session: Session,
    *,
    dynamic_id: UUID,
    dynamic_input: ResolvedDynamicCreationInput,
) -> None:
    """Insert a new dynamic's parameter values and flush them for later reads.

    Each value's ``parameter_id`` names a dynamic parameter, which
    ``resolve_dynamic_creation_input`` found in ``dynamic_parameters``.
    """
    session.add_all(
        [
            DynamicParameterValue(
                dynamic_id=dynamic_id,
                dynamic_parameter_id=value.parameter_id,
                value_json=value.value,
                start_date=value.start_date,
                end_date=value.end_date,
            )
            for value in dynamic_input.parameter_values
        ]
    )
    session.flush()
