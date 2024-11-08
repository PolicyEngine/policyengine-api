import json
from datetime import datetime
from policyengine_api.data import database
from sys import stderr
import time


class TestUserPolicies:
    # Define the policy to test against
    country_id = "us"
    baseline_id = 2
    baseline_label = "Current law"
    reform_id = 0
    reform_label = "dworkin"
    user_id = 15
    geography = "us"
    year = "2024"
    number_of_provisions = 3
    api_version = "0.123.45"
    # Simulate JS's Date.now()
    added_date = int(time.time())
    updated_date = int(time.time())
    budgetary_impact = "$13 billion"

    test_policy = {
        "country_id": country_id,
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "reform_id": reform_id,
        "reform_label": reform_label,
        "user_id": user_id,
        "geography": geography,
        "year": year,
        "number_of_provisions": number_of_provisions,
        "api_version": api_version,
        "added_date": added_date,
        "updated_date": updated_date,
        "budgetary_impact": budgetary_impact,
    }

    updated_api_version = "0.456.78"
    updated_test_policy = {
        **test_policy,
        "api_version": updated_api_version,
        "updated_date": int(time.time()),
    }

    """
  Test adding a record to user_policies
  """

    def test_set_and_get_record(self, rest_client):
        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND reform_label = ? AND geography = ? AND year = ?",
            (
                self.reform_id,
                self.baseline_id,
                self.user_id,
                self.reform_label,
                self.geography,
                self.year,
            ),
        )

        res = rest_client.post("/us/user-policy", json=self.test_policy)
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.get(f"/us/user-policy/{self.user_id}")
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert return_object["result"][0]["reform_id"] == self.reform_id
        assert return_object["result"][0]["baseline_id"] == self.baseline_id

        res = rest_client.post("/us/user-policy", json=self.test_policy)
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        user_policy_id = return_object["result"]["id"]
        updated_test_policy = {
            **self.updated_test_policy,
            "id": user_policy_id,
        }

        res = rest_client.put("/us/user-policy", json=updated_test_policy)
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        row = database.query(
            f"SELECT * FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND reform_label = ? AND geography = ? AND year = ?",
            (
                self.reform_id,
                self.baseline_id,
                self.user_id,
                self.reform_label,
                self.geography,
                self.year,
            ),
        ).fetchone()
        readable_row = dict(row)
        assert readable_row["api_version"] == self.updated_api_version

        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND reform_label = ? AND geography = ? AND year = ?",
            (
                self.reform_id,
                self.baseline_id,
                self.user_id,
                self.reform_label,
                self.geography,
                self.year,
            ),
        )

    def test_nulls(self, rest_client):

        nulled_test_policy = {
            **self.test_policy,
            "baseline_label": None,
            "reform_label": None,
        }

        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND  geography = ? AND year = ?",
            (
                self.reform_id,
                self.baseline_id,
                self.user_id,
                self.geography,
                self.year,
            ),
        )

        res = rest_client.post("/us/user-policy", json=nulled_test_policy)
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

        res = rest_client.post("/us/user-policy", json=nulled_test_policy)
        return_object = json.loads(res.text)
        print(return_object)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        database.query(
            f"DELETE FROM user_policies WHERE reform_id = ? AND baseline_id = ? AND user_id = ? AND geography = ? AND year = ?",
            (
                self.reform_id,
                self.baseline_id,
                self.user_id,
                self.geography,
                self.year,
            ),
        )
