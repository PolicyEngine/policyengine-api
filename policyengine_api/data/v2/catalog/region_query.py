"""Region and economy-option metadata queries."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from policyengine_api.dataset_display import get_dataset_display_label
from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
)
from policyengine_api.data.v2.catalog.query_support import (
    MetadataResourceNotFoundError,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataDatasetOption,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataPageResult,
    MetadataRegion,
    MetadataRegionOption,
    MetadataTimePeriodOption,
)
from policyengine_api.data.v2.models import Dataset, Region


def _region(region: Region) -> MetadataRegion:
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


def list_regions(
    session: Session,
    selected: SelectedCatalog,
    *,
    region_type: str | None,
    offset: int,
    limit: int,
) -> MetadataPageResult[MetadataRegion]:
    statement = select(Region).where(
        Region.tax_benefit_model_version_id == selected.model_version.id
    )
    if region_type is not None:
        statement = statement.where(Region.region_type == region_type)
    rows = query_rows(
        session,
        statement.order_by(Region.code).offset(offset).limit(limit + 1),
    )
    return page_result(
        selected,
        [_region(row) for row in rows],
        offset=offset,
        limit=limit,
    )


def get_region(
    session: Session,
    selected: SelectedCatalog,
    region_id: UUID,
) -> MetadataDetailResult[MetadataRegion]:
    rows = query_rows(
        session,
        select(Region).where(
            Region.id == region_id,
            Region.tax_benefit_model_version_id == selected.model_version.id,
        ),
    )
    if not rows:
        raise MetadataResourceNotFoundError(f"region {region_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_region(rows[0]),
    )


def get_region_by_code(
    session: Session,
    selected: SelectedCatalog,
    region_code: str,
) -> MetadataDetailResult[MetadataRegion]:
    rows = query_rows(
        session,
        select(Region).where(
            Region.code == region_code,
            Region.tax_benefit_model_version_id == selected.model_version.id,
        ),
    )
    if not rows:
        raise MetadataResourceNotFoundError(f"region {region_code!r} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_region(rows[0]),
    )


def get_economy_options(
    session: Session,
    selected: SelectedCatalog,
) -> MetadataEconomyOptionsResult:
    country_id = selected.country_id
    regions = query_rows(
        session,
        select(Region)
        .where(Region.tax_benefit_model_version_id == selected.model_version.id)
        .order_by(Region.code),
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
        session,
        select(Dataset).where(
            Dataset.id == national_region.default_dataset_id,
            Dataset.tax_benefit_model_version_id == selected.model_version.id,
            Dataset.is_output_dataset.is_(False),
            Dataset.storage_path.is_(None),
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
