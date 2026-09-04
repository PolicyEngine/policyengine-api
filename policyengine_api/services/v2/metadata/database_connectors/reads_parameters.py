"""Database selections for parameter and canonical-value metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Parameter, ParameterValue
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def read_parameters(
    session: Session,
    *,
    model_version_id: UUID,
    offset: int,
    limit: int,
    search: str | None,
) -> list[Parameter]:
    statement = select(Parameter).where(
        col(Parameter.tax_benefit_model_version_id) == model_version_id
    )
    if search:
        pattern = f"%{_escape_like(search)}%"
        statement = statement.where(
            sa.or_(
                col(Parameter.name).ilike(pattern, escape="\\"),
                col(Parameter.label).ilike(pattern, escape="\\"),
                col(Parameter.description).ilike(pattern, escape="\\"),
            )
        )
    return read_rows(
        session,
        statement.order_by(col(Parameter.name)).offset(offset).limit(limit + 1),
    )


def read_parameter(
    session: Session, *, model_version_id: UUID, parameter_id: UUID
) -> Parameter | None:
    rows = read_rows(
        session,
        select(Parameter).where(
            col(Parameter.id) == parameter_id,
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
        ),
    )
    return rows[0] if rows else None


def read_parameter_values(
    session: Session,
    *,
    model_version_id: UUID,
    parameter_id: UUID | None,
    selected_day: datetime | None,
    offset: int,
    limit: int,
) -> list[ParameterValue]:
    statement = (
        select(ParameterValue)
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
    )
    if parameter_id is not None:
        statement = statement.where(col(ParameterValue.parameter_id) == parameter_id)
    if selected_day is not None:
        statement = statement.where(
            col(ParameterValue.start_date) <= selected_day,
            sa.or_(
                col(ParameterValue.end_date).is_(None),
                col(ParameterValue.end_date) >= selected_day,
            ),
        )
    return read_rows(
        session,
        statement.order_by(
            col(Parameter.name),
            col(ParameterValue.start_date).desc(),
            col(ParameterValue.id),
        )
        .offset(offset)
        .limit(limit + 1),
    )


def read_parameter_value(
    session: Session, *, model_version_id: UUID, value_id: UUID
) -> ParameterValue | None:
    rows = read_rows(
        session,
        select(ParameterValue)
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(
            col(ParameterValue.id) == value_id,
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        ),
    )
    return rows[0] if rows else None
