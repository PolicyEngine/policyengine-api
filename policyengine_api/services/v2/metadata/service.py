"""Session-owning application service for API v2 metadata reads."""

from __future__ import annotations

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
    validate_policyengine_version,
)
from policyengine_api.data.v2.metadata.dataset_queries import (
    DatasetQueryMethods,
)
from policyengine_api.data.v2.metadata.model_queries import (
    ModelQueryMethods,
)
from policyengine_api.data.v2.metadata.parameter_queries import (
    ParameterQueryMethods,
)
from policyengine_api.data.v2.metadata.query_support import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    validate_metadata_page,
)
from policyengine_api.data.v2.metadata.region_queries import (
    RegionQueryMethods,
)
from policyengine_api.data.v2.metadata.variable_queries import (
    VariableQueryMethods,
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
    ModelQueryMethods,
    VariableQueryMethods,
    ParameterQueryMethods,
    DatasetQueryMethods,
    RegionQueryMethods,
):
    """Expose resource-specific metadata query methods to the route layer."""
