"""
Test basics for /economy endpoints.
"""

import json
import time
import datetime
from policyengine_api.data import local_database


def test_economy_1(rest_client):
    """Add a simple policy and get /economy for that over 2."""
    with open(
        "./tests/python/data/test_economy_1_policy_1.json",
        "r",
        encoding="utf-8",
    ) as data:
        local_database.query(
            "DELETE FROM reform_impact WHERE country_id = 'us'"
        )
        policy_create = rest_client.post(
            "/us/policy",
            headers={"Content-Type": "application/json"},
            data=data,
        )
        assert policy_create.status_code == 201
        assert policy_create.json["result"] is not None
        policy_id = policy_create.json["result"]["policy_id"]
        assert policy_id is not None
        policy_response = rest_client.get(f"/us/policy/{policy_id}")
        assert policy_response.status_code == 200
        assert policy_response.json["status"] == "ok"
        assert policy_response.json["result"]["id"] == policy_id
        policy = policy_response.json["result"]["policy_json"]
        assert policy is not None
        assert policy["gov.abolitions.ccdf_income"] is not None
        assert policy["gov.irs.income.exemption.amount"] is not None
        assert (
            policy["gov.abolitions.ccdf_income"]["2023-01-01.2028-12-31"]
            is True
        )
        assert (
            policy["gov.irs.income.exemption.amount"]["2023-01-01.2028-12-31"]
            == "100"
        )
        query = f"/us/economy/{policy_id}/over/2?region=us&time_period=2023"
        economy_response = rest_client.get(query)
        assert economy_response.status_code == 200
        assert economy_response.json["status"] == "computing", (
            f'Expected first answer status to be "computing" but it is '
            f'{str(economy_response.json["status"])}'
        )
        while economy_response.json["status"] == "computing":
            print("Before sleep:", datetime.datetime.now())
            time.sleep(3)
            print("After sleep:", datetime.datetime.now())
            economy_response = rest_client.get(query)
            print(json.dumps(economy_response.json))
        assert (
            economy_response.json["status"] == "ok"
        ), f'Expected status "ok", got {economy_response.json["status"]}'
