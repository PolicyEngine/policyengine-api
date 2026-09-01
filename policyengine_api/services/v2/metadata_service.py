"""Session-owning application service for API v2 metadata reads."""

from __future__ import annotations

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
    validate_policyengine_version,
)
from policyengine_api.data.v2.catalog.dataset_query import DatasetQueryMethods
from policyengine_api.data.v2.catalog.model_query import ModelQueryMethods
from policyengine_api.data.v2.catalog.parameter_query import ParameterQueryMethods
from policyengine_api.data.v2.catalog.query_support import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    validate_metadata_page,
)
from policyengine_api.data.v2.catalog.region_query import RegionQueryMethods
from policyengine_api.data.v2.catalog.variable_query import VariableQueryMethods


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
    """Combine the resource-specific query methods into the route-facing API."""
