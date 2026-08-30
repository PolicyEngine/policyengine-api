"""Logical input-dataset metadata queries."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.catalog.query_support import (
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


def list_datasets(
    session: Session,
    selected: SelectedCatalog,
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[MetadataDataset]:
    rows = query_rows(
        session,
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
    session: Session,
    selected: SelectedCatalog,
    dataset_id: UUID,
) -> MetadataDetailResult[MetadataDataset]:
    rows = query_rows(
        session,
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
