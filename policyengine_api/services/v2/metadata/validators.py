"""Database-independent validation for v2 metadata operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from policyengine_api.data.v2.catalog.catalog_selection_validation import (
        SelectedCatalog,
    )
    from policyengine_api.data.v2.models import Dataset, Region


MAXIMUM_METADATA_PAGE_LIMIT = 500


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


class ParameterSearchFileUnavailableError(MetadataCatalogUnavailableError):
    """Raised when a selected catalog version has no parameter search file.

    Catalog publication writes a file, from the installed packages' catalog,
    for a catalog format 2 version it publishes or runs with installed. Other
    versions have none: those stored before catalog format 2, and those stored
    before search files existed that publication has not run with installed
    since. The message names the version and is safe to return to the caller.
    """


class ParameterTreeUnavailableError(MetadataCatalogUnavailableError):
    """Raised when a selected catalog version has no parameter tree.

    Catalog publication writes a tree, from the installed packages, for each
    version it publishes and for the installed version when it is stored with
    catalog format 2 but without one; any other version has none. The message
    names the version and is safe to return to the caller.
    """


class CatalogValuesPrunedError(MetadataCatalogUnavailableError):
    """Raised when catalog pruning removed the selected version's current-law data.

    Catalog publication prunes the stored versions other than the installed
    one and the two most recently published others: it deletes their
    current-law parameter values, parameter tree rows and parameter search
    file, which publishing the version again restores. The message names the
    country and the version and is safe to return to the caller.

    ``running_version`` says whether the pruned version is the one this
    process runs, which a request without ``policyengine_version`` selects.
    Its data is then missing because of how the service was deployed, such
    as traffic moved back to a revision older than the kept versions, not
    because of what the request asked for.
    """

    def __init__(self, message: str, *, running_version: bool = False) -> None:
        """Keep the message and whether the pruned version is the running one."""
        super().__init__(message)
        self.running_version = running_version


def parameter_tree_unavailable_error(
    selected: SelectedCatalog,
) -> ParameterTreeUnavailableError:
    """Return the error for a selected version that has no parameter tree."""
    msg = (
        f"catalog version {selected.policyengine_version} has no parameter "
        "tree: catalog publication writes trees only for the versions it "
        "publishes and for the installed version with catalog format 2"
    )
    return ParameterTreeUnavailableError(msg)


def parameter_search_file_unavailable_error(
    selected: SelectedCatalog,
) -> ParameterSearchFileUnavailableError:
    """Return the error for a selected version that has no parameter search file."""
    msg = (
        f"catalog version {selected.policyengine_version} has no parameter search "
        "file: only catalog format 2 versions that catalog publication has "
        "published, or run with installed, since search files were added have one"
    )
    return ParameterSearchFileUnavailableError(msg)


def require_current_law_values(
    selected: SelectedCatalog,
    *,
    pruned_at: datetime | None,
    running_policyengine_version: str,
) -> None:
    """Raise CatalogValuesPrunedError if the selected version was pruned.

    ``pruned_at`` is the version's ``catalog_values_pruned_at``: when catalog
    publication removed its current-law values, tree rows and search file, or
    None while they are stored. The error says whether the version is
    ``running_policyengine_version``, the one the process runs.
    """
    if pruned_at is None:
        return
    version = selected.policyengine_version
    msg = (
        f"PolicyEngine.py {version}'s current-law parameter values for "
        f"{selected.country_id} were removed from the catalog, with its "
        "parameter tree and search file; they return when PolicyEngine.py "
        f"{version} is installed again"
    )
    raise CatalogValuesPrunedError(
        msg, running_version=version == running_policyengine_version
    )


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
