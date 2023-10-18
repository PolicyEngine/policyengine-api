import pytest
import json

from policyengine_api.endpoints.household import get_household_under_policy
from policyengine_api.endpoints.metadata import get_metadata
from policyengine_api.endpoints.policy import get_policy
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data import database
from policyengine_api.api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


TEST_HOUSEHOLD_ID = "-100"


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


def interface_test_household_under_policy(country_id: str, current_law: str, excluded_vars: list):
    """
    Test that a household under current law contains all relevant 
    """
    # Note: Attempted to mock the database.query statements in get_household_under_policy,
    # but was unable to, hence the (less secure) emission of SQL creation, followed by deletion
    CURRENT_LAW = current_law

    # Value to invalidated if any key is not present in household
    is_test_passing = True

    # Fetch live country metadata
    metadata = get_metadata(country_id)["result"]

    # Create the test household on the local db instance
    create_test_household(TEST_HOUSEHOLD_ID, country_id)

    # Remove the created household from the db
    test_row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (TEST_HOUSEHOLD_ID, country_id),
    ).fetchone()

    # Create a result object by simply calling the relevant function
    result_object = get_household_under_policy(
        country_id, TEST_HOUSEHOLD_ID, CURRENT_LAW
    )["result"]

    # Remove the created test household
    remove_test_household(TEST_HOUSEHOLD_ID, country_id)
    remove_calculated_hup(TEST_HOUSEHOLD_ID, CURRENT_LAW, country_id)

    # Create a dict of entity singular and plural terms for testing
    entities_map = {}
    for entity in metadata["entities"]:
        entity_plural = metadata["entities"][entity]["plural"]
        entities_map[entity_plural] = entity

    # Create a set of all variables listed within the metadata that are yearly,
    # as well as one that will store all variables accessed while looping
    # Note: This removes issues with SNAP variables, which are calculated monthly
    var_filter = lambda x: (metadata["variables"][x]["definitionPeriod"] == "year") and x not in excluded_vars
    metadata_var_set = set(filter(var_filter, metadata["variables"].keys()))
    result_var_set = set()
    
    # Loop through every third-level variable in result_object
    for entity_group in result_object:
        for entity in result_object[entity_group]:
            entity_group_singularized = entities_map[entity_group]
            for variable in result_object[entity_group][entity]:
                # Skip ignored variables
                if (
                    variable in excluded_vars or
                    metadata["variables"][variable]["definitionPeriod"] != "year"
                ):
                    continue

                # Ensure that the variable exists in both 
                # result_object and test_object
                if variable not in metadata["variables"]:
                    print(f"Failing due to variable {variable} not in metadata")
                    is_test_passing = False
                    break

                # Ensure that variable exists within the correct
                # entity
                if (
                    variable not in excluded_vars and
                    entity_group_singularized != metadata["variables"][variable]["entity"]
                ):
                    print(f"Failing due to variable {variable} not in entity group {entity_group_singularized}")
                    is_test_passing = False
                    break
                
                # Add variable to result var set
                result_var_set.add(variable)

    if (result_var_set != metadata_var_set):
        results_diff = result_var_set.difference(metadata_var_set)
        metadata_diff = metadata_var_set.difference(result_var_set)
        if (len(results_diff) > 0):
          print("Error: The following values are only present in the result object:")
          print(results_diff)
        if (len(metadata_diff) > 0):
          print("Error: The following values are only present in the metadata:")
          print(metadata_diff)
        is_test_passing = False
                
    return is_test_passing

def test_us_household_under_policy():
    """
    Test that a US household under current law is created correctly
    """
    
    is_test_passing = interface_test_household_under_policy("us", "2", ["members"])

    assert is_test_passing == True

def test_uk_household_under_policy():
    """
    Test that a UK household under current law is created correctly
    """

    # The extra excluded variables all contain OpenFisca State entities,
    # necessitating their removal
    is_test_passing = interface_test_household_under_policy(
        "uk", 
        "1", 
        [
            "members",
            "property_sale_rate",
            "state_id",
            "state_weight"
        ]
      )

    assert is_test_passing == True

def test_get_calculate(client):
    """
    Test the get_calculate endpoint with the same data as
    test_us_household_under_policy. Note that redis must be running
    for this test to function properly.
    """

    CURRENT_LAW_US = "2"
    COUNTRY_ID = "us"

    test_household = None
    test_object = {}
    is_test_passing = True

    excluded_vars = ["members"]

    # Fetch live country metadata
    metadata = get_metadata(COUNTRY_ID)["result"]

    with open(
        f"./tests/python/data/us_household.json", "r", encoding="utf-8"
    ) as f:
        test_household = json.load(f)

    test_policy = get_policy("us", CURRENT_LAW_US)["result"]["policy_json"]

    test_object["policy"] = test_policy
    test_object["household"] = test_household

    res = client.post("/us/calculate", json=test_object)
    result_object = json.loads(res.text)["result"]

    # Create a dict of entity singular and plural terms for testing
    entities_map = {}
    for entity in metadata["entities"]:
        entity_plural = metadata["entities"][entity]["plural"]
        entities_map[entity_plural] = entity

    # Create a set of all variables listed within the metadata that are yearly,
    # as well as one that will store all variables accessed while looping
    # Note: This removes issues with SNAP variables, which are calculated monthly
    var_filter = lambda x: (metadata["variables"][x]["definitionPeriod"] == "year") and x not in excluded_vars
    metadata_var_set = set(filter(var_filter, metadata["variables"].keys()))
    result_var_set = set()
    
    # Loop through every third-level variable in result_object
    for entity_group in result_object:
        for entity in result_object[entity_group]:
            entity_group_singularized = entities_map[entity_group]
            for variable in result_object[entity_group][entity]:
                # Skip ignored variables
                if (
                    variable in excluded_vars or
                    metadata["variables"][variable]["definitionPeriod"] != "year"
                ):
                    continue

                # Ensure that the variable exists in both 
                # result_object and test_object
                if variable not in metadata["variables"]:
                    print(f"Failing due to variable {variable} not in metadata")
                    is_test_passing = False
                    break

                # Ensure that variable exists within the correct
                # entity
                if (
                    variable not in excluded_vars and
                    entity_group_singularized != metadata["variables"][variable]["entity"]
                ):
                    print(f"Failing due to variable {variable} not in entity group {entity_group_singularized}")
                    is_test_passing = False
                    break
                
                # Add variable to result var set
                result_var_set.add(variable)

    if (result_var_set != metadata_var_set):
        results_diff = result_var_set.difference(metadata_var_set)
        metadata_diff = metadata_var_set.difference(result_var_set)
        if (len(results_diff) > 0):
          print("Error: The following values are only present in the result object:")
          print(results_diff)
        if (len(metadata_diff) > 0):
          print("Error: The following values are only present in the metadata:")
          print(metadata_diff)
        is_test_passing = False
                
    assert is_test_passing == True