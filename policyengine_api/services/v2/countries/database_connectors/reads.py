"""Database selections used by the v2 countries list and the startup check."""

from __future__ import annotations

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Country


def read_countries(session: Session) -> list[Country]:
    """Return every countries row, ordered by country ID."""
    return list(session.exec(select(Country).order_by(col(Country.id))).all())


def read_country_ids(session: Session) -> list[str]:
    """Return the ID of every countries row, ordered."""
    return list(session.exec(select(Country.id).order_by(col(Country.id))).all())
