"""Database selections for parameter and canonical-value metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.data.v2.models import Parameter, ParameterValue
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows
from policyengine_api.services.v2.metadata.types import MetadataCatalogParameterRow

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from uuid import UUID

CATALOG_VALUE_BATCH_SIZE = 10_000


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
    """Return a page of a model version's parameters in name order.

    search matches name, label or description as a literal, case-insensitive
    substring. Fetch limit + 1 rows so the caller can tell whether another page
    exists.
    """
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
    parameter_id: UUID | None,
    selected_day: datetime | None,
    offset: int,
    limit: int,
) -> list[ParameterValue]:
    """Return a page of a model version's current-law parameter values.

    Values tied to a policy or dynamic are excluded. parameter_id keeps one
    parameter's values and selected_day keeps those in effect on that day. Rows
    are ordered by parameter name, then newest first, and limit + 1 are fetched
    so the caller can tell whether another page exists.
    """
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


def read_all_parameter_rows(
    session: Session, *, model_version_id: UUID
) -> list[MetadataCatalogParameterRow]:
    """Return every parameter of a model version, without values, in name order."""
    rows = read_rows(
        session,
        sa.select(
            col(Parameter.id),
            col(Parameter.name),
            col(Parameter.label),
            col(Parameter.description),
            col(Parameter.data_type),
            col(Parameter.unit),
            col(Parameter.metadata_label),
            col(Parameter.period),
            col(Parameter.economy),
            col(Parameter.household),
        )
        .where(col(Parameter.tax_benefit_model_version_id) == model_version_id)
        .order_by(col(Parameter.name)),
    )
    return [MetadataCatalogParameterRow(*row) for row in rows]


def iter_canonical_parameter_values(
    session: Session, *, model_version_id: UUID
) -> Iterator[tuple[UUID, datetime, Any]]:
    """Yield every current-law value of a model version as it is read.

    Each item is (parameter_id, start_date, value). A parameter's values are
    consecutive and oldest first. Rows are fetched in batches, so the whole
    set is never held at once. Raise MetadataCatalogUnavailableError when the
    database query fails.
    """
    statement = (
        select(
            ParameterValue.parameter_id,
            ParameterValue.start_date,
            ParameterValue.value_json,
        )
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(
            col(Parameter.tax_benefit_model_version_id) == model_version_id,
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
        .order_by(col(ParameterValue.parameter_id), col(ParameterValue.start_date))
        .execution_options(yield_per=CATALOG_VALUE_BATCH_SIZE)
    )
    try:
        yield from session.exec(statement)
    except SQLAlchemyError as error:
        msg = "the v2 metadata catalog cannot be queried"
        raise MetadataCatalogUnavailableError(msg) from error
