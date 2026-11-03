"""Countries rows for SQLite tests that enforce v2 foreign keys.

``V2_METADATA.create_all`` creates an empty countries table, while the v2
Alembic revision that adds the table inserts the US and UK rows. Tests that
turn on SQLite foreign-key enforcement add the same rows before writing
records that name a country.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import Country

if TYPE_CHECKING:
    from sqlmodel import Session

# The rows the countries revision inserts, ordered by country ID.
LISTED_COUNTRY_ROWS = (
    {"id": "uk", "household_enabled": True, "society_wide_enabled": True},
    {"id": "us", "household_enabled": True, "society_wide_enabled": True},
)


def add_listed_countries(session: Session) -> None:
    """Insert and commit the US and UK countries rows."""
    session.add_all(Country(**row) for row in LISTED_COUNTRY_ROWS)
    session.commit()
