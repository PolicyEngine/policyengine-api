"""Variable metadata queries."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.catalog.query_support import (
    MetadataResourceNotFoundError,
    escape_like,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataDetailResult,
    MetadataPageResult,
    MetadataVariable,
)
from policyengine_api.data.v2.models import Variable


def _variable(variable: Variable) -> MetadataVariable:
    return MetadataVariable(
        id=variable.id,
        name=variable.name,
        label=variable.label,
        entity=variable.entity,
        description=variable.description,
        data_type=variable.data_type,
        possible_values=variable.possible_values,
        default_value=variable.default_value,
        adds=variable.adds,
        subtracts=variable.subtracts,
    )


def list_variables(
    session: Session,
    selected: SelectedCatalog,
    *,
    offset: int,
    limit: int,
    search: str | None,
) -> MetadataPageResult[MetadataVariable]:
    statement = select(Variable).where(
        Variable.tax_benefit_model_version_id == selected.model_version.id
    )
    if search:
        pattern = f"%{escape_like(search)}%"
        statement = statement.where(
            sa.or_(
                Variable.name.ilike(pattern, escape="\\"),
                Variable.label.ilike(pattern, escape="\\"),
                Variable.description.ilike(pattern, escape="\\"),
            )
        )
    rows = query_rows(
        session,
        statement.order_by(Variable.name).offset(offset).limit(limit + 1),
    )
    return page_result(
        selected,
        [_variable(row) for row in rows],
        offset=offset,
        limit=limit,
    )


def get_variable(
    session: Session,
    selected: SelectedCatalog,
    variable_id: UUID,
) -> MetadataDetailResult[MetadataVariable]:
    rows = query_rows(
        session,
        select(Variable).where(
            Variable.id == variable_id,
            Variable.tax_benefit_model_version_id == selected.model_version.id,
        ),
    )
    if not rows:
        raise MetadataResourceNotFoundError(f"variable {variable_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_variable(rows[0]),
    )
