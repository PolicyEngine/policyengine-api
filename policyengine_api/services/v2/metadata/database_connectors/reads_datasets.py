"""Database selections for logical input-dataset metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Dataset
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from uuid import UUID


def read_datasets(
    session: Session, *, model_version_id: UUID, offset: int, limit: int
) -> list[Dataset]:
    """Return a page of a model version's logical input datasets in name order.

    Fetch limit + 1 rows so the caller can tell whether another page exists.
    """
    return read_rows(
        session,
        select(Dataset)
        .where(
            col(Dataset.tax_benefit_model_version_id) == model_version_id,
            col(Dataset.is_output_dataset).is_(False),
            col(Dataset.storage_path).is_(None),
        )
        .order_by(col(Dataset.name))
        .offset(offset)
        .limit(limit + 1),
    )


def read_dataset(
    session: Session, *, model_version_id: UUID, dataset_id: UUID
) -> Dataset | None:
    """Return the model version's logical input dataset with dataset_id, or None."""
    rows = read_rows(
        session,
        select(Dataset).where(
            col(Dataset.id) == dataset_id,
            col(Dataset.tax_benefit_model_version_id) == model_version_id,
            col(Dataset.is_output_dataset).is_(False),
            col(Dataset.storage_path).is_(None),
        ),
    )
    return rows[0] if rows else None


def read_input_datasets(session: Session, *, model_version_id: UUID) -> list[Dataset]:
    """Return every logical input dataset of a model version in name order."""
    return read_rows(
        session,
        select(Dataset)
        .where(
            col(Dataset.tax_benefit_model_version_id) == model_version_id,
            col(Dataset.is_output_dataset).is_(False),
            col(Dataset.storage_path).is_(None),
        )
        .order_by(col(Dataset.name)),
    )
