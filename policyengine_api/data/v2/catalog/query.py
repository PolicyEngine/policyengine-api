"""Read-only v2 catalog queries and deterministic response serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from policyengine_api.dataset_display import get_dataset_display_label
from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    SelectedCatalog,
    UnsupportedPreviewCountryError,
    select_catalog,
    validate_policyengine_version,
)
from policyengine_api.data.v2.catalog.parameter_tree_query import (
    parameter_children_from_rows,
    parameter_children_query,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataRegionOption,
    MetadataTimePeriodOption,
    MetadataVariable,
)
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterValue,
    Region,
    Variable,
)


__all__ = [
    "InvalidMetadataPageError",
    "InvalidPolicyEngineVersionError",
    "MetadataCatalogUnavailableError",
    "MetadataCatalogVersionNotFoundError",
    "MetadataResourceNotFoundError",
    "UnsupportedPreviewCountryError",
    "V2MetadataQueryService",
    "validate_metadata_page",
    "validate_policyengine_version",
]


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


ResourceT = TypeVar("ResourceT")


def _page(
    selected: SelectedCatalog,
    rows: list[ResourceT],
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[ResourceT]:
    return MetadataPageResult(
        policyengine_version=selected.policyengine_version,
        items=rows[:limit],
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def validate_metadata_page(offset: int, limit: int) -> tuple[int, int]:
    if offset < 0:
        raise InvalidMetadataPageError("offset must be at least 0")
    if not 1 <= limit <= 500:
        raise InvalidMetadataPageError("limit must be between 1 and 500")
    return offset, limit


def _metadata_model(selected: SelectedCatalog) -> MetadataModel:
    return MetadataModel(
        id=selected.model.id,
        name=selected.model.name,
        description=selected.model_version.description,
    )


def _metadata_model_version(selected: SelectedCatalog) -> MetadataModelVersionDetail:
    return MetadataModelVersionDetail(
        id=selected.model_version.id,
        model_id=selected.model.id,
        version=selected.model_version.version,
        description=selected.model_version.description,
        current_law_id=selected.model_version.current_law_id,
        metadata_time_periods=selected.model_version.metadata_time_periods,
    )


def _metadata_variable(variable: Variable) -> MetadataVariable:
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


def _metadata_parameter(parameter: Parameter) -> MetadataParameterSummary:
    return MetadataParameterSummary(
        id=parameter.id,
        name=parameter.name,
        label=parameter.label,
        description=parameter.description,
        data_type=parameter.data_type,
        unit=parameter.unit,
    )


def _metadata_parameter_value(
    value: ParameterValue,
) -> MetadataCanonicalParameterValue:
    return MetadataCanonicalParameterValue(
        id=value.id,
        parameter_id=value.parameter_id,
        value=value.value_json,
        start_date=value.start_date,
        end_date=value.end_date,
    )


def _metadata_dataset(dataset: Dataset) -> MetadataDataset:
    return MetadataDataset(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        year=dataset.year,
    )


def _metadata_region(region: Region) -> MetadataRegion:
    return MetadataRegion(
        id=region.id,
        code=region.code,
        label=region.label,
        region_type=region.region_type.value,
        requires_filter=region.requires_filter,
        filter_field=region.filter_field,
        filter_value=region.filter_value,
        filter_strategy=region.filter_strategy,
        parent_code=region.parent_code,
        state_code=region.state_code,
        state_name=region.state_name,
        default_dataset_id=region.default_dataset_id,
    )


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class V2MetadataQueryService:
    """Assemble preview metadata using only an injected v2 read session."""

    def __init__(self, session: Session, *, running_policyengine_version: str):
        self._session = session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
        """Close the request-owned read session."""

        self._session.close()

    def select_catalog(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> SelectedCatalog:
        """Select exactly one initialized country catalog."""

        return select_catalog(
            self._session,
            country_id=country_id,
            running_policyengine_version=self._running_policyengine_version,
            policyengine_version=policyengine_version,
        )

    def _resource_rows(self, statement: object) -> list:
        try:
            return list(self._session.exec(statement).all())
        except SQLAlchemyError as error:
            raise MetadataCatalogUnavailableError(
                "the v2 metadata catalog cannot be queried"
            ) from error

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        rows = [_metadata_model(selected)] if offset == 0 else []
        return _page(selected, rows, offset=offset, limit=limit)

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        selected = self.select_catalog(country_id, policyengine_version)
        if selected.model.id != model_id:
            raise MetadataResourceNotFoundError(f"model {model_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_model(selected),
        )

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResult:
        selected = self.select_catalog(country_id, policyengine_version)
        return MetadataModelSelectionResult(
            policyengine_version=selected.policyengine_version,
            model=_metadata_model(selected),
            model_version=_metadata_model_version(selected),
        )

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        rows = [_metadata_model_version(selected)] if offset == 0 else []
        return _page(selected, rows, offset=offset, limit=limit)

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        selected = self.select_catalog(country_id, policyengine_version)
        if selected.model_version.id != version_id:
            raise MetadataResourceNotFoundError(
                f"model version {version_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_model_version(selected),
        )

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataVariable]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        statement = select(Variable).where(
            Variable.tax_benefit_model_version_id == selected.model_version.id
        )
        if search:
            pattern = f"%{_escaped_like(search)}%"
            statement = statement.where(
                sa.or_(
                    Variable.name.ilike(pattern, escape="\\"),
                    Variable.label.ilike(pattern, escape="\\"),
                    Variable.description.ilike(pattern, escape="\\"),
                )
            )
        rows = self._resource_rows(
            statement.order_by(Variable.name).offset(offset).limit(limit + 1)
        )
        return _page(
            selected,
            [_metadata_variable(row) for row in rows],
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
        rows = self._resource_rows(
            select(Variable).where(
                Variable.id == variable_id,
                Variable.tax_benefit_model_version_id == selected.model_version.id,
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"variable {variable_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_variable(rows[0]),
        )

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        statement = select(Parameter).where(
            Parameter.tax_benefit_model_version_id == selected.model_version.id
        )
        if search:
            pattern = f"%{_escaped_like(search)}%"
            statement = statement.where(
                sa.or_(
                    Parameter.name.ilike(pattern, escape="\\"),
                    Parameter.label.ilike(pattern, escape="\\"),
                    Parameter.description.ilike(pattern, escape="\\"),
                )
            )
        rows = self._resource_rows(
            statement.order_by(Parameter.name).offset(offset).limit(limit + 1)
        )
        return _page(
            selected,
            [_metadata_parameter(row) for row in rows],
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
        rows = self._resource_rows(
            select(Parameter).where(
                Parameter.id == parameter_id,
                Parameter.tax_benefit_model_version_id == selected.model_version.id,
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(
                f"parameter {parameter_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_parameter(rows[0]),
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
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        rows = self._resource_rows(
            parameter_children_query(
                model_version_id=selected.model_version.id,
                parent_path=parent_path,
                dialect=self._session.get_bind().dialect.name,
                offset=offset,
                limit=limit,
            )
        )
        return _page(
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
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
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
            selected_time = now or datetime.now(timezone.utc)
            if selected_time.tzinfo is None:
                selected_time = selected_time.replace(tzinfo=timezone.utc)
            selected_day = selected_time.astimezone(timezone.utc).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            statement = statement.where(
                ParameterValue.start_date <= selected_day,
                sa.or_(
                    ParameterValue.end_date.is_(None),
                    ParameterValue.end_date >= selected_day,
                ),
            )
        rows = self._resource_rows(
            statement.order_by(
                Parameter.name,
                ParameterValue.start_date.desc(),
                ParameterValue.id,
            )
            .offset(offset)
            .limit(limit + 1)
        )
        return _page(
            selected,
            [_metadata_parameter_value(row) for row in rows],
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
        rows = self._resource_rows(
            select(ParameterValue)
            .join(Parameter, Parameter.id == ParameterValue.parameter_id)
            .where(
                ParameterValue.id == value_id,
                Parameter.tax_benefit_model_version_id == selected.model_version.id,
                ParameterValue.policy_id.is_(None),
                ParameterValue.dynamic_id.is_(None),
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(
                f"parameter value {value_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_parameter_value(rows[0]),
        )

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        rows = self._resource_rows(
            select(Dataset)
            .where(
                Dataset.tax_benefit_model_version_id == selected.model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            )
            .order_by(Dataset.name)
            .offset(offset)
            .limit(limit + 1)
        )
        return _page(
            selected,
            [_metadata_dataset(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = self._resource_rows(
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.tax_benefit_model_version_id == selected.model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"dataset {dataset_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_dataset(rows[0]),
        )

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataRegion]:
        validate_metadata_page(offset, limit)
        selected = self.select_catalog(country_id, policyengine_version)
        statement = select(Region).where(
            Region.tax_benefit_model_version_id == selected.model_version.id
        )
        if region_type is not None:
            statement = statement.where(Region.region_type == region_type)
        rows = self._resource_rows(
            statement.order_by(Region.code).offset(offset).limit(limit + 1)
        )
        return _page(
            selected,
            [_metadata_region(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = self._resource_rows(
            select(Region).where(
                Region.id == region_id,
                Region.tax_benefit_model_version_id == selected.model_version.id,
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"region {region_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_region(rows[0]),
        )

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = self._resource_rows(
            select(Region).where(
                Region.code == region_code,
                Region.tax_benefit_model_version_id == selected.model_version.id,
            )
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"region {region_code!r} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_metadata_region(rows[0]),
        )

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResult:
        selected = self.select_catalog(country_id, policyengine_version)
        regions = self._resource_rows(
            select(Region)
            .where(Region.tax_benefit_model_version_id == selected.model_version.id)
            .order_by(Region.code)
        )
        national_region = next(
            (region for region in regions if region.code == country_id),
            None,
        )
        if national_region is None:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} national v2 region is absent"
            )
        datasets = self._resource_rows(
            select(Dataset).where(
                Dataset.id == national_region.default_dataset_id,
                Dataset.tax_benefit_model_version_id == selected.model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            )
        )
        if len(datasets) != 1:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} national v2 dataset is absent"
            )
        time_periods = selected.model_version.metadata_time_periods
        if (
            not isinstance(selected.model_version.current_law_id, int)
            or not isinstance(time_periods, list)
            or not time_periods
            or any(not isinstance(year, int) for year in time_periods)
        ):
            raise MetadataCatalogUnavailableError(
                f"the {country_id} v2 model-version options are incomplete"
            )
        national_dataset = datasets[0]
        return MetadataEconomyOptionsResult(
            policyengine_version=selected.policyengine_version,
            current_law_id=selected.model_version.current_law_id,
            region=[
                MetadataRegionOption(
                    name=region.code,
                    label=region.label,
                    type=region.region_type.value,
                )
                for region in regions
            ],
            time_period=[
                MetadataTimePeriodOption(name=year, label=str(year))
                for year in time_periods
            ],
            datasets=[
                MetadataDatasetOption(
                    name=national_dataset.name,
                    label=get_dataset_display_label(national_dataset.name),
                )
            ],
        )
