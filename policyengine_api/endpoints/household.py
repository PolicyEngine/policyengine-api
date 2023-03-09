from policyengine_api.country import COUNTRIES, validate_country
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import VERSION, COUNTRY_PACKAGE_VERSIONS
import json


def get_household(
    country_id: str, household_id: int = None, household_data: dict = None
) -> dict:
    """
    Get household data for a given country and household ID, or get the full record for a given household from its data.

    Args:
        country_id (str): The country ID.
        household_id (int, optional): The household ID. Defaults to None.
        household_data (dict, optional): The household data. Defaults to None.

    Returns:
        dict: The household record.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    household = None
    if household_id is not None:
        # Get the household record for a given household ID.
        household = database.get_in_table(
            "household", country_id=country_id, id=household_id
        )
        if household is None:
            return dict(
                status="error",
                message=f"Household {household_id} not found in {country_id}",
            )
    elif household_data is not None:
        # Get the household record for a given household data object.
        household = database.get_in_table(
            "household",
            country_id=country_id,
            household_hash=hash_object(household_data),
        )
        if household is None:
            return dict(
                status="error",
                message=f"Household not found in {country_id}",
            )
    else:
        return dict(
            status="error",
            message=f"Must provide either household_id or household_data",
        )
    household = dict(household)
    household["household_json"] = json.loads(household["household_json"])
    return dict(
        status="ok",
        message=None,
        result=household,
    )


def set_household(
    country_id: str, household_id: str, household_json: dict, label: str = None
) -> dict:
    """
    Set household data for a given country and household ID.

    Args:
        country_id (str): The country ID.
        household_json (dict): The household data.
        household_id (str, optional): The household ID. Defaults to None.
        label (str, optional): The household label. Defaults to None.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    household_invalid = validate_household(country_id, household_json)
    if household_invalid:
        return household_invalid

    household_hash = hash_object(household_json)
    database.set_in_table(
        "household",
        dict(id=household_id) if household_id is not None else {},
        dict(
            country_id=country_id,
            household_json=json.dumps(household_json),
            household_hash=household_hash,
            label=label,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        ),
        auto_increment="id",
    )

    household_id = database.get_in_table(
        "household", country_id=country_id, household_hash=household_hash
    )["id"]

    return dict(
        status="ok",
        message=None,
        result=dict(
            household_id=household_id,
        ),
    )


def validate_household(country_id: str, household_data: dict = None) -> dict:
    """
    Validate a household.

    Args:
        country_id (str): The country ID.
        household_data (dict, optional): The household data. Defaults to None.

    Returns:
        dict: The validation result.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    country_system = COUNTRIES[country_id].tax_benefit_system
    allowed_keys = [entity.plural for entity in country_system.entities] + [
        "axes"
    ]
    if not all(key in allowed_keys for key in household_data.keys()):
        return dict(
            status="error",
            message=f"Household data must contain only the following keys: {', '.join(allowed_keys)}. You provided: {', '.join(household_data.keys())}.",
        )
    return
