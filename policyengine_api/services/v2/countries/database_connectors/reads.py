"""Database selections used by the v2 countries list."""

from __future__ import annotations

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Country


def read_countries(session: Session) -> list[Country]:
    """Return every countries row, ordered by country ID."""
    return list(session.exec(select(Country).order_by(col(Country.id))).all())
