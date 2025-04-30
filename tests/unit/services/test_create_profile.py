import pytest
from policyengine_api.services.user_service import UserService
from datetime import datetime

user_service = UserService()

<<<<<<< HEAD

class TestCreateProfile:

    # Test creating a valid user profile
    def test_create_profile_valid(self, test_db):
        garbage_auth0_id = "test_garbage_auth0_id_123"
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

=======
user_service = UserService()


class TestCreateProfile:

    def test_create_profile_valid(self, test_db):
        # Use a more explicit garbage ID to not imply any formatting
        garbage_auth0_id = "test_garbage_auth0_id_123"
        primary_country = "us"  # Use correct country format
        username = "test_username"
        user_since = 20250101  # Use BIGINT as expected by the database

        # Create the profile
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        result = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

<<<<<<< HEAD
        assert result[0] is True

=======
        # Verify the result from the service
        assert result[0] is True

        # Query the database directly to verify the record was created
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        created_record = test_db.query(
            "SELECT * FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

<<<<<<< HEAD
=======
        # Verify the record was created with the correct values
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        assert created_record is not None
        assert created_record["auth0_id"] == garbage_auth0_id
        assert created_record["primary_country"] == primary_country
        assert created_record["username"] == username
        assert created_record["user_since"] == user_since

<<<<<<< HEAD
    # Test that creating a profile without auth0_id raises an exception
    def test_create_profile_missing_auth0_id(self, test_db):
        primary_country = "us"
        username = "test_username"
        user_since = int(datetime.now().timestamp())

=======
    def test_create_profile_missing_auth0_id(self, test_db):
        # More descriptive test name for this specific invalid case
        primary_country = "us"
        username = "test_username"
        user_since = 20250101

        # Test that we get an error when auth0_id is missing
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        with pytest.raises(
            Exception,
            match=r"UserService.create_profile\(\) missing 1 required positional argument: 'auth0_id'",
        ):
            user_service.create_profile(
                primary_country=primary_country,
                username=username,
                user_since=user_since,
            )

<<<<<<< HEAD
=======
        # Verify that no record was created in the database
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        records = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE username = ?",
            (username,),
        ).fetchone()

        assert records["count"] == 0

<<<<<<< HEAD
    # Test that creating a duplicate profile returns False
=======
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
    def test_create_profile_duplicate(self, test_db):
        garbage_auth0_id = "duplicate_test_id_456"
        primary_country = "us"
        username = "duplicate_test_username"
<<<<<<< HEAD
        user_since = int(datetime.now().timestamp())

=======
        user_since = 20250101

        # Create the first profile and verify it was created
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        result1 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

        assert result1[0] is True

<<<<<<< HEAD
=======
        # Verify the record exists in the database
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        record_count_before = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_before["count"] == 1

<<<<<<< HEAD
=======
        # Attempt to create a duplicate profile
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        result2 = user_service.create_profile(
            primary_country=primary_country,
            auth0_id=garbage_auth0_id,
            username=username,
            user_since=user_since,
        )

<<<<<<< HEAD
        assert result2[0] is False

=======
        # Verify that the second attempt returns False
        assert result2[0] is False

        # Verify that no additional record was created in the database
>>>>>>> 935870fe (Fixed implementation of create_test_profile.py and changelog entry format)
        record_count_after = test_db.query(
            "SELECT COUNT(*) as count FROM user_profiles WHERE auth0_id = ?",
            (garbage_auth0_id,),
        ).fetchone()

        assert record_count_after["count"] == 1
