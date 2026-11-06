"""Shared database selections for v2 metadata operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select

from policyengine_api.data.v2.catalog.catalog_selection_reads import select_catalog
from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
)
from policyengine_api.data.v2.models import TaxBenefitModelVersion

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session


def read_metadata_catalog(
    session: Session,
    *,
    country_id: str,
    running_policyengine_version: str,
    policyengine_version: str | None,
) -> SelectedCatalog:
    """Return the country's catalog for policyengine_version, else the running version.

    Raise the catalog_selection_validation errors for an unsupported country, an
    unpublished version or an unreachable database.
    """
    return select_catalog(
        session,
        country_id=country_id,
        running_policyengine_version=running_policyengine_version,
        policyengine_version=policyengine_version,
    )


def read_rows(
    session: Session,
    statement: Any,  # noqa: ANN401  # Session.exec overloads omit core SQLAlchemy selects
) -> list[Any]:
    """Execute statement and return every row.

    Raise MetadataCatalogUnavailableError when the database query fails.
    """
    try:
        return list(session.exec(statement).all())
    except SQLAlchemyError as error:
        msg = "the v2 metadata catalog cannot be queried"
        raise MetadataCatalogUnavailableError(msg) from error


def read_catalog_values_pruned_at(
    session: Session, *, model_version_id: UUID
) -> datetime | None:
    """Return when catalog pruning removed the version's current-law data, or None.

    It reads the version's ``catalog_values_pruned_at`` from the database, not
    from a selection the process may have kept since before the pruning.
    """
    rows = read_rows(
        session,
        select(col(TaxBenefitModelVersion.catalog_values_pruned_at)).where(
            col(TaxBenefitModelVersion.id) == model_version_id
        ),
    )
    pruned_at: datetime | None = rows[0] if rows else None
    return pruned_at
