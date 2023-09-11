import pytest
import json

from policyengine_api.endpoints.household import get_household_under_policy
from policyengine_api.endpoints.policy import get_policy
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data import database
from policyengine_api.api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


TEST_HOUSEHOLD_ID = -100


def create_test_household(household_id, country_id):
    test_household = None

    row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (household_id, country_id),
    ).fetchone()

    if row is not None:
        # WARNING: This could mutate existing arrays if running make-test
        # instead of make debug-test specifically on production server
        remove_test_household(household_id, country_id)

    with open(
        f"./tests/python/data/{country_id}_household.json",
        "r",
        encoding="utf-8",
    ) as f:
        test_household = json.load(f)

    try:
        row = database.query(
            f"INSERT INTO household (id, country_id, household_json, household_hash, label, api_version) VALUES (?, ?, ?, ?, ?, ?)",
            (
                household_id,
                country_id,
                json.dumps(test_household),
                "Garbage value",
                "Garbage value",
                "0.0.0",
            ),
        )

    except Exception as err:
        raise err

    return household_id


def remove_test_household(household_id, country_id):

    row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (household_id, country_id),
    ).fetchone()

    if row is not None:
        try:
            database.query(
                f"DELETE FROM household WHERE id = ? AND country_id = ?",
                (household_id, country_id),
            )
        except Exception as err:
            raise err

    return True


def remove_calculated_hup(household_id, policy_id, country_id):
    """
    Function to remove the calculated household under policy generated
    by get_household_under_policy, for testing purposes
    """

    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    try:
        database.query(
            f"DELETE FROM computed_household WHERE household_id = ? AND policy_id = ? AND api_version = ?",
            (household_id, policy_id, api_version),
        )
    except Exception as err:
        raise err


def test_us_household_under_policy():
    """
    Test that a US household under current law is created correctly
    """
    # Note: Attempted to mock the database.query statements in get_household_under_policy,
    # but was unable to, hence the (less secure) emission of SQL creation, followed by deletion
    CURRENT_LAW_US = 2

    expected_object = None
    with open(
        "./tests/python/data/us_household_under_policy_target.json",
        "r",
        encoding="utf-8",
    ) as f:
        expected_object = json.load(f)

    create_test_household(TEST_HOUSEHOLD_ID, "us")

    test_row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (TEST_HOUSEHOLD_ID, "us"),
    ).fetchone()

    result_object = get_household_under_policy(
        "us", TEST_HOUSEHOLD_ID, CURRENT_LAW_US
    )["result"]

    remove_test_household(TEST_HOUSEHOLD_ID, "us")

    remove_calculated_hup(TEST_HOUSEHOLD_ID, CURRENT_LAW_US, "us")

    # Remove variables that are calculated randomly:
    del expected_object["households"]["your household"]["county"]
    del expected_object["households"]["your household"]["county_str"]
    del expected_object["households"]["your household"]["three_digit_zip_code"]
    del expected_object["households"]["your household"]["zip_code"]
    del expected_object["households"]["your household"]["ccdf_county_cluster"]

    del result_object["households"]["your household"]["county"]
    del result_object["households"]["your household"]["county_str"]
    del result_object["households"]["your household"]["three_digit_zip_code"]
    del result_object["households"]["your household"]["zip_code"]
    del result_object["households"]["your household"]["ccdf_county_cluster"]

    # Remove person_ids (note that this is a bug driven by JSON's inherent
    # unordered nature)
    for person in expected_object["people"]:
        del expected_object["people"][person]["person_id"]

    for person in result_object["people"]:
        del result_object["people"][person]["person_id"]

    for marital_unit in expected_object["marital_units"]:
        del expected_object["marital_units"][marital_unit]["marital_unit_id"]

    for marital_unit in result_object["marital_units"]:
        del result_object["marital_units"][marital_unit]["marital_unit_id"]

    assert expected_object == result_object


def test_uk_household_under_policy():
    """
    Test that a UK household under current law is created correctly
    """
    # Note: Attempted to mock the database.query statements in get_household_under_policy,
    # but was unable to, hence the (less secure) emission of SQL creation, followed by deletion
    CURRENT_LAW_UK = 1

    expected_object = None
    with open(
        "./tests/python/data/uk_household_under_policy_target.json",
        "r",
        encoding="utf-8",
    ) as f:
        expected_object = json.load(f)

    create_test_household(TEST_HOUSEHOLD_ID, "uk")

    test_row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (TEST_HOUSEHOLD_ID, "uk"),
    ).fetchone()

    result_object = get_household_under_policy(
        "uk", TEST_HOUSEHOLD_ID, CURRENT_LAW_UK
    )["result"]

    remove_test_household(TEST_HOUSEHOLD_ID, "uk")

    remove_calculated_hup(TEST_HOUSEHOLD_ID, CURRENT_LAW_UK, "uk")

    # Remove child_index (note that this is a bug driven by JSON's inherent
    # unordered nature)
    for person in expected_object["people"]:
        del expected_object["people"][person]["child_index"]

    for person in result_object["people"]:
        del result_object["people"][person]["child_index"]

    assert expected_object == result_object


def test_get_calculate(client):
    """
    Test the get_calculate endpoint with the same data as
    test_us_household_under_policy. Note that redis must be running
    for this test to function properly.
    """

    CURRENT_LAW_US = 2

    expected_object = None
    test_household = None
    test_object = {}

    with open(
        "./tests/python/data/us_household_under_policy_target.json",
        "r",
        encoding="utf-8",
    ) as f:
        expected_object = json.load(f)

    with open(
        f"./tests/python/data/us_household.json", "r", encoding="utf-8"
    ) as f:
        test_household = json.load(f)

    test_policy = get_policy("us", CURRENT_LAW_US)["result"]["policy_json"]

    test_object["policy"] = test_policy
    test_object["household"] = test_household

    res = client.post("/us/calculate", json=test_object)
    result_object = json.loads(res.text)["result"]

    # Remove variables that are calculated randomly:
    del expected_object["households"]["your household"]["county"]
    del expected_object["households"]["your household"]["county_str"]
    del expected_object["households"]["your household"]["three_digit_zip_code"]
    del expected_object["households"]["your household"]["zip_code"]
    del expected_object["households"]["your household"]["ccdf_county_cluster"]

    del result_object["households"]["your household"]["county"]
    del result_object["households"]["your household"]["county_str"]
    del result_object["households"]["your household"]["three_digit_zip_code"]
    del result_object["households"]["your household"]["zip_code"]
    del result_object["households"]["your household"]["ccdf_county_cluster"]

    # Remove person_ids (note that this is a bug driven by JSON's inherent
    # unordered nature)
    for person in expected_object["people"]:
        del expected_object["people"][person]["person_id"]

    for person in result_object["people"]:
        del result_object["people"][person]["person_id"]

    for marital_unit in expected_object["marital_units"]:
        del expected_object["marital_units"][marital_unit]["marital_unit_id"]

    for marital_unit in result_object["marital_units"]:
        del result_object["marital_units"][marital_unit]["marital_unit_id"]

    assert expected_object == result_object
