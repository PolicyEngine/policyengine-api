"""Database selections used by immutable v2 dynamic operations.

A dynamic's values are ``dynamic_parameter_values`` rows, and the parameters
it may set are ``dynamic_parameters`` rows (C1 · 50).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
)

if TYPE_CHECKING:
    from uuid import UUID

# Parameter names bound in one statement; far below PostgreSQL's 65,535 limit.
DYNAMIC_PARAMETER_NAME_BATCH_SIZE = 1_000


def read_dynamic_by_content_identity(
    session: Session, *, canonicalization_version: int, content_hash: str
) -> Dynamic | None:
    """Return the dynamic with this canonical version and content hash, or None."""
    return session.exec(
        select(Dynamic).where(
            Dynamic.canonicalization_version == canonicalization_version,
            Dynamic.content_hash == content_hash,
        )
    ).one_or_none()


def read_version_dynamic_parameter_names(
    session: Session, *, model_version_id: UUID, requested_ids: set[UUID]
) -> dict[UUID, str]:
    """Return the names of the requested dynamic parameters of this version, by id."""
    if not requested_ids:
        return {}
    return dict(
        session.exec(
            select(DynamicParameter.id, DynamicParameter.name).where(
                DynamicParameter.tax_benefit_model_version_id == model_version_id,
                col(DynamicParameter.id).in_(requested_ids),
            )
        ).all()
    )


def read_dynamic_parameters_by_name(
    session: Session, *, model_version_id: UUID, names: set[str]
) -> dict[str, DynamicParameter]:
    """Return this version's dynamic parameters with the given names, by name.

    The names are read in batches of DYNAMIC_PARAMETER_NAME_BATCH_SIZE, as
    a PostgreSQL statement takes at most 65,535 bound values.
    """
    ordered_names = sorted(names)
    found: dict[str, DynamicParameter] = {}
    for start in range(0, len(ordered_names), DYNAMIC_PARAMETER_NAME_BATCH_SIZE):
        batch = ordered_names[start : start + DYNAMIC_PARAMETER_NAME_BATCH_SIZE]
        parameters = session.exec(
            select(DynamicParameter).where(
                DynamicParameter.tax_benefit_model_version_id == model_version_id,
                col(DynamicParameter.name).in_(batch),
            )
        ).all()
        found.update((parameter.name, parameter) for parameter in parameters)
    return found


def read_dynamic_parameter_values(
    session: Session, dynamic_id: UUID
) -> list[DynamicParameterValue]:
    """Return every parameter value stored for one dynamic, in no particular order."""
    return list(
        session.exec(
            select(DynamicParameterValue).where(
                DynamicParameterValue.dynamic_id == dynamic_id
            )
        ).all()
    )


def read_dynamic_row(
    session: Session, *, country_id: str, dynamic_id: UUID
) -> Dynamic | None:
    """Return the dynamic with this id in this country, or None."""
    return session.exec(
        select(Dynamic).where(
            Dynamic.id == dynamic_id, Dynamic.country_id == country_id
        )
    ).one_or_none()


def read_dynamic_parameter_values_with_names(
    session: Session, dynamic_ids: list[UUID]
) -> list[tuple[DynamicParameterValue, str]]:
    """Return the dynamics' values with parameter names, by name then start date."""
    if not dynamic_ids:
        return []
    return list(
        session.exec(
            select(DynamicParameterValue, DynamicParameter.name)
            .join(
                DynamicParameter,
                col(DynamicParameter.id)
                == col(DynamicParameterValue.dynamic_parameter_id),
            )
            .where(col(DynamicParameterValue.dynamic_id).in_(dynamic_ids))
            .order_by(
                col(DynamicParameter.name),
                col(DynamicParameterValue.start_date),
                col(DynamicParameterValue.id),
            )
        ).all()
    )
