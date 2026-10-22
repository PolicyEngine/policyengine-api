"""Database selections for parameter and canonical-value metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Parameter, ParameterValue
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from policyengine_api.services.v2.metadata.types import (
        ParameterFilter,
        ParameterValueSelection,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def read_parameters(
    session: Session,
    *,
    model_version_id: UUID,
    offset: int,
    limit: int,
    parameter_filter: ParameterFilter,
) -> list[Parameter]:
    """Return a page of a model version's parameters in name order.

    The filter's search matches name, label or description as a literal,
    case-insensitive substring, and its names keep only parameters with those
    exact names. Fetch limit + 1 rows so the caller can tell whether another
    page exists.
    """
    statement = select(Parameter).where(
        col(Parameter.tax_benefit_model_version_id) == model_version_id
    )
    if parameter_filter.names is not None:
        statement = statement.where(
            col(Parameter.name).in_(sorted(parameter_filter.names))
        )
    search = parameter_filter.search
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


def read_parameters_by_name(
    session: Session, *, model_version_id: UUID, parameter_names: Collection[str]
) -> list[Parameter]:
    """Return the named parameters of a model version in name order.

    Names the version has no parameter for are absent.
    """
    if not parameter_names:
        return []
    return read_rows(
        session,
        select(Parameter)
        .where(
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
            col(Parameter.name).in_(sorted(parameter_names)),
        )
        .order_by(col(Parameter.name)),
    )


def read_parameter(
    session: Session, *, model_version_id: UUID, parameter_id: UUID
) -> Parameter | None:
    """Return the model version's parameter with parameter_id, or None."""
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
    selection: ParameterValueSelection,
    offset: int,
    limit: int,
) -> list[ParameterValue]:
    """Return a page of a model version's current-law parameter values.

    Values tied to a policy or dynamic are excluded. The selection's
    parameter_id keeps one parameter's values, its parameter_names the values
    of the parameters with those names, and its selected_day those in effect
    on that day. Rows are ordered by parameter name, then newest
    first, and limit + 1 are fetched so the caller can tell whether another
    page exists.
    """
    parameter_id = selection.parameter_id
    selected_day = selection.selected_day
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
    if selection.parameter_names is not None:
        statement = statement.where(
            col(Parameter.name).in_(sorted(selection.parameter_names))
        )
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
    """Return the model version's current-law value with value_id, or None."""
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


def read_current_law_values_by_parameter_name(
    session: Session, *, model_version_id: UUID, parameter_names: Collection[str]
) -> list[Any]:
    """Return the current-law values of the named parameters of a model version.

    Each row has the parameter's name, the value's value_json, start_date and
    end_date. Values tied to a policy or dynamic are excluded. Rows are ordered
    by parameter name, then start date.
    """
    if not parameter_names:
        return []
    return read_rows(
        session,
        select(
            col(Parameter.name),
            col(ParameterValue.value_json),
            col(ParameterValue.start_date),
            col(ParameterValue.end_date),
        )
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
            col(Parameter.name).in_(sorted(parameter_names)),
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
        .order_by(col(Parameter.name), col(ParameterValue.start_date)),
    )
