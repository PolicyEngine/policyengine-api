"""SQLite-backed coverage for the v2 countries service: the list and the check."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import V2_METADATA, Country
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.countries.validators import (
    CountryListMismatchError,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS
from tests.fixtures.v2_countries import add_listed_countries


def _service_with_countries(*extra_countries: Country) -> V2CountryService:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    with sessions() as session:
        add_listed_countries(session)
        session.add_all(extra_countries)
        session.commit()
    return V2CountryService(CountryDatabaseSession(sessions))


def test_countries_are_listed_by_id_with_their_capability_flags() -> None:
    service = _service_with_countries(
        Country(id="be", household_enabled=True, society_wide_enabled=False)
    )

    countries = service.list_countries()

    assert countries == [
        CountryRead(id="be", household_enabled=True, society_wide_enabled=False),
        CountryRead(id="uk", household_enabled=True, society_wide_enabled=True),
        CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
    ]


def test_an_empty_countries_table_lists_no_countries() -> None:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    service = V2CountryService(
        CountryDatabaseSession(sessionmaker(engine, class_=Session))
    )

    assert service.list_countries() == []


def test_rows_for_exactly_the_listed_countries_pass_verification() -> None:
    service = _service_with_countries()

    service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)


def test_a_row_for_an_unlisted_country_fails_verification() -> None:
    service = _service_with_countries(
        Country(id="ca", household_enabled=True, society_wide_enabled=False)
    )

    with pytest.raises(CountryListMismatchError) as raised:
        service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)

    assert raised.value.rows_not_listed == ("ca",)
    assert raised.value.listed_without_row == ()


def test_an_empty_countries_table_fails_verification() -> None:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    service = V2CountryService(
        CountryDatabaseSession(sessionmaker(engine, class_=Session))
    )

    with pytest.raises(CountryListMismatchError) as raised:
        service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)

    assert raised.value.listed_without_row == tuple(sorted(SUPPORTED_COUNTRY_IDS))
