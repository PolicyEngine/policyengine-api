"""Tax-benefit model and model-version metadata queries."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.catalog.query_support import (
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


def list_models(
    selected: SelectedCatalog,
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[MetadataModel]:
    rows = [_model(selected)] if offset == 0 else []
    return page_result(selected, rows, offset=offset, limit=limit)


def get_model(
    selected: SelectedCatalog,
    model_id: UUID,
) -> MetadataDetailResult[MetadataModel]:
    if selected.model.id != model_id:
        raise MetadataResourceNotFoundError(f"model {model_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_model(selected),
    )


def get_model_by_country(selected: SelectedCatalog) -> MetadataModelSelectionResult:
    return MetadataModelSelectionResult(
        policyengine_version=selected.policyengine_version,
        model=_model(selected),
        model_version=_model_version(selected),
    )


def list_model_versions(
    selected: SelectedCatalog,
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[MetadataModelVersionDetail]:
    rows = [_model_version(selected)] if offset == 0 else []
    return page_result(selected, rows, offset=offset, limit=limit)


def get_model_version(
    selected: SelectedCatalog,
    version_id: UUID,
) -> MetadataDetailResult[MetadataModelVersionDetail]:
    if selected.model_version.id != version_id:
        raise MetadataResourceNotFoundError(f"model version {version_id} was not found")
    return MetadataDetailResult(
        policyengine_version=selected.policyengine_version,
        item=_model_version(selected),
    )
