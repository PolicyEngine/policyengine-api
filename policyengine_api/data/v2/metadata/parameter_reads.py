"""Parameter and canonical parameter-value metadata database reads."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import col, select
from policyengine_api.data.v2.metadata.parameter_tree_reads import (
    parameter_children_from_rows,
    parameter_children_query,
)
from policyengine_api.data.v2.metadata.read_support import (
    MetadataReadContext,
    MetadataResourceNotFoundError,
    escape_like,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.metadata.read_models import (
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


class ParameterReadMethods(MetadataReadContext):
    """Read parameters and canonical values from the selected catalog."""

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        statement = select(Parameter).where(
            col(Parameter.tax_benefit_model_version_id) == selected.model_version.id
        )
        if search:
            pattern = f"%{escape_like(search)}%"
            statement = statement.where(
                sa.or_(
                    col(Parameter.name).ilike(pattern, escape="\\"),
                    col(Parameter.label).ilike(pattern, escape="\\"),
                    col(Parameter.description).ilike(pattern, escape="\\"),
                )
            )
        rows = query_rows(
            self._session,
            statement.order_by(col(Parameter.name)).offset(offset).limit(limit + 1),
        )
        return page_result(
            selected,
            [_parameter(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = query_rows(
            self._session,
            select(Parameter).where(
                col(Parameter.id) == parameter_id,
                col(Parameter.tax_benefit_model_version_id)
                == selected.model_version.id,
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(
                f"parameter {parameter_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_parameter(rows[0]),
        )

    def list_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parent_path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataParameterChild]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        rows = query_rows(
            self._session,
            parameter_children_query(
                model_version_id=selected.model_version.id,
                parent_path=parent_path,
                dialect=self._session.get_bind().dialect.name,
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
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parameter_id: UUID | None = None,
        current: bool = False,
        offset: int = 0,
        limit: int = 100,
        now: datetime | None = None,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        statement = (
            select(ParameterValue)
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(
                col(Parameter.tax_benefit_model_version_id)
                == selected.model_version.id,
                col(ParameterValue.policy_id).is_(None),
                col(ParameterValue.dynamic_id).is_(None),
            )
        )
        if parameter_id is not None:
            statement = statement.where(
                col(ParameterValue.parameter_id) == parameter_id
            )
        if current:
            selected_day = _utc_day_start(now or datetime.now(timezone.utc))
            statement = statement.where(
                col(ParameterValue.start_date) <= selected_day,
                sa.or_(
                    col(ParameterValue.end_date).is_(None),
                    col(ParameterValue.end_date) >= selected_day,
                ),
            )
        rows = query_rows(
            self._session,
            statement.order_by(
                col(Parameter.name),
                col(ParameterValue.start_date).desc(),
                col(ParameterValue.id),
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
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = query_rows(
            self._session,
            select(ParameterValue)
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(
                col(ParameterValue.id) == value_id,
                col(Parameter.tax_benefit_model_version_id)
                == selected.model_version.id,
                col(ParameterValue.policy_id).is_(None),
                col(ParameterValue.dynamic_id).is_(None),
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(
                f"parameter value {value_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_parameter_value(rows[0]),
        )
