"""Database selections used by immutable v2 dynamic operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Dynamic, Parameter, ParameterValue

if TYPE_CHECKING:
    from uuid import UUID


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


def read_dynamic_parameter_values(
    session: Session, dynamic_id: UUID
) -> list[ParameterValue]:
    """Return every parameter value stored for one dynamic, in no particular order."""
    return list(
        session.exec(
            select(ParameterValue).where(ParameterValue.dynamic_id == dynamic_id)
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
) -> list[tuple[ParameterValue, str]]:
    """Return the dynamics' values with parameter names, by name then start date."""
    if not dynamic_ids:
        return []
    return list(
        session.exec(
            select(ParameterValue, Parameter.name)
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(col(ParameterValue.dynamic_id).in_(dynamic_ids))
            .order_by(
                col(Parameter.name),
                col(ParameterValue.start_date),
                col(ParameterValue.id),
            )
        ).all()
    )
