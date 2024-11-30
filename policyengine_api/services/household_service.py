from sqlalchemy.engine.row import LegacyRow
import json
from policyengine_api.data import database

class HouseholdService:

  def get_household(self, country_id: str, household_id: int) -> dict | None:
    """
    Get a household's input data with a given ID.

    Args:
        country_id (str): The country ID.
        household_id (int): The household ID.
    """
    print("Getting household data")

    try:
        row: LegacyRow | None = database.query(
            f"SELECT * FROM household WHERE id = ? AND country_id = ?",
            (household_id, country_id),
        ).fetchone()
       
        # If row is present, we must JSON.loads the household_json
        household = None
        if row is not None:
            household = dict(row)
            if household["household_json"]:
              household["household_json"] = json.loads(household["household_json"])
        return household
    
    except Exception as e:
       print(f"Error fetching household #{household_id}. Details: {str(e)}")
       raise e
    
  def create_household(
      self,
      country_id: str,
      household_json: dict,
      household_hash: int,
      label: str | None,
      api_version: str,
  ) -> int:
      """
      Create a new household with the given data.

      Args:
          country_id (str): The country ID.
          household_json (dict): The household data.
          household_hash (int): The hash of the household data.
          label (str): The label for the household.
          api_version (str): The API version.
      """

      print("Creating new household")

      try:
          database.query(
              f"INSERT INTO household (country_id, household_json, household_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
              (
                  country_id,
                  json.dumps(household_json),
                  household_hash,
                  label,
                  api_version,
              ),
          )

          household_id = database.query(
              f"SELECT id FROM household WHERE country_id = ? AND household_hash = ?",
              (country_id, household_hash),
          ).fetchone()["id"]

          return household_id
      except Exception as e:
          print(f"Error creating household. Details: {str(e)}")
          raise e
