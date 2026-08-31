"""Logical input-dataset metadata queries."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import select
from policyengine_api.data.v2.catalog.query_support import (
    MetadataQueryContext,
    MetadataResourceNotFoundError,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataDataset,
    MetadataDetailResult,
    MetadataPageResult,
)
from policyengine_api.data.v2.models import Dataset


def _dataset(dataset: Dataset) -> MetadataDataset:
    return MetadataDataset(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        year=dataset.year,
    )


class DatasetQueryMethods(MetadataQueryContext):
    """Route-facing logical input-dataset query methods."""

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        selected = self._select_paginated_catalog(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
        )
        rows = query_rows(
            self._session,
            select(Dataset)
            .where(
                Dataset.tax_benefit_model_version_id == selected.model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            )
            .order_by(Dataset.name)
            .offset(offset)
            .limit(limit + 1),
        )
        return page_result(
            selected,
            [_dataset(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        selected = self.select_catalog(country_id, policyengine_version)
        rows = query_rows(
            self._session,
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.tax_benefit_model_version_id == selected.model_version.id,
                Dataset.is_output_dataset.is_(False),
                Dataset.storage_path.is_(None),
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"dataset {dataset_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_dataset(rows[0]),
        )
