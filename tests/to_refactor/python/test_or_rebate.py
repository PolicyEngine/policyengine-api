import json
import time
import datetime
from policyengine_api.data import local_database
import sys


def test_or_rebate_us(rest_client):
    """
    Test that the Oregon Rebate (Measure 118) policy is calculated
    and provides logical outputs for US-wide sim
    """

    return or_rebate_runner(rest_client, "us")


def test_or_rebate_ehanced_us(rest_client):
    """
    Test that the Oregon Rebate (Measure 118) policy is calculated
    and provides logical outputs for sim using enhanced_us dataset
    """

    return or_rebate_runner(rest_client, "enhanced_us")


def test_or_rebate_or(rest_client):
    """
    Test that the Oregon Rebate (Measure 118) policy is calculated
    and provides logical outputs for Oregon sim
    """

    return or_rebate_runner(rest_client, "or")


def or_rebate_runner(rest_client, region: str = "us"):
    """
    Run the Oregon Rebate (Measure 118) policy test, depending on provided
    region (defaults to "us")
    """

    test_year = 2024
    default_policy = 2

    with open(
        "./tests/python/data/or_rebate_measure_118.json",
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
    assert result["budget"]["budgetary_impact"] is not None

    # Ensure that Gini coefficient is logical (between 0.25 and 0.75)
    assert result["inequality"]["gini"]["baseline"] > 0.25
    assert result["inequality"]["gini"]["baseline"] < 0.75

    # Ensure that top_10_pct_share is logical
    assert result["inequality"]["top_10_pct_share"]["baseline"] < 1

    local_database.query(
        f"DELETE FROM policy WHERE id = ? ",
        (policy_id,),
    )
