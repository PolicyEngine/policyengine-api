"""Router-facing service for the v2 countries list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.countries.database_connectors.reads import (
    read_countries,
)
from policyengine_api.services.v2.countries.transformations import country_read

if TYPE_CHECKING:
    from policyengine_api.services.v2.countries.database_session import (
        CountryDatabaseSession,
    )
    from policyengine_api.services.v2.countries.types import CountryRead


class V2CountryService:
    """List the countries v2 records may belong to, with their capability."""

    def __init__(self, database_session: CountryDatabaseSession) -> None:
        """Read through ``database_session``, which opens one session per call."""
        self._database_session = database_session

    def list_countries(self) -> list[CountryRead]:
        """Return every listed country, ordered by country ID."""
        with self._database_session.read() as session:
            return [country_read(country) for country in read_countries(session)]
