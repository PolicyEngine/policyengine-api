"""Country-scoped complete household read tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session, create_engine
import pytest

from policyengine_api.data.v2.models import Household, V2_METADATA
from policyengine_api.services.v2.households.services import (
    read_complete_household,
    read_household_page,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError


def _stored_households():
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_id = UUID("00000000-0000-0000-0000-000000000010")
    second_id = UUID("00000000-0000-0000-0000-000000000020")
    other_id = UUID("00000000-0000-0000-0000-000000000030")
    first = Household(
        id=first_id,
        country_id="us",
        default_year=2026,
        household_data={"people": [], "household": []},
        canonicalization_version=1,
        content_hash="1" * 64,
        created_at=created,
        updated_at=created,
    )
    second = Household(
        id=second_id,
        country_id="us",
        default_year=None,
        household_data={"people": [], "household": []},
        canonicalization_version=1,
        content_hash="2" * 64,
        created_at=created + timedelta(seconds=1),
        updated_at=created + timedelta(seconds=1),
    )
    other = Household(
        id=other_id,
        country_id="uk",
        default_year=2026,
        household_data={"people": [], "household": [], "benunit": []},
        canonicalization_version=1,
        content_hash="3" * 64,
        created_at=created + timedelta(seconds=2),
        updated_at=created + timedelta(seconds=2),
    )
    with Session(engine) as session:
        session.add_all([first, second, other])
        session.commit()
    return engine, first_id, second_id, other_id


def test_detail_is_complete_and_uses_country_as_resource_identity() -> None:
    engine, first_id, _second_id, _other_id = _stored_households()
    try:
        with Session(engine) as session:
            item = read_complete_household(
                session, country_id="us", household_id=first_id
            )
            assert item.household_data == {"people": [], "household": []}
            assert item.default_year == 2026
            with pytest.raises(HouseholdNotFoundError):
                read_complete_household(session, country_id="uk", household_id=first_id)
    finally:
        engine.dispose()


def test_collection_orders_paginates_and_filters_exact_default_year() -> None:
    engine, first_id, second_id, _other_id = _stored_households()
    try:
        with Session(engine) as session:
            first_page = read_household_page(
                session,
                country_id="us",
                default_year=None,
                offset=0,
                limit=1,
            )
            second_page = read_household_page(
                session,
                country_id="us",
                default_year=None,
                offset=1,
                limit=1,
            )
            filtered = read_household_page(
                session,
                country_id="us",
                default_year=2026,
                offset=0,
                limit=100,
            )

        assert [item.id for item in first_page.items] == [first_id]
        assert first_page.has_more is True
        assert [item.id for item in second_page.items] == [second_id]
        assert second_page.has_more is False
        assert [item.id for item in filtered.items] == [first_id]
    finally:
        engine.dispose()
