"""SQLite-backed coverage for the v2 countries service: the list and the check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.models import Country
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.countries.validators import (
    CountryListMismatchError,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_countries import add_listed_countries

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    """Return Session factories of an empty in-memory SQLite v2 database."""
    with sqlite_v2_sessions() as v2_sessions:
        yield v2_sessions


def _service_with_countries(
    sessions: sessionmaker[Session], *extra_countries: Country
) -> V2CountryService:
    with sessions() as session:
        add_listed_countries(session)
        session.add_all(extra_countries)
        session.commit()
    return V2CountryService(CountryDatabaseSession(sessions))


def test_countries_are_listed_by_id_with_their_capability_flags(
    sessions: sessionmaker[Session],
) -> None:
    service = _service_with_countries(
        sessions, Country(id="be", household_enabled=True, society_wide_enabled=False)
    )

    countries = service.list_countries()

    assert countries == [
        CountryRead(id="be", household_enabled=True, society_wide_enabled=False),
        CountryRead(id="uk", household_enabled=True, society_wide_enabled=True),
        CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
    ]


def test_an_empty_countries_table_lists_no_countries(
    sessions: sessionmaker[Session],
) -> None:
    service = V2CountryService(CountryDatabaseSession(sessions))

    assert service.list_countries() == []


def test_rows_for_exactly_the_listed_countries_pass_verification(
    sessions: sessionmaker[Session],
) -> None:
    service = _service_with_countries(sessions)

    service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)


def test_a_row_for_an_unlisted_country_fails_verification(
    sessions: sessionmaker[Session],
) -> None:
    service = _service_with_countries(
        sessions, Country(id="ca", household_enabled=True, society_wide_enabled=False)
    )

    with pytest.raises(CountryListMismatchError) as raised:
        service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)

    assert raised.value.rows_not_listed == ("ca",)
    assert raised.value.listed_without_row == ()


def test_an_empty_countries_table_fails_verification(
    sessions: sessionmaker[Session],
) -> None:
    service = V2CountryService(CountryDatabaseSession(sessions))

    with pytest.raises(CountryListMismatchError) as raised:
        service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)

    assert raised.value.listed_without_row == tuple(sorted(SUPPORTED_COUNTRY_IDS))
