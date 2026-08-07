import pytest

from policyengine_api.data.v1_models import UserProfile
from policyengine_api.services.user_service import UserService
from tests.fixtures.services.user_service import valid_user_record


pytest_plugins = ["tests.fixtures.services.user_service"]

service = UserService()


def test_get_profile_requires_an_identifier(orm_session):
    with pytest.raises(
        ValueError,
        match="you must specify either auth0_id or user_id",
    ):
        service.get_profile(orm_session)


def test_get_profile_returns_none_for_unknown_auth0_id(orm_session):
    assert service.get_profile(orm_session, auth0_id="missing") is None


def test_get_profile_returns_mapped_entity_by_either_identifier(
    orm_session,
    existing_user_profile,
):
    by_auth0 = service.get_profile(
        orm_session,
        auth0_id=valid_user_record["auth0_id"],
    )
    by_id = service.get_profile(
        orm_session,
        user_id=valid_user_record["user_id"],
    )

    assert isinstance(by_auth0, UserProfile)
    assert by_auth0 is by_id
    assert by_auth0.username == valid_user_record["username"]


def test_create_profile_returns_existing_entity_for_duplicate_auth0_id(
    orm_session,
):
    created, profile = service.create_profile(
        orm_session,
        "us",
        "auth0|duplicate",
        "first",
        1,
    )
    duplicate_created, duplicate = service.create_profile(
        orm_session,
        "uk",
        "auth0|duplicate",
        "second",
        2,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate is profile
    assert duplicate.username == "first"


def test_update_profile_returns_none_for_missing_entity(orm_session):
    assert service.update_profile(orm_session, 999, "uk", "missing", 2) is None


def test_update_profile_only_changes_non_null_fields(
    orm_session,
    existing_user_profile,
):
    profile = service.update_profile(
        orm_session,
        valid_user_record["user_id"],
        "uk",
        None,
        valid_user_record["user_since"] + 1,
    )

    assert profile.primary_country == "uk"
    assert profile.username == valid_user_record["username"]
    assert profile.user_since == valid_user_record["user_since"] + 1


def test_update_profile_requires_user_id(orm_session):
    with pytest.raises(
        ValueError,
        match="you must specify either auth0_id or user_id",
    ):
        service.update_profile(orm_session, None, "us", "name", 1)
