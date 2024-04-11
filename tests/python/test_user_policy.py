import json
from policyengine_api.data import database


class TestUserPolicies:
    # Define the policy to test against
    country_id = "us"
    baseline_id = 2
    baseline_label = "Current law"
    reform_id = 0
    reform_label = "dworkin"
    user_id = "maxwell"
    test_policy = {
        "country_id": country_id,
        "baseline_id": baseline_id, 
        "baseline_label": baseline_label, 
        "reform_id": reform_id, 
        "reform_label" :reform_label, 
        "user_id": user_id, 
    }

    """
  Test adding a record to user_policies
  """

    def test_set_and_get_record(self, rest_client):
        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND reform_label = ?",
            (self.reform_id, self.baseline_id, self.user_id, self.reform_label),
        )

        res = rest_client.post("/us/user_policy", json=self.test_policy)
        return_object = json.loads(res.text)

        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.get(f"/us/user_policy/{self.user_id}")
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert return_object["result"][0]["reform_id"] == self.reform_id
        assert return_object["result"][0]["baseline_id"] == self.baseline_id

        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND reform_label = ?",
            (self.reform_id, self.baseline_id, self.user_id, self.reform_label),
        )
