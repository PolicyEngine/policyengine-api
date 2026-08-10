from policyengine_api.data.v1_models import UserProfile
from policyengine_api.services.user_service import UserService


def test_user_service_reads_and_writes_mapped_profiles(orm_session_factory):
    service = UserService(orm_session_factory)

    created, profile = service.create_profile(
        primary_country="us",
        auth0_id="auth0|direct",
        username="direct-user",
        user_since=123,
    )
    duplicate_created, duplicate = service.create_profile(
        primary_country="us",
        auth0_id="auth0|direct",
        username="ignored",
        user_since=456,
    )

    assert created is True
    assert duplicate_created is False
    assert isinstance(profile, UserProfile)
    assert duplicate.user_id == profile.user_id
    assert service.get_profile(auth0_id="auth0|direct").user_id == profile.user_id


def test_user_service_updates_the_mapped_profile(orm_session_factory):
    service = UserService(orm_session_factory)
    _, profile = service.create_profile(
        primary_country="us",
        auth0_id="auth0|update",
        username=None,
        user_since=123,
    )

    updated = service.update_profile(
        user_id=profile.user_id,
        primary_country="uk",
        username="updated-user",
        user_since=456,
    )

    assert updated.user_id == profile.user_id
    assert updated.primary_country == "uk"
    assert updated.username == "updated-user"
