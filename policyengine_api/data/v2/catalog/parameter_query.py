"""Parameter, parameter-tree, and canonical parameter-value queries."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.catalog.parameter_tree_query import (
    parameter_children_from_rows,
    parameter_children_query,
)
from policyengine_api.data.v2.catalog.query_support import (
    MetadataResourceNotFoundError,
    escape_like,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataCanonicalParameterValue,
    MetadataDetailResult,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
)
from policyengine_api.data.v2.models import Parameter, ParameterValue


def _parameter(parameter: Parameter) -> MetadataParameterSummary:
    return MetadataParameterSummary(
        id=parameter.id,
        name=parameter.name,
        label=parameter.label,
        description=parameter.description,
        data_type=parameter.data_type,
        unit=parameter.unit,
    )


def _parameter_value(value: ParameterValue) -> MetadataCanonicalParameterValue:
    return MetadataCanonicalParameterValue(
        id=value.id,
        parameter_id=value.parameter_id,
        value=value.value_json,
        start_date=value.start_date,
        end_date=value.end_date,
    )


def _utc_day_start(selected_time: datetime) -> datetime:
    if selected_time.tzinfo is None:
        selected_time = selected_time.replace(tzinfo=timezone.utc)
    return selected_time.astimezone(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def list_parameters(
    session: Session,
    selected: SelectedCatalog,
    *,
    offset: int,
    limit: int,
    search: str | None,
) -> MetadataPageResult[MetadataParameterSummary]:
    statement = select(Parameter).where(
        Parameter.tax_benefit_model_version_id == selected.model_version.id
    )
    if search:
        pattern = f"%{escape_like(search)}%"
        statement = statement.where(
            sa.or_(
                Parameter.name.ilike(pattern, escape="\\"),
                Parameter.label.ilike(pattern, escape="\\"),
                Parameter.description.ilike(pattern, escape="\\"),
            )
        )
    rows = query_rows(
        session,
        statement.order_by(Parameter.name).offset(offset).limit(limit + 1),
    )
    return page_result(
        selected,
        [_parameter(row) for row in rows],
        offset=offset,
        limit=limit,
    )


def get_parameter(
    session: Session,
    selected: SelectedCatalog,
    parameter_id: UUID,
) -> MetadataDetailResult[MetadataParameterSummary]:
    rows = query_rows(
        session,
        select(Parameter).where(
            Parameter.id == parameter_id,
            Parameter.tax_benefit_model_version_id == selected.model_version.id,
        ),
    )
    if not rows:
        raise MetadataResourceNotFoundError(f"parameter {parameter_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_parameter(rows[0]),
    )


def list_parameter_children(
    session: Session,
    selected: SelectedCatalog,
    *,
    parent_path: str,
    offset: int,
    limit: int,
) -> MetadataPageResult[MetadataParameterChild]:
    rows = query_rows(
        session,
        parameter_children_query(
            model_version_id=selected.model_version.id,
            parent_path=parent_path,
            dialect=session.get_bind().dialect.name,
            offset=offset,
            limit=limit,
        ),
    )
    return page_result(
        selected,
        parameter_children_from_rows(rows),
        offset=offset,
        limit=limit,
    )


def list_parameter_values(
    session: Session,
    selected: SelectedCatalog,
    *,
    parameter_id: UUID | None,
    current: bool,
    offset: int,
    limit: int,
    now: datetime | None,
) -> MetadataPageResult[MetadataCanonicalParameterValue]:
    statement = (
        select(ParameterValue)
        .join(Parameter, Parameter.id == ParameterValue.parameter_id)
        .where(
            Parameter.tax_benefit_model_version_id == selected.model_version.id,
            ParameterValue.policy_id.is_(None),
            ParameterValue.dynamic_id.is_(None),
        )
    )
    if parameter_id is not None:
        statement = statement.where(ParameterValue.parameter_id == parameter_id)
    if current:
        selected_day = _utc_day_start(now or datetime.now(timezone.utc))
        statement = statement.where(
            ParameterValue.start_date <= selected_day,
            sa.or_(
                ParameterValue.end_date.is_(None),
                ParameterValue.end_date >= selected_day,
            ),
        )
    rows = query_rows(
        session,
        statement.order_by(
            Parameter.name,
            ParameterValue.start_date.desc(),
            ParameterValue.id,
        )
        .offset(offset)
        .limit(limit + 1),
    )
    return page_result(
        selected,
        [_parameter_value(row) for row in rows],
        offset=offset,
        limit=limit,
    )


def get_parameter_value(
    session: Session,
    selected: SelectedCatalog,
    value_id: UUID,
) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
    rows = query_rows(
        session,
        select(ParameterValue)
        .join(Parameter, Parameter.id == ParameterValue.parameter_id)
        .where(
            ParameterValue.id == value_id,
            Parameter.tax_benefit_model_version_id == selected.model_version.id,
            ParameterValue.policy_id.is_(None),
            ParameterValue.dynamic_id.is_(None),
        ),
    )
    if not rows:
        raise MetadataResourceNotFoundError(f"parameter value {value_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_parameter_value(rows[0]),
    )
