from datetime import datetime
from unittest.mock import patch
import time
import pytest
import os

from tests.fixtures.reform_economies_fixtures import (
    mock_all_services,
    prepare_us_reforms,
    prepare_uk_reforms,
    prepare_state_reforms,
)

from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)

reform_impacts_service = ReformImpactsService()

"""
This file defines a series of integration tests meant to
ensure that code changes do not introduce regressions that
cause the API to fail to calculate society-wide economic outputs.

These tests patch all database calls, instead assuming that the
code connected to the database is functioning correctly. This should
be handled by individual unit tests.
"""


@pytest.mark.parametrize("reform", prepare_us_reforms())
def test_us_reform_economies(rest_client, mock_all_services, reform):
    run_reform_economy_test(rest_client, mock_all_services, reform)


# Skip UK tests when running locally; will fail with 404 due to microdata
@pytest.mark.skipif(
    os.getenv("FLASK_DEBUG", "0") == "1",
    reason="Unable to fetch non-public microdata; skipping test locally",
)
@pytest.mark.parametrize("reform", prepare_uk_reforms())
def test_uk_reform_economies(rest_client, mock_all_services, reform):
    run_reform_economy_test(rest_client, mock_all_services, reform)


@pytest.mark.parametrize("reform", prepare_state_reforms())
def test_state_reform_economies(rest_client, mock_all_services, reform):
    run_reform_economy_test(rest_client, mock_all_services, reform)


def run_reform_economy_test(rest_client, mock_all_services, reform):

    test_year = datetime.now().year
    test_policy_id = 7  # This can be defined as anything greater than 5
    test_current_law = reform["current_law"]
    test_region = reform["region"]
    test_country_id = reform["country_id"]

    query = f"/{test_country_id}/economy/{test_policy_id}/over/{test_current_law}?region={test_region}&time_period={test_year}"

    # Purge any previous reform impact data
    reform_impacts_service.delete_all_reform_impacts()

    # Enqueue an economy-wide sim job
    economy_response = rest_client.get(query)

    # Expect our first outputs to be "computing"
    assert economy_response.status_code == 200
    assert economy_response.json["status"] == "computing", (
        f'Expected first answer status to be "computing" but it is '
        f'{str(economy_response.json["status"])}'
    )

    # While computing, keep polling
    while economy_response.json["status"] == "computing":
        print("Before sleep:", datetime.now())
        time.sleep(3)
        print("After sleep:", datetime.now())
        economy_response = rest_client.get(query)

    # Expect the final status to be "ok"
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
