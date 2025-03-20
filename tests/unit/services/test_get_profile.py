import pytest
from unittest.mock import MagicMock
from unittest.mock import patch
from policyengine_api.services.user_service import UserService

service = UserService()

valid_user_record = {
    "user_id": 1,
    "auth0_id": "123",
    "username": "person1",
    "primary_country": "US",
    "user_since": 1678658906,
}


@pytest.fixture
def existing_user_profile(test_db):
    """Insert an existing user record into the database."""
    test_db.query(
        "INSERT INTO user_profiles (user_id, auth0_id, username, primary_country, user_since) VALUES (?, ?, ?, ?, ?)",
        (
            valid_user_record["user_id"],
            valid_user_record["auth0_id"],
            valid_user_record["username"],
            valid_user_record["primary_country"],
            valid_user_record["user_since"],
        ),
    )
    inserted_row = test_db.query(
        "SELECT * FROM user_profiles WHERE auth0_id = ?",
        (valid_user_record["auth0_id"],),
    ).fetchone()

    return inserted_row


class TestGetProfile:

    def test_get_profile_id_not_specified(self):
        # GIVEN no ID
        # WHEN we call get_profile with no auth0_id or user_id

        # Then a ValueError should be raised
        with pytest.raises(
            ValueError, match="you must specify either auth0_id or user_id"
        ):
            service.get_profile()

    def test_get_profile_nonexistent_record(self):
        # GIVEN nonexistent record
        INVALID_RECORD_ID = "invalid"

        # WHEN we call get_profile with nonexistent user
        result = service.get_profile(auth0_id=INVALID_RECORD_ID)

        # THEN result is None
        assert result is None

    def test_get_profile_auth0_id(self, existing_user_profile):
        # WHEN we call get_profile with auth0_id
        result = service.get_profile(
            auth0_id=existing_user_profile["auth0_id"]
        )

        # THEN returns record
        assert result == existing_user_profile

    def test_get_profile_user_id(self, existing_user_profile):
        # WHEN we call get_profile with user_id
        result = service.get_profile(user_id=existing_user_profile["user_id"])

        # THEN returns record
        assert result == existing_user_profile

    def test_get_profile_id_priority(self, test_db, existing_user_profile):

        # WHEN we call get_profile with auth0_id and user_id
        result = service.get_profile(
            auth0_id=existing_user_profile["auth0_id"],
            user_id=existing_user_profile["user_id"],
        )

        # THEN returns record using auth0_id
        record = test_db.query(
            "SELECT * FROM user_profiles WHERE auth0_id = ?",
            (valid_user_record["auth0_id"],),
        ).fetchone()

        assert result == record
