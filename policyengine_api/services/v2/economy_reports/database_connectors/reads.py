"""Database selections used by the v2 economy report service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import Country

if TYPE_CHECKING:
    from sqlmodel import Session


def read_country(session: Session, country_id: str) -> Country | None:
    """Return the country's countries row, or None when it has none."""
    return session.get(Country, country_id)
