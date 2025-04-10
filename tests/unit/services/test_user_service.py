import pytest
from policyengine_api.services.user_service import UserService

user_service = UserService()


# Test data for new user
new_user_country_id = "us"
new_user_auth_id = "new_unique_auth0_id_123"
new_user_username = "newuser"
new_user_since = 1742540470533
new_user_params = [
    new_user_username,
    new_user_auth_id,
    new_user_username,
    new_user_since,
]

# Test data for existing user
existing_user_country_id = "us"
existing_user_auth_id = "existing_auth0_id"
existing_user_username = "newuser"
existing_user_since = 1742540470533
existing_user_params = [
    existing_user_country_id,
    existing_user_auth_id,
    existing_user_username,
    existing_user_since,
]


@pytest.fixture
def seed_user(test_db):
    """Seed the database with an existing user"""
    test_db.query(
        """
        INSERT INTO user_profiles (primary_country, auth0_id, username, user_since)
        VALUES (?, ?, ?, ?)
        """,
        tuple(existing_user_params),
    )


def test_create_new_user_profile(test_db):
    """Test that a new user profile is created successfully"""
    res = user_service.create_profile(*new_user_params)
    assert res[0] is True
    assert res[1] is not None
    assert res[1]["auth0_id"] == new_user_params[1]


def test_duplicate_user_profile(seed_user, test_db):
    """Test that creating a profile for an already existing user returns False"""
    res = user_service.create_profile(*existing_user_params)
    assert res[0] is False
    assert res[1] is not None
    assert res[1]["auth0_id"] == existing_user_params[1]
