"""Shared database selections for v2 metadata operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
    select_catalog,
)

if TYPE_CHECKING:
    from sqlmodel import Session


def read_metadata_catalog(
    session: Session,
    *,
    country_id: str,
    running_policyengine_version: str,
    policyengine_version: str | None,
) -> SelectedCatalog:
    """Return the country's catalog for policyengine_version, else the running version.

    Raise the catalog_selection errors for an unsupported country, an
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
        raise MetadataCatalogUnavailableError(
            "the v2 metadata catalog cannot be queried"
        ) from error
