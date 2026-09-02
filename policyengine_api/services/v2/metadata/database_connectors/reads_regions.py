"""Database selections for region and economy-option metadata."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Dataset, Region
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows


def read_regions(
    session: Session,
    *,
    model_version_id: UUID,
    region_type: str | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> list[Region]:
    statement = select(Region).where(
        col(Region.tax_benefit_model_version_id) == model_version_id
    )
    if region_type is not None:
        statement = statement.where(col(Region.region_type) == region_type)
    statement = statement.order_by(col(Region.code))
    if offset is not None:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit + 1)
    return read_rows(session, statement)


def read_region(
    session: Session,
    *,
    model_version_id: UUID,
    region_id: UUID | None = None,
    region_code: str | None = None,
) -> Region | None:
    statement = select(Region).where(
        col(Region.tax_benefit_model_version_id) == model_version_id
    )
    if region_id is not None:
        statement = statement.where(col(Region.id) == region_id)
    if region_code is not None:
        statement = statement.where(col(Region.code) == region_code)
    rows = read_rows(session, statement)
    return rows[0] if rows else None


def read_input_dataset(
    session: Session, *, model_version_id: UUID, dataset_id: UUID
) -> Dataset | None:
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
