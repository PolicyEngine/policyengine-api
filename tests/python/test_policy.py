import pytest
import json
from policyengine_api.data import database


class TestPolicy:
    # Define the policy to test against
    country_id = "us"
    policy_json = ({"sample_parameter": "maxwell"},)
    label = "cruft"
    test_policy = {"data": policy_json, "label": label}

    """
  Test creating a policy, then ensure that duplicating
  that policy generates the correct response within the
  app; this requires sequential processing, hence the 
  need for a separate Python-based test
  """

    def test_create_unique_policy(self, rest_client):

        database.query(
            f"DELETE FROM policy WHERE policy_json = ? AND label = ? AND country_id = ?",
            (json.dumps(self.policy_json), self.label, self.country_id),
        )

        res = rest_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

    def test_create_nonunique_policy(self, rest_client):

        res = rest_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        database.query(
            f"DELETE FROM policy WHERE policy_json = ? AND label = ? AND country_id = ?",
            (json.dumps(self.policy_json), self.label, self.country_id),
        )
