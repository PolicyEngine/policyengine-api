"""Tax-benefit model and model-version metadata queries."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.catalog.query_support import (
    MetadataQueryContext,
    MetadataResourceNotFoundError,
    page_result,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataDetailResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
)


def _model(selected: SelectedCatalog) -> MetadataModel:
    return MetadataModel(
        id=selected.model.id,
        name=selected.model.name,
        description=selected.model_version.description,
    )


def _model_version(selected: SelectedCatalog) -> MetadataModelVersionDetail:
    return MetadataModelVersionDetail(
        id=selected.model_version.id,
        model_id=selected.model.id,
        version=selected.model_version.version,
        description=selected.model_version.description,
        current_law_id=selected.model_version.current_law_id,
        metadata_time_periods=selected.model_version.metadata_time_periods,
    )


class ModelQueryMethods(MetadataQueryContext):
    """Route-facing model and model-version query methods."""

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        rows = [_model(selected)] if offset == 0 else []
        return page_result(selected, rows, offset=offset, limit=limit)

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        selected = self.select_catalog(country_id, policyengine_version)
        if selected.model.id != model_id:
            raise MetadataResourceNotFoundError(f"model {model_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_model(selected),
        )

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResult:
        selected = self.select_catalog(country_id, policyengine_version)
        return MetadataModelSelectionResult(
            policyengine_version=selected.policyengine_version,
            model=_model(selected),
            model_version=_model_version(selected),
        )

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        rows = [_model_version(selected)] if offset == 0 else []
        return page_result(selected, rows, offset=offset, limit=limit)

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        selected = self.select_catalog(country_id, policyengine_version)
        if selected.model_version.id != version_id:
            raise MetadataResourceNotFoundError(
                f"model version {version_id} was not found"
            )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_model_version(selected),
        )
