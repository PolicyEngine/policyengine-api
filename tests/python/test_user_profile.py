import json
from datetime import datetime
from policyengine_api.data import database
import time


class TestUserProfiles:
    # Define the profile to test against
    auth0_id = "dworkin"
    primary_country = "us"
    user_since = datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S")

    test_profile = {
        "auth0_id": auth0_id,
        "primary_country": primary_country,
        "user_since": user_since,
    }

    """
    Test adding a record to user_profiles
    """

    def test_set_and_get_record(self, rest_client):
        database.query(
            f"DELETE FROM user_profiles WHERE auth0_id = ? AND primary_country = ?",
            (
                self.auth0_id,
                self.primary_country,
            ),
        )

        res = rest_client.post("/us/user_profile", json=self.test_profile)
        return_object = json.loads(res.text)

        print(return_object)
        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.get(f"/us/user_profile?auth0_id={self.auth0_id}")
        return_object = json.loads(res.text)

        assert res.status_code == 200
        assert return_object["status"] == "ok"
        assert return_object["result"]["auth0_id"] == self.auth0_id
        assert (
            return_object["result"]["primary_country"] == self.primary_country
        )
        assert return_object["result"]["username"] == None

        user_id = return_object["result"]["user_id"]

        res = rest_client.get(f"/us/user_profile?user_id={user_id}")
        return_object = json.loads(res.text)

        assert res.status_code == 200
        assert return_object["status"] == "ok"
        assert (
            return_object["result"]["primary_country"] == self.primary_country
        )
        assert return_object["result"].get("auth0_id") is None
        assert return_object["result"]["username"] == None

        test_username = "maxwell"
        updated_profile = {"user_id": user_id, "username": test_username}

        res = rest_client.put("/us/user_profile", json=updated_profile)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        row = database.query(
            f"SELECT * FROM user_profiles WHERE user_id = ? AND username = ?",
            (user_id, test_username),
        ).fetchone()
        assert row is not None

        malicious_updated_profile = {
            **updated_profile,
            "auth0_id": self.auth0_id,
        }

        res = rest_client.put(
            "/us/user_profile", json=malicious_updated_profile
        )
        return_object = json.loads(res.text)

        assert res.status_code == 403

        database.query(
            f"DELETE FROM user_profiles WHERE user_id = ? AND auth0_id = ? AND primary_country = ?",
            (user_id, self.auth0_id, self.primary_country),
        )
