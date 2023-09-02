import pytest
import json
from policyengine_api.endpoints.household import get_household_under_policy
from policyengine_api.data import database
import sys

TEST_HOUSEHOLD_ID = -100

def create_test_household(household_id, country_id):
  test_household = None

  row = database.query(
    f"SELECT * FROM household WHERE id = ? AND country_id = ?",
    (household_id, country_id),
  ).fetchone()

  if row is not None:
    raise Exception("Record already exists at test index")
    
  with open("./tests/python/data/us_household.json", "r", encoding="utf-8") as f:
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
      raise Exception(err)
  
  return True


def test_us_household_under_policy():
  """
  Test that a US household under current law is created correctly
  """
  # Note: Attempted to mock the database.query statements in get_household_under_policy,
  # but was unable to, hence the (less secure) emission of SQL creation, followed by deletion

  expected_object = None
  with open("./tests/python/data/us_household_under_policy_target.json", "r", encoding="utf-8") as f:
    expected_object = json.load(f)

  create_test_household(
    TEST_HOUSEHOLD_ID,
    "us"
  )

  test_row = database.query(
    f"SELECT * FROM household WHERE id = ? AND country_id = ?",
    (TEST_HOUSEHOLD_ID, "us"),
  ).fetchone()

  result_object = get_household_under_policy(
    "us", 
    TEST_HOUSEHOLD_ID,
    2)
  
  remove_test_household(
    TEST_HOUSEHOLD_ID,
    "us"
  )
  
  assert expected_object == result_object["result"]
