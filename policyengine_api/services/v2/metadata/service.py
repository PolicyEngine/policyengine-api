"""Session-owning application service for API v2 metadata reads."""

from __future__ import annotations

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
    validate_policyengine_version,
)
from policyengine_api.data.v2.metadata.dataset_read_repository import (
    DatasetReadRepository,
)
from policyengine_api.data.v2.metadata.model_read_repository import (
    ModelReadRepository,
)
from policyengine_api.data.v2.metadata.parameter_read_repository import (
    ParameterReadRepository,
)
from policyengine_api.data.v2.metadata.read_repository import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    validate_metadata_page,
)
from policyengine_api.data.v2.metadata.region_read_repository import (
    RegionReadRepository,
)
from policyengine_api.data.v2.metadata.variable_read_repository import (
    VariableReadRepository,
)


__all__ = [
    "InvalidMetadataPageError",
    "InvalidPolicyEngineVersionError",
    "MetadataCatalogUnavailableError",
    "MetadataCatalogVersionNotFoundError",
    "MetadataResourceNotFoundError",
    "UnsupportedPreviewCountryError",
    "V2MetadataService",
    "validate_metadata_page",
    "validate_policyengine_version",
]


class V2MetadataService(
    ModelReadRepository,
    VariableReadRepository,
    ParameterReadRepository,
    DatasetReadRepository,
    RegionReadRepository,
):
    """Expose resource-specific metadata repositories to the route layer."""
