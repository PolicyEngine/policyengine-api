"""Shared database selections for v2 metadata operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
    select_catalog,
)


def read_metadata_catalog(
    session: Session,
    *,
    country_id: str,
    running_policyengine_version: str,
    policyengine_version: str | None,
) -> SelectedCatalog:
    return select_catalog(
        session,
        country_id=country_id,
        running_policyengine_version=running_policyengine_version,
        policyengine_version=policyengine_version,
    )


def read_rows(session: Session, statement: Any) -> list[Any]:
    try:
        return list(session.exec(statement).all())
    except SQLAlchemyError as error:
        raise MetadataCatalogUnavailableError(
            "the v2 metadata catalog cannot be queried"
        ) from error
