"""Database-independent validation for v2 metadata operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
    from policyengine_api.data.v2.models import Dataset, Region


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


def validate_metadata_page(offset: int, limit: int) -> tuple[int, int]:
    if offset < 0:
        raise InvalidMetadataPageError("offset must be at least 0")
    if not 1 <= limit <= 500:
        raise InvalidMetadataPageError("limit must be between 1 and 500")
    return offset, limit


ResourceT = TypeVar("ResourceT")


def require_metadata_resource(
    resource: ResourceT | None, *, description: str
) -> ResourceT:
    if resource is None:
        raise MetadataResourceNotFoundError(f"{description} was not found")
    return resource


def validate_economy_options(
    selected: "SelectedCatalog",
    *,
    country_id: str,
    regions: list["Region"],
    national_dataset: "Dataset | None",
) -> "Dataset":
    """Validate preloaded records required by the economy-options response."""

    if not any(region.code == country_id for region in regions):
        raise MetadataCatalogUnavailableError(
            f"the {country_id} national v2 region is absent"
        )
    if national_dataset is None:
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
    return national_dataset
