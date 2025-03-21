import pytest
import unittest.mock as mock
from policyengine_api.services.user_service import UserService
user_service = UserService()

class TestCreateProfile:
    def test_create_profile_valid(self, test_db):
        auth0_id = 'test_auth0_id'
        primary_country = 'us'
        username = 'test_username'
        user_since = 2025

        def fetch_created_record():
            return test_db.query(
                'SELECT * FROM user_profiles WHERE auth0_id = ?', (auth0_id,)
            ).fetchone()

        result = user_service.create_profile(
            primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )

        assert result[0] is True

        user_record = fetch_created_record()
        assert user_record is not None
        assert user_record['auth0_id'] == auth0_id  # Ensure column name is correct
        assert user_record['primary_country'] == primary_country
        assert user_record['username'] == username
        assert user_record['user_since'] == user_since

    
    def test_create_profile_invalid_argument(self, test_db):
        primary_country = 'us'
        username = 'test_username'
        user_since = 2025
        with pytest.raises(
            Exception,
            match=r"UserService.create_profile\(\) missing 1 required positional argument: 'auth0_id'",
        ):
            user_service.create_profile(
                primary_country=primary_country, username=username, user_since=user_since
            )
        

    def test_create_profile_duplicate(self, test_db):
        auth0_id = 'test_auth0_id'
        primary_country = 'us'
        username = 'test_username'
        user_since = 2025
        result1 = user_service.create_profile(
            primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )
        
        
        result2 = user_service.create_profile(
                primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )
        assert result2[0] == False
