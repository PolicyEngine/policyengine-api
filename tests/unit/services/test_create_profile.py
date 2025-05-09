import pytest
from policyengine_api.services.user_service import UserService

user_service = UserService()


class TestCreateProfile:

    # Test creating a valid user profile
    def test_create_profile_valid(self, test_db):
        garbage_auth0_id = "test_garbage_auth0_id_123"
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

        # Create the profile
        result = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        # Verify the result from the service
        assert result[0] is True

        # Query the database directly to verify the record was created
        created_record = test_db.query(
            "SELECT * FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        # Verify the record was created with the correct values
        assert created_record is not None
        assert created_record["auth0_id"] == garbage_auth0_id
        assert created_record["primary_country"] == primary_country
        assert created_record["username"] == username
        assert created_record["user_since"] == user_since

    def test_create_profile_missing_auth0_id(self, test_db):
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

        # Test that we get an error when auth0_id is missing
        with pytest.raises(
            Exception,
            match=r"UserService.create_profile\(\) missing 1 required positional argument: 'auth0_id'",
        ):
            user_service.create_profile(
                primary_country=primary_country,
                username=username,
                user_since=user_since,
            )

        # Verify that no record was created in the database
        records = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE username = ?",
            (username,),
        ).fetchone()

        assert records["count"] == 0

    def test_create_profile_duplicate(self, test_db):
        garbage_auth0_id = "duplicate_test_id_456"
        primary_country = "us"
        username = "duplicate_test_username"
        user_since = 20250101

        # Create the first profile and verify it was created
        result1 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        assert result1[0] is True

        # Verify the record exists in the database
        record_count_before = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_before["count"] == 1

        # Attempt to create a duplicate profile
        result2 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        # Verify that the second attempt returns False
        assert result2[0] is False

        # Verify that no additional record was created in the database
        record_count_after = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_after["count"] == 1
