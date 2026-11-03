"""Router-facing and startup service for the v2 countries table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.countries.database_connectors.reads import (
    read_countries,
    read_country_ids,
)
from policyengine_api.services.v2.countries.transformations import country_read
from policyengine_api.services.v2.countries.validators import (
    validate_countries_match_code_list,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from policyengine_api.services.v2.countries.database_session import (
        CountryDatabaseSession,
    )
    from policyengine_api.services.v2.countries.types import CountryRead


class V2CountryService:
    """List the served countries, and check them against the list in code."""

    def __init__(self, database_session: CountryDatabaseSession) -> None:
        """Read through ``database_session``, which opens one session per call."""
        self._database_session = database_session

    def list_countries(self) -> list[CountryRead]:
        """Return every countries row, ordered by country ID."""
        with self._database_session.read() as session:
            return [country_read(country) for country in read_countries(session)]

    def verify_countries_match_code_list(
        self, listed_country_ids: Iterable[str]
    ) -> None:
        """Raise ``CountryListMismatchError`` unless the rows name exactly these.

        The application runs this at startup with the country list in code.
        """
        with self._database_session.read() as session:
            stored_country_ids = read_country_ids(session)
        validate_countries_match_code_list(
            stored_country_ids=stored_country_ids,
            listed_country_ids=listed_country_ids,
        )
