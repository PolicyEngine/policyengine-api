"""Logical input-dataset metadata database reads."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import col, select
from policyengine_api.data.v2.metadata.read_repository import (
    MetadataReadRepositoryBase,
    MetadataResourceNotFoundError,
    page_result,
    query_rows,
)
from policyengine_api.data.v2.metadata.read_models import (
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


class DatasetReadRepository(MetadataReadRepositoryBase):
    """Read logical input datasets from the selected catalog."""

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
                col(Dataset.tax_benefit_model_version_id) == selected.model_version.id,
                col(Dataset.is_output_dataset).is_(False),
                col(Dataset.storage_path).is_(None),
            )
            .order_by(col(Dataset.name))
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
                col(Dataset.id) == dataset_id,
                col(Dataset.tax_benefit_model_version_id) == selected.model_version.id,
                col(Dataset.is_output_dataset).is_(False),
                col(Dataset.storage_path).is_(None),
            ),
        )
        if not rows:
            raise MetadataResourceNotFoundError(f"dataset {dataset_id} was not found")
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=_dataset(rows[0]),
        )
