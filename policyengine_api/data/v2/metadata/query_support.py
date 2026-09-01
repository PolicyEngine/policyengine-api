"""Shared database execution and pagination for v2 metadata queries."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
    select_catalog as select_metadata_catalog,
    validate_policyengine_version,
)
from policyengine_api.data.v2.metadata.read_models import MetadataPageResult


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


ResourceT = TypeVar("ResourceT")


class MetadataQueryContext:
    """Own the session and catalog selection shared by metadata query methods."""

    def __init__(self, session: Session, *, running_policyengine_version: str):
        self._session = session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
        """Close the request-owned read session."""

        self._session.close()

    def select_catalog(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> SelectedCatalog:
        """Select exactly one initialized country catalog."""

        return select_metadata_catalog(
            self._session,
            country_id=country_id,
            running_policyengine_version=self._running_policyengine_version,
            policyengine_version=policyengine_version,
        )

    def _select_paginated_catalog(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        offset: int,
        limit: int,
    ) -> SelectedCatalog:
        validate_metadata_page(offset, limit)
        return self.select_catalog(country_id, policyengine_version)


def page_result(
    selected: SelectedCatalog,
    rows: list[ResourceT],
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[ResourceT]:
    """Return one bounded response page from a limit-plus-one query."""

    return MetadataPageResult(
        policyengine_version=selected.policyengine_version,
        items=rows[:limit],
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def validate_metadata_page(offset: int, limit: int) -> tuple[int, int]:
    """Validate the shared v2 metadata collection bounds."""

    if offset < 0:
        raise InvalidMetadataPageError("offset must be at least 0")
    if not 1 <= limit <= 500:
        raise InvalidMetadataPageError("limit must be between 1 and 500")
    return offset, limit


def query_rows(session: Session, statement: Any) -> list[Any]:
    """Execute one read statement and translate database failures."""

    try:
        return list(session.exec(statement).all())
    except SQLAlchemyError as error:
        raise MetadataCatalogUnavailableError(
            "the v2 metadata catalog cannot be queried"
        ) from error


def escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters in a literal search value."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
