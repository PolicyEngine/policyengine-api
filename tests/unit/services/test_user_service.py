import pytest
from policyengine_api.services.user_service import UserService

from tests.fixtures.services.user_service import (
    valid_user_record,
    existing_user_profile,
)

service = UserService()


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
        result = service.get_profile(auth0_id=existing_user_profile["auth0_id"])

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
