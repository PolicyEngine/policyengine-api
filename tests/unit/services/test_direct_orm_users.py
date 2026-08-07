from policyengine_api.data.v1_models import UserProfile
from policyengine_api.services.user_service import UserService


def test_user_service_reads_and_writes_mapped_profiles(orm_session):
    service = UserService()

    created, profile = service.create_profile(
        orm_session,
        primary_country="us",
        auth0_id="auth0|direct",
        username="direct-user",
        user_since=123,
    )
    duplicate_created, duplicate = service.create_profile(
        orm_session,
        primary_country="us",
        auth0_id="auth0|direct",
        username="ignored",
        user_since=456,
    )

    assert created is True
    assert duplicate_created is False
    assert isinstance(profile, UserProfile)
    assert duplicate is profile
    assert service.get_profile(orm_session, auth0_id="auth0|direct") is profile


def test_user_service_updates_the_mapped_profile(orm_session):
    service = UserService()
    _, profile = service.create_profile(
        orm_session,
        primary_country="us",
        auth0_id="auth0|update",
        username=None,
        user_since=123,
    )

    updated = service.update_profile(
        orm_session,
        user_id=profile.user_id,
        primary_country="uk",
        username="updated-user",
        user_since=456,
    )

    assert updated is profile
    assert profile.primary_country == "uk"
    assert profile.username == "updated-user"
