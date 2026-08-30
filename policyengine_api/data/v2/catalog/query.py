"""Route-facing service for read-only v2 metadata resource queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.catalog import (
    dataset_query,
    model_query,
    parameter_query,
    region_query,
    variable_query,
)
from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    SelectedCatalog,
    UnsupportedPreviewCountryError,
    select_catalog,
    validate_policyengine_version,
)
from policyengine_api.data.v2.catalog.query_support import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
    validate_metadata_page,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataVariable,
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


class V2MetadataQueryService:
    """Select one catalog and delegate each resource to its query module."""

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

    def _select_paginated_catalog(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        offset: int,
        limit: int,
    ) -> SelectedCatalog:
        validate_metadata_page(offset, limit)
        return self.select_catalog(country_id, policyengine_version)

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        return model_query.list_models(
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
        )

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        return model_query.get_model(
            self.select_catalog(country_id, policyengine_version),
            model_id,
        )

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResult:
        return model_query.get_model_by_country(
            self.select_catalog(country_id, policyengine_version)
        )

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        return model_query.list_model_versions(
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
        )

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        return model_query.get_model_version(
            self.select_catalog(country_id, policyengine_version),
            version_id,
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
        return variable_query.list_variables(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
            search=search,
        )

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataVariable]:
        return variable_query.get_variable(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            variable_id,
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
        return parameter_query.list_parameters(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
            search=search,
        )

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        return parameter_query.get_parameter(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            parameter_id,
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
        return parameter_query.list_parameter_children(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            parent_path=parent_path,
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
        return parameter_query.list_parameter_values(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            parameter_id=parameter_id,
            current=current,
            offset=offset,
            limit=limit,
            now=now,
        )

    def get_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        return parameter_query.get_parameter_value(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            value_id,
        )

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        return dataset_query.list_datasets(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
        )

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        return dataset_query.get_dataset(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            dataset_id,
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
        return region_query.list_regions(
            self._session,
            self._select_paginated_catalog(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
            region_type=region_type,
            offset=offset,
            limit=limit,
        )

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        return region_query.get_region(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            region_id,
        )

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        return region_query.get_region_by_code(
            self._session,
            self.select_catalog(country_id, policyengine_version),
            region_code,
        )

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResult:
        return region_query.get_economy_options(
            self._session,
            self.select_catalog(country_id, policyengine_version),
        )
