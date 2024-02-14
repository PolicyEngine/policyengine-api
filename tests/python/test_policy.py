import pytest
import json
from policyengine_api.data import database
from policyengine_api.utils import hash_object


class TestPolicy:
    # Define the policy to test against
    country_id = "us"
    policy_json = {"sample_parameter": {"2024-01-01.2025-12-31": True}}
    label = "dworkin"
    test_policy = {"data": policy_json, "label": label}
    policy_hash = hash_object(json.dumps(policy_json))

    """
  Test creating a policy, then ensure that duplicating
  that policy generates the correct response within the
  app; this requires sequential processing, hence the 
  need for a separate Python-based test
  """

    def test_create_unique_policy(self, rest_client):
        database.query(
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
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
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
        )
