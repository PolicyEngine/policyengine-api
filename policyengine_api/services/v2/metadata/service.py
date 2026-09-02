"""Session-owning application service for API v2 metadata reads."""

from __future__ import annotations

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
    validate_policyengine_version,
)
from policyengine_api.data.v2.metadata.reads_datasets import (
    DatasetReadMethods,
)
from policyengine_api.data.v2.metadata.reads_models import (
    ModelReadMethods,
)
from policyengine_api.data.v2.metadata.reads_parameters import (
    ParameterReadMethods,
)
from policyengine_api.data.v2.metadata.reads import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    validate_metadata_page,
)
from policyengine_api.data.v2.metadata.reads_regions import (
    RegionReadMethods,
)
from policyengine_api.data.v2.metadata.reads_variables import (
    VariableReadMethods,
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
    ModelReadMethods,
    VariableReadMethods,
    ParameterReadMethods,
    DatasetReadMethods,
    RegionReadMethods,
):
    """Expose resource-specific metadata read methods to the route layer."""
