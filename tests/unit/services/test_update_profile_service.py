import pytest
from policyengine_api.services.user_service import UserService

from tests.fixtures.services.user_service import (
    valid_user_record,
    existing_user_profile,
)

service = UserService()


class TestUpdateProfile:

    def test_update_profile_given_existing_record(
        self, test_db, existing_user_profile
    ):
        # GIVEN an existing profile record (from fixture)

        # WHEN we call update_profile with new data
        updated_username = "updated_username"
        updated_country = "uk"

        result = service.update_profile(
            user_id=existing_user_profile["user_id"],
            primary_country=updated_country,
            username=updated_username,
            user_since=existing_user_profile["user_since"],
        )

        # THEN the method should return True for successful update
        assert result is True

        # AND the database should be updated with new values
        updated_record = test_db.query(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (existing_user_profile["user_id"],),
        ).fetchone()

        assert updated_record["username"] == updated_username
        assert updated_record["primary_country"] == updated_country

    def test_update_profile_given_nonexistent_record(self, test_db):
        # GIVEN a nonexistent profile record id
        NONEXISTENT_ID = 999

        # WHEN we call update_profile for this nonexistent record
        result = service.update_profile(
            user_id=NONEXISTENT_ID,
            primary_country="uk",
            username="newuser",
            user_since="2024-01-01",
        )

        # THEN the result should be False
        assert result is False

    def test_update_profile_with_partial_fields(
        self, test_db, existing_user_profile
    ):
        # GIVEN an existing profile record (from fixture)

        # WHEN we call update_profile with only some fields provided
        updated_country = "CA"
        original_username = existing_user_profile["username"]

        result = service.update_profile(
            user_id=existing_user_profile["user_id"],
            primary_country=updated_country,
            username=None,
            user_since=existing_user_profile["user_since"],
        )

        # THEN the method should return True for successful update
        assert result is True

        # AND only the provided fields should be updated
        updated_record = test_db.query(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (existing_user_profile["user_id"],),
        ).fetchone()

        assert updated_record["primary_country"] == updated_country
        assert (
            updated_record["username"] == original_username
        )  # Username should remain unchanged

    def test_update_profile_with_database_error(
        self, monkeypatch, existing_user_profile
    ):
        # GIVEN an existing profile record (from fixture)

        # AND a database that raises an exception
        def mock_db_query_error(*args, **kwargs):
            raise Exception("Database error")

        monkeypatch.setattr(
            "policyengine_api.data.database.query", mock_db_query_error
        )

        # WHEN we call update_profile
        # THEN an exception should be raised
        with pytest.raises(Exception, match="Database error"):
            service.update_profile(
                user_id=existing_user_profile["user_id"],
                primary_country="US",
                username="testuser",
                user_since="2023-01-01",
            )

    def test_update_profile_id_not_specified(self):
        # GIVEN no user_id specified

        # WHEN we call update_profile with None as user_id
        # THEN a ValueError should be raised
        with pytest.raises(
            ValueError, match="you must specify either auth0_id or user_id"
        ):
            service.update_profile(
                user_id=None,
                primary_country="US",
                username="testuser",
                user_since="2023-01-01",
            )
