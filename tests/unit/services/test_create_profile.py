import pytest
import unittest.mock as mock
import time
from policyengine_api.services.user_service import UserService

userService = UserService()

class TestCreateProfile:

    def test_create_profile_valid(self):
        auth0_id = 'test-auth-id'
        primary_country = 'United States'
        username = 'test_username'
        user_since = int(time.time() * 1000)  
        
        result = userService.create_profile(
            primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )
        
        assert result[0] is True
        user_record = userService.get_profile(auth0_id)
        assert user_record is not None
        assert user_record['auth0_id'] == auth0_id
        assert user_record['primary_country'] == primary_country
        assert user_record['username'] == username
        assert user_record['user_since'] == user_since
    
    def test_create_profile_invalid(self):
        primary_country = 'United States'
        username = 'test_username'
        user_since = int(time.time() * 1000)  
        with pytest.raises(
            Exception,
            match=r"UserService.create_profile\(\) missing 1 required positional argument: 'auth0_id'",
        ):
            userService.create_profile(
                primary_country=primary_country, username=username, user_since=user_since
            )

    def test_create_profile_duplicate(self):
        auth0_id = 'test-auth-id'
        primary_country = 'United States'
        username = 'test_username'
        user_since = int(time.time() * 1000)  
        result1 = userService.create_profile(
            primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )
        
        
        result2 = userService.create_profile(
                primary_country=primary_country, auth0_id=auth0_id, username=username, user_since=user_since
        )
        assert result2[0] == False