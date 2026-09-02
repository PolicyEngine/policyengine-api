"""Database selections for variable metadata."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Variable
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows


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
    rows = read_rows(
        session,
        select(Variable).where(
            col(Variable.id) == variable_id,
            col(Variable.tax_benefit_model_version_id) == model_version_id,
        ),
    )
    return rows[0] if rows else None
