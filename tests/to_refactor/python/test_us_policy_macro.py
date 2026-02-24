import json
import time
import datetime
from policyengine_api.data import local_database
import sys

# This test is a temporary test to ensure state impacts work properly.
# It should be replaced with more comprehensive integration tests, then removed.


def test_utah(rest_client):
    """
    Test that the a given Utah policy is calculated
    and provides logical outputs for a sim
    """

    return utah_reform_runner(rest_client, "ut")


def utah_reform_runner(rest_client, region: str = "us"):
    """
    Run the given Utah policy test, depending on provided
    region (defaults to "us")
    """

    test_year = 2025
    default_policy = 2

    with open(
        "./tests/data/utah_reform.json",
        "r",
        encoding="utf-8",
    ) as f:
        data_object = json.load(f)

    local_database.query("DELETE FROM reform_impact WHERE country_id = 'us'")

    policy_create = rest_client.post(
        "/us/policy",
        headers={"Content-Type": "application/json"},
        json=data_object,
    )

    assert policy_create.status_code in [200, 201]
    assert policy_create.json["result"] is not None

    policy_id = policy_create.json["result"]["policy_id"]
    assert policy_id is not None

    query = f"/us/economy/{policy_id}/over/{default_policy}?region={region}&time_period={test_year}"
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
    ), f'Expected status "ok", got {economy_response.json["status"]} with message "{economy_response.json}"'

    result = economy_response.json["result"]

    assert result is not None

    # Ensure that there is some budgetary impact
    cost = round(result["budget"]["budgetary_impact"] / 1e6, 1)
    assert (
        cost / 1867.4 - 1
    ) < 0.01, (
        f"Expected budgetary impact to be 1867.4 million, got {cost} million"
    )

    assert (
        result["intra_decile"]["all"]["Lose less than 5%"] / 0.534 - 1
    ) < 0.01, (
        f"Expected 53.4% of people to lose less than 5%, got "
        f"{result['intra_decile']['all']['Lose less than 5%']}"
    )

    local_database.query(
        f"DELETE FROM policy WHERE id = ? ",
        (policy_id,),
    )
