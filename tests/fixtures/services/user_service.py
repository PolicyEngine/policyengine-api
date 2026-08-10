import pytest

from policyengine_api.data.v1_models import UserProfile

valid_user_record = {
    "user_id": 1,
    "auth0_id": "123",
    "username": "person1",
    "primary_country": "US",
    "user_since": 1678658906,
}


@pytest.fixture
def existing_user_profile(orm_session):
    """Insert an existing user record into the database."""
    profile = UserProfile(
        user_id=valid_user_record["user_id"],
        auth0_id=valid_user_record["auth0_id"],
        username=valid_user_record["username"],
        primary_country=valid_user_record["primary_country"],
        user_since=valid_user_record["user_since"],
    )
    orm_session.add(profile)
    orm_session.commit()
    return profile
