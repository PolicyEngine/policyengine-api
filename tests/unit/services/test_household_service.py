import pytest

from policyengine_api.data.v1_models import Household
from policyengine_api.services.household_service import HouseholdService
from tests.fixtures.services.household_fixtures import (
    valid_db_row,
    valid_request_body,
)


pytest_plugins = ["tests.fixtures.services.household_fixtures"]


service = HouseholdService()


def test_get_household_returns_mapped_entity(orm_session, existing_household_record):
    household = service.get_household(
        orm_session,
        valid_db_row["country_id"],
        valid_db_row["id"],
    )

    assert isinstance(household, Household)
    assert household.household_json == valid_request_body["data"]


def test_get_household_returns_none_for_missing_entity(orm_session):
    assert service.get_household(orm_session, "us", 999) is None


@pytest.mark.parametrize("household_id", ["invalid", -1])
def test_get_household_rejects_invalid_id(orm_session, household_id):
    with pytest.raises(Exception, match="Invalid household ID"):
        service.get_household(orm_session, "us", household_id)


def test_create_household_adds_mapped_entity(orm_session, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "some-hash",
    )

    household = service.create_household(
        orm_session,
        "us",
        valid_request_body["data"],
        valid_request_body["label"],
    )

    assert isinstance(household, Household)
    assert household.id is not None
    assert household.household_json == valid_request_body["data"]


def test_update_household_mutates_mapped_entity(
    orm_session,
    existing_household_record,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "updated-hash",
    )

    household = service.update_household(
        orm_session,
        "us",
        valid_db_row["id"],
        {"people": {"person1": {"age": 31}}},
        "Updated Household",
    )

    assert household.label == "Updated Household"
    assert household.household_hash == "updated-hash"
    assert household.household_json == {"people": {"person1": {"age": 31}}}


def test_update_household_rejects_missing_or_cross_country_entity(
    orm_session,
    existing_household_record,
):
    with pytest.raises(LookupError):
        service.update_household(
            orm_session,
            "uk",
            valid_db_row["id"],
            {},
            "Wrong country",
        )
