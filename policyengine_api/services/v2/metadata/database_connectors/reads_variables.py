"""Database selections for variable metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Variable
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from uuid import UUID


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def read_variables(
    session: Session,
    *,
    model_version_id: UUID,
    offset: int,
    limit: int,
    search: str | None,
) -> list[Variable]:
    """Return a page of a model version's variables in name order.

    search matches name, label or description as a literal, case-insensitive
    substring. Fetch limit + 1 rows so the caller can tell whether another page
    exists.
    """
    statement = select(Variable).where(
        col(Variable.tax_benefit_model_version_id) == model_version_id
    )
    if search:
        pattern = f"%{_escape_like(search)}%"
        statement = statement.where(
            sa.or_(
                col(Variable.name).ilike(pattern, escape="\\"),
                col(Variable.label).ilike(pattern, escape="\\"),
                col(Variable.description).ilike(pattern, escape="\\"),
            )
        )
    return read_rows(
        session,
        statement.order_by(col(Variable.name)).offset(offset).limit(limit + 1),
    )


def read_variable(
    session: Session, *, model_version_id: UUID, variable_id: UUID
) -> Variable | None:
    """Return the model version's variable with variable_id, or None."""
    rows = read_rows(
        session,
        select(Variable).where(
            col(Variable.id) == variable_id,
            col(Variable.tax_benefit_model_version_id) == model_version_id,
        ),
    )
    return rows[0] if rows else None


def read_all_variables(session: Session, *, model_version_id: UUID) -> list[Variable]:
    """Return every variable of a model version in name order."""
    return read_rows(
        session,
        select(Variable)
        .where(col(Variable.tax_benefit_model_version_id) == model_version_id)
        .order_by(col(Variable.name)),
    )
