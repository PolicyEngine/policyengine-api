"""SQLite-backed coverage for the v2 countries read service."""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import V2_METADATA, Country
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.countries.types import CountryRead
from tests.fixtures.v2_countries import add_society_wide_countries


def _service_with_countries(*extra_countries: Country) -> V2CountryService:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    with sessions() as session:
        add_society_wide_countries(session)
        session.add_all(extra_countries)
        session.commit()
    return V2CountryService(CountryDatabaseSession(sessions))


def test_countries_are_listed_by_id_with_their_capability_flags() -> None:
    service = _service_with_countries(
        Country(
            id="be",
            name="Belgium",
            household_enabled=True,
            society_wide_enabled=False,
        )
    )

    countries = service.list_countries()

    assert countries == [
        CountryRead(
            id="be",
            name="Belgium",
            household_enabled=True,
            society_wide_enabled=False,
        ),
        CountryRead(
            id="uk",
            name="United Kingdom",
            household_enabled=True,
            society_wide_enabled=True,
        ),
        CountryRead(
            id="us",
            name="United States",
            household_enabled=True,
            society_wide_enabled=True,
        ),
    ]


def test_an_empty_countries_table_lists_no_countries() -> None:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    service = V2CountryService(
        CountryDatabaseSession(sessionmaker(engine, class_=Session))
    )

    assert service.list_countries() == []
