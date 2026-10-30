"""Database selections used by the v2 household report service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from policyengine_api.data.v2.models import Country, TaxBenefitModelVersion

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from sqlmodel import Session


def read_country(session: Session, country_id: str) -> Country | None:
    """Return the country's countries row, or None when it has none."""
    return session.get(Country, country_id)


def read_policyengine_versions(
    session: Session, catalog_version_ids: Collection[UUID]
) -> dict[UUID, str]:
    """Return the PolicyEngine.py version of each of these catalog versions.

    A catalog version the Public API does not have is left out.
    """
    if not catalog_version_ids:
        return {}
    rows = session.exec(
        select(TaxBenefitModelVersion.id, TaxBenefitModelVersion.version).where(
            col(TaxBenefitModelVersion.id).in_(catalog_version_ids)
        )
    )
    return dict(rows.all())
