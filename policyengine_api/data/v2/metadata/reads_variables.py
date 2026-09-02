"""Variable metadata database reads."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlmodel import col, select
from policyengine_api.data.v2.metadata.reads import (
    MetadataReadContext,
    MetadataResourceNotFoundError,
    escape_like,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.metadata.reads import (
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


class VariableReadMethods(MetadataReadContext):
    """Read variables from the selected catalog."""

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataVariable]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        statement = select(Variable).where(
            col(Variable.tax_benefit_model_version_id) == selected.model_version.id
        )
        if search:
            pattern = f"%{escape_like(search)}%"
            statement = statement.where(
                sa.or_(
                    col(Variable.name).ilike(pattern, escape="\\"),
                    col(Variable.label).ilike(pattern, escape="\\"),
                    col(Variable.description).ilike(pattern, escape="\\"),
                )
            )
        rows = query_rows(
            self._session,
            statement.order_by(col(Variable.name)).offset(offset).limit(limit + 1),
        )
        return page_result(
            selected,
            [_variable(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataVariable]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = query_rows(
            self._session,
            select(Variable).where(
                col(Variable.id) == variable_id,
                col(Variable.tax_benefit_model_version_id) == selected.model_version.id,
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"variable {variable_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_variable(rows[0]),
        )
