"""Database-independent validation for v2 metadata operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
    from policyengine_api.data.v2.models import Dataset, Region


MAXIMUM_METADATA_PAGE_LIMIT = 500


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


class ParameterTreeUnavailableError(MetadataCatalogUnavailableError):
    """Raised when a selected catalog version has no parameter tree.

    Catalog publication writes a tree, from the installed packages, for each
    version it publishes and for the installed version when it is stored with
    catalog format 2 but without one; any other version has none. The message
    names the version and is safe to return to the caller.
    """


def validate_metadata_page(offset: int, limit: int) -> tuple[int, int]:
    """Return offset and limit unchanged, or raise InvalidMetadataPageError.

    offset must be at least 0 and limit between 1 and 500.
    """
    if offset < 0:
        msg = "offset must be at least 0"
        raise InvalidMetadataPageError(msg)
    if not 1 <= limit <= MAXIMUM_METADATA_PAGE_LIMIT:
        msg = "limit must be between 1 and 500"
        raise InvalidMetadataPageError(msg)
    return offset, limit


ResourceT = TypeVar("ResourceT")


def require_metadata_resource(
    resource: ResourceT | None, *, description: str
) -> ResourceT:
    """Return resource, or raise MetadataResourceNotFoundError naming description."""
    if resource is None:
        msg = f"{description} was not found"
        raise MetadataResourceNotFoundError(msg)
    return resource


def validate_economy_options(
    selected: SelectedCatalog,
    *,
    country_id: str,
    regions: list[Region],
    national_dataset: Dataset | None,
) -> Dataset:
    """Validate preloaded records required by the economy-options response."""
    if not any(region.code == country_id for region in regions):
        msg = f"the {country_id} national v2 region is absent"
        raise MetadataCatalogUnavailableError(msg)
    if national_dataset is None:
        msg = f"the {country_id} national v2 dataset is absent"
        raise MetadataCatalogUnavailableError(msg)
    time_periods = selected.model_version.metadata_time_periods
    if (
        not isinstance(selected.model_version.current_law_id, int)
        or not isinstance(time_periods, list)
        or not time_periods
        or any(not isinstance(year, int) for year in time_periods)
    ):
        msg = f"the {country_id} v2 model-version options are incomplete"
        raise MetadataCatalogUnavailableError(msg)
    return national_dataset
