import pytest
import json
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


class TestPolicyCreation:
    # Define the policy to test against
    country_id = "us"
    policy_json = {"sample_parameter": {"2024-01-01.2025-12-31": True}}
    label = "dworkin"
    test_policy = {"data": policy_json, "label": label}
    policy_hash = hash_object(policy_json)

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

class TestPolicySearch:
    
    country_id = "us"
    policy_json = {"sample_input": {"2023-01-01.2024-12-31": True}}
    label = "maxwell"
    policy_hash = hash_object(policy_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    # Pre-seed database with duplicate policies
    for i in range(2):
        database.query(
            f"INSERT INTO policy (country_id, label, policy_json, policy_hash, api_version) VALUES (?, ?, ?, ?, ?)",
            (country_id, label, json.dumps(policy_json), policy_hash, api_version),
        )

    db_output = database.query(
        f"SELECT * FROM policy WHERE label = ?",
        (label,),
    ).fetchall()

    def test_search_all_policies(self, rest_client):
        res = rest_client.get("/us/policies")
        return_object = json.loads(res.text)

        filtered_return = list(filter(lambda x: x["label"] == self.label, return_object["result"]))

        assert return_object["status"] == "ok"
        assert len(filtered_return) == len(self.db_output)

    def test_search_unique_policies(self, rest_client):

        res = rest_client.get("/us/policies?unique_only=true")
        return_object = json.loads(res.text)

        filtered_return = list(filter(lambda x: x["label"] == self.label, return_object["result"]))

        assert return_object["status"] == "ok"
        assert len(filtered_return) == 1

        # Clean up duplicate policies created
        database.query(
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
        )