import json
import time

from sqlalchemy import delete, select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import UserProfile


class TestUserProfiles:
    # Define the profile to test against
    auth0_id = "dworkin"
    primary_country = "us"
    # Simulate JS's Date.now()
    user_since = int(time.time())

    test_profile = {
        "auth0_id": auth0_id,
        "primary_country": primary_country,
        "user_since": user_since,
    }

    """
    Test adding a record to user_profiles
    """

    def test_set_and_get_record(self, rest_client):
        with get_v1_session_factory().begin() as session:
            session.execute(
                delete(UserProfile).where(
                    UserProfile.auth0_id == self.auth0_id,
                    UserProfile.primary_country == self.primary_country,
                )
            )

        res = rest_client.post("/us/user-profile", json=self.test_profile)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.get(f"/us/user-profile?auth0_id={self.auth0_id}")
        return_object = json.loads(res.text)

        assert res.status_code == 200
        assert return_object["status"] == "ok"
        assert return_object["result"]["auth0_id"] == self.auth0_id
        assert return_object["result"]["primary_country"] == self.primary_country
        assert return_object["result"]["username"] is None

        user_id = return_object["result"]["user_id"]

        res = rest_client.get(f"/us/user-profile?user_id={user_id}")
        return_object = json.loads(res.text)

        assert res.status_code == 200
        assert return_object["status"] == "ok"
        assert return_object["result"]["primary_country"] == self.primary_country
        assert return_object["result"].get("auth0_id") is None
        assert return_object["result"]["username"] is None

        test_username = "maxwell"
        updated_profile = {"user_id": user_id, "username": test_username}

        res = rest_client.put("/us/user-profile", json=updated_profile)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        with get_v1_session_factory()() as session:
            row = session.scalar(
                select(UserProfile).where(
                    UserProfile.user_id == user_id,
                    UserProfile.username == test_username,
                )
            )
            assert row is not None

        malicious_updated_profile = {**updated_profile, "auth0_id": "BOGUS"}

        res = rest_client.put("/us/user-profile", json=malicious_updated_profile)
        return_object = json.loads(res.text)

        assert res.status_code == 200

        with get_v1_session_factory().begin() as session:
            row = session.scalar(
                select(UserProfile).where(UserProfile.username == test_username)
            )
            assert row.auth0_id == self.auth0_id
            session.delete(row)

    def test_non_existent_record(self, rest_client):
        non_existent_auth0_id = "non-existent-auth0-id"

        res = rest_client.get(f"/us/user-profile?auth0_id={non_existent_auth0_id}")
        assert res.status_code == 404
