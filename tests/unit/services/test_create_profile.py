import pytest
from policyengine_api.services.user_service import UserService
from datetime import datetime

user_service = UserService()


class TestCreateProfile:

    # Test creating a valid user profile
    def test_create_profile_valid(self, test_db):
        garbage_auth0_id = "test_garbage_auth0_id_123"
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

        result = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        assert result[0] is True

        created_record = test_db.query(
            "SELECT * FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert created_record is not None
        assert created_record["auth0_id"] == garbage_auth0_id
        assert created_record["primary_country"] == primary_country
        assert created_record["username"] == username
        assert created_record["user_since"] == user_since

    # Test that creating a profile without auth0_id raises an exception
    def test_create_profile_missing_auth0_id(self, test_db):
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

        with pytest.raises(
            Exception,
            match=r"UserService.create_profile\(\) missing 1 required positional argument: 'auth0_id'",
        ):
            user_service.create_profile(
                primary_country=primary_country,
                username=username,
                user_since=user_since,
            )

        records = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE username = ?",
            (username,),
        ).fetchone()

        assert records["count"] == 0

    # Test that creating a duplicate profile returns False
    def test_create_profile_duplicate(self, test_db):
        garbage_auth0_id = "duplicate_test_id_456"
        primary_country = "us"
        username = "duplicate_test_username"
        user_since = int(datetime.now().timestamp())

        result1 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        assert result1[0] is True

        record_count_before = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_before["count"] == 1

        result2 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        assert result2[0] is False

        record_count_after = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_after["count"] == 1
