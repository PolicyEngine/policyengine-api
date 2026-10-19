"""Countries rows for SQLite tests that enforce v2 foreign keys.

``V2_METADATA.create_all`` creates an empty countries table, while the v2
Alembic revision inserts the US and UK rows. Tests that turn on SQLite
foreign-key enforcement add the same rows before writing country records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import Country

if TYPE_CHECKING:
    from sqlmodel import Session

# The rows the countries revision inserts, ordered by country ID.
SOCIETY_WIDE_COUNTRY_ROWS = (
    {
        "id": "uk",
        "name": "United Kingdom",
        "household_enabled": True,
        "society_wide_enabled": True,
    },
    {
        "id": "us",
        "name": "United States",
        "household_enabled": True,
        "society_wide_enabled": True,
    },
)


def add_society_wide_countries(session: Session) -> None:
    """Insert and commit the US and UK countries rows."""
    session.add_all(Country(**row) for row in SOCIETY_WIDE_COUNTRY_ROWS)
    session.commit()
