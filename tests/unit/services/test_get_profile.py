import pytest
from unittest.mock import MagicMock
from unittest.mock import patch
from policyengine_api.services.user_service import UserService

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

    def test_get_profile_nonexistent_record(self, test_db):
        # GIVEN nonexistent record
        test_db = MagicMock()
        test_db.query.return_value.fetchone.return_value = None

        # WHEN we call get_profile with nonexistent user
        result = service.get_profile(auth0_id="invalid")

        # THEN result is None
        assert result is None

    def test_get_profile_auth0_id(self):
        # GIVEN an auth0_id
        auth0_id = "01"

        # WHEN we call get_profile with auth0_id
        with patch(
            "policyengine_api.services.user_service.database.query"
        ) as mock_query:
            mock_query.return_value.fetchone.return_value = {
                "auth0_id": auth0_id,
                "name": "abc",
            }
            result = service.get_profile(auth0_id=auth0_id)

        # THEN returns record
        assert result == {"auth0_id": auth0_id, "name": "abc"}
        mock_query.assert_called_once_with(
            "SELECT * FROM user_profiles WHERE auth0_id = ?", (auth0_id,)
        )

    def test_get_profile_user_id(self):
        # GIVEN a user_id
        user_id = "1"

        # WHEN we call get_profile with user_id
        with patch(
            "policyengine_api.services.user_service.database.query"
        ) as mock_query:
            mock_query.return_value.fetchone.return_value = {
                "user_id": user_id,
                "name": "abc",
            }
            result = service.get_profile(user_id=user_id)

        # THEN returns record
        assert result == {"user_id": user_id, "name": "abc"}
        mock_query.assert_called_once_with(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        )

    def test_get_profile_id_datatype(self):
        # GIVEN integer instead of string for auth0_id

        # WHEN we call get_profile with auth0_id
        result = service.get_profile(auth0_id=1)

        # THEN returns no records
        assert result is None

    def test_get_profile_id_priority(self):
        # GIVEN auth0_id and user_id
        auth0_id = "1"
        user_id = "123"

        # WHEN we call get_profile with auth0_id and user_id
        with patch(
            "policyengine_api.services.user_service.database.query"
        ) as mock_query:
            mock_query.return_value.fetchone.return_value = {
                "auth0_id": auth0_id,
                "user_id": user_id,
                "name": "abc",
            }
            result = service.get_profile(auth0_id=auth0_id, user_id=user_id)

        # THEN returns record using auth0_id
        assert result == {
            "auth0_id": auth0_id,
            "user_id": user_id,
            "name": "abc",
        }
        mock_query.assert_called_once_with(
            "SELECT * FROM user_profiles WHERE auth0_id = ?", (auth0_id,)
        )
