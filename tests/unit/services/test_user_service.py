import pytest

from policyengine_api.data.v1_models import UserProfile
from policyengine_api.services.user_service import UserService
from tests.fixtures.services.user_service import valid_user_record


pytest_plugins = ["tests.fixtures.services.user_service"]


@pytest.fixture
def service(orm_session_factory):
    return UserService(orm_session_factory)


def test_get_profile_requires_an_identifier(service):
    with pytest.raises(
        ValueError,
        match="you must specify either auth0_id or user_id",
    ):
        service.get_profile()


def test_get_profile_returns_none_for_unknown_auth0_id(service):
    assert service.get_profile(auth0_id="missing") is None


def test_get_profile_returns_mapped_entity_by_either_identifier(
    service,
    existing_user_profile,
):
    by_auth0 = service.get_profile(
        auth0_id=valid_user_record["auth0_id"],
    )
    by_id = service.get_profile(
        user_id=valid_user_record["user_id"],
    )

    assert isinstance(by_auth0, UserProfile)
    assert by_auth0.user_id == by_id.user_id
    assert by_auth0.username == valid_user_record["username"]


def test_create_profile_returns_existing_entity_for_duplicate_auth0_id(service):
    created, profile = service.create_profile(
        "us",
        "auth0|duplicate",
        "first",
        1,
    )
    duplicate_created, duplicate = service.create_profile(
        "uk",
        "auth0|duplicate",
        "second",
        2,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.user_id == profile.user_id
    assert duplicate.username == "first"


def test_update_profile_returns_none_for_missing_entity(service):
    assert service.update_profile(999, "uk", "missing", 2) is None


def test_update_profile_only_changes_non_null_fields(
    service,
    existing_user_profile,
):
    profile = service.update_profile(
        valid_user_record["user_id"],
        "uk",
        None,
        valid_user_record["user_since"] + 1,
    )

    assert profile.primary_country == "uk"
    assert profile.username == valid_user_record["username"]
    assert profile.user_since == valid_user_record["user_since"] + 1


def test_update_profile_requires_user_id(service):
    with pytest.raises(
        ValueError,
        match="you must specify either auth0_id or user_id",
    ):
        service.update_profile(None, "us", "name", 1)
