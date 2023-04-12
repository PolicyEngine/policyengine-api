from policyengine_api.country import (
    COUNTRIES,
    validate_country,
    PolicyEngineCountry,
)
from policyengine_api.data import database, local_database
import json
from flask import Response, request
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import sqlalchemy.exc
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_core.parameters import get_parameter
from policyengine_core.periods import instant
from policyengine_core.enums import Enum
from policyengine_api.country import PolicyEngineCountry, COUNTRIES
import json
import dpath
import math
import logging


def get_household(country_id: str, household_id: str) -> dict:
    """Get a household's input data with a given ID.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
    """
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    # Retrieve from the household table

    row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (household_id, country_id),
    ).fetchone()

    if row is not None:
        household = dict(row)
        household["household_json"] = json.loads(household["household_json"])
        return dict(
            status="ok",
            message=None,
            result=household,
        )
    else:
        response_body = dict(
            status="error",
            message=f"Household #{household_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )


def post_household(country_id: str) -> dict:
    """Set a household's input data.

    Args:
        country_id (str): The country ID.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    payload = request.json
    label = payload.get("label")
    household_json = payload.get("data")
    household_hash = hash_object(household_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

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
    except sqlalchemy.exc.IntegrityError:
        pass

    household_id = database.query(
        f"SELECT id FROM household WHERE country_id = ? AND household_hash = ?",
        (country_id, household_hash),
    ).fetchone()["id"]

    return dict(
        status="ok",
        message=None,
        result=dict(
            household_id=household_id,
        ),
    )


def get_household_under_policy(
    country_id: str, household_id: str, policy_id: str
):
    """Get a household's output data under a given policy.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
        policy_id (str): The policy ID.
    """
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    # Look in computed_households to see if already computed

    row = local_database.query(
        f"SELECT * FROM computed_household WHERE household_id = ? AND policy_id = ? AND api_version = ?",
        (household_id, policy_id, api_version),
    ).fetchone()

    if row is not None:
        result = dict(
            policy_id=row[0],
            household_id=row[1],
            country_id=row[2],
            api_version=row[3],
            computed_household_json=row[4],
            status=row[5],
        )
        result["result"] = json.loads(result["computed_household_json"])
        del result["computed_household_json"]
        return dict(
            status="ok",
            message=None,
            result=result["result"],
        )

    # Retrieve from the household table

    row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (household_id, country_id),
    ).fetchone()

    if row is not None:
        household = dict(row)
        household["household_json"] = json.loads(household["household_json"])
    else:
        response_body = dict(
            status="error",
            message=f"Household #{household_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    # Retrieve from the policy table

    row = database.query(
        f"SELECT * FROM policy WHERE id = ? AND country_id = ?",
        (policy_id, country_id),
    ).fetchone()

    if row is not None:
        policy = dict(row)
        policy["policy_json"] = json.loads(policy["policy_json"])
    else:
        response_body = dict(
            status="error",
            message=f"Policy #{policy_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    country = COUNTRIES.get(country_id)

    try:
        result = country.calculate(
            household["household_json"], policy["policy_json"]
        )
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error calculating household #{household_id} under policy #{policy_id}: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    # Store the result in the computed_household table

    try:
        local_database.query(
            f"INSERT INTO computed_household (country_id, household_id, policy_id, computed_household_json, api_version) VALUES (?, ?, ?, ?, ?)",
            (
                country_id,
                household_id,
                policy_id,
                json.dumps(result),
                api_version,
            ),
        )
    except sqlalchemy.exc.IntegrityError:
        # Update the result if it already exists
        local_database.query(
            f"UPDATE computed_household SET computed_household_json = ? WHERE country_id = ? AND household_id = ? AND policy_id = ?",
            (json.dumps(result), country_id, household_id, policy_id),
        )

    return dict(
        status="ok",
        message=None,
        result=result,
    )


def get_calculate(country_id: str) -> dict:
    """Lightweight endpoint for passing in household and policy JSON objects and calculating without storing data.

    Args:
        country_id (str): The country ID.
    """

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    payload = request.json
    household_json = payload.get("household", {})
    policy_json = payload.get("policy", {})

    country = COUNTRIES.get(country_id)

    try:
        result = country.calculate(household_json, policy_json)
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error calculating household under policy: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    return dict(
        status="ok",
        message=None,
        result=result,
    )
