"""Region and economy-option metadata database reads."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import col, select

from policyengine_api.dataset_display import get_dataset_display_label
from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.data.v2.metadata.query_support import (
    MetadataQueryContext,
    MetadataResourceNotFoundError,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.metadata.read_models import (
    MetadataDatasetOption,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataPageResult,
    MetadataRegion,
    MetadataRegionOption,
    MetadataRegionType,
    MetadataTimePeriodOption,
)
from policyengine_api.data.v2.models import Dataset, Region


def _region(region: Region) -> MetadataRegion:
    return MetadataRegion(
        id=region.id,
        code=region.code,
        label=region.label,
        region_type=MetadataRegionType(region.region_type.value),
        requires_filter=region.requires_filter,
        filter_field=region.filter_field,
        filter_value=region.filter_value,
        filter_strategy=region.filter_strategy,
        parent_code=region.parent_code,
        state_code=region.state_code,
        state_name=region.state_name,
        default_dataset_id=region.default_dataset_id,
    )


class RegionQueryMethods(MetadataQueryContext):
    """Read regions and economy options from the selected catalog."""

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataRegion]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        statement = select(Region).where(
            col(Region.tax_benefit_model_version_id) == selected.model_version.id
        )
        if region_type is not None:
            statement = statement.where(col(Region.region_type) == region_type)
        rows = query_rows(
            self._session,
            statement.order_by(col(Region.code)).offset(offset).limit(limit + 1),
        )
        return page_result(
            selected,
            [_region(row) for row in rows],
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
        rows = query_rows(
            self._session,
            select(Region).where(
                col(Region.id) == region_id,
                col(Region.tax_benefit_model_version_id) == selected.model_version.id,
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"region {region_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_region(rows[0]),
        )

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = query_rows(
            self._session,
            select(Region).where(
                col(Region.code) == region_code,
                col(Region.tax_benefit_model_version_id) == selected.model_version.id,
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"region {region_code!r} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_region(rows[0]),
        )

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResult:
        selected = self.select_catalog(country_id, policyengine_version)
        regions = query_rows(
            self._session,
            select(Region)
            .where(
                col(Region.tax_benefit_model_version_id) == selected.model_version.id
            )
            .order_by(col(Region.code)),
        )
        national_region = next(
            (region for region in regions if region.code == country_id),
            None,
        )
        if national_region is None:
            raise MetadataCatalogUnavailableError(
                f"the {country_id} national v2 region is absent"
            )
        datasets = query_rows(
            self._session,
            select(Dataset).where(
                col(Dataset.id) == national_region.default_dataset_id,
                col(Dataset.tax_benefit_model_version_id) == selected.model_version.id,
                col(Dataset.is_output_dataset).is_(False),
                col(Dataset.storage_path).is_(None),
            ),
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
                    type=MetadataRegionType(region.region_type.value),
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
