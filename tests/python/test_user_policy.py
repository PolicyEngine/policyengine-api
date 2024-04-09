import json
from policyengine_api.data import database


class TestUserPolicies:

    # Define the policy to test against
    country_id = "us"
    policy_id = 2
    user_id = "maxwell"
    label = "dworkin"
    test_policy = {"policy_id": policy_id, "user_id": user_id, "label": label}

    """
  Test adding a record to user_policies
  """

    def test_set_and_get_record(self, rest_client):
        database.query(
            f"DELETE FROM user_policies WHERE policy_id = ? AND user_id = ? AND label = ?",
            (self.policy_id, self.user_id, self.label),
        )

        res = rest_client.post("/us/user_policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.get(f"/us/user_policy/{self.user_id}")
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert return_object["result"][0]["policy_id"] == self.policy_id

        database.query(
            f"DELETE FROM user_policies WHERE policy_id = ? AND user_id = ? AND label = ?",
            (self.policy_id, self.user_id, self.label),
        )
