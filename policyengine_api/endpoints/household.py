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
import sys


def add_yearly_variables(household, country_id):
    """
    Add yearly variables to a household dict before enqueueing calculation
    """
    metadata = COUNTRIES.get(country_id).metadata["result"]

    variables = metadata["variables"]
    entities = metadata["entities"]
    household_year = get_household_year(household)

    for variable in variables:
        if variables[variable]["definitionPeriod"] in (
            "year",
            "month",
            "eternity",
        ):
            entity_plural = entities[variables[variable]["entity"]]["plural"]
            if entity_plural in household:
                possible_entities = household[entity_plural].keys()
                for entity in possible_entities:
                    if (
                        not variables[variable]["name"]
                        in household[entity_plural][entity]
                    ):
                        if variables[variable]["isInputVariable"]:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {
                                household_year: variables[variable][
                                    "defaultValue"
                                ]
                            }
                        else:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {household_year: None}
    return household


def get_household_year(household):
    """Given a household dict, get the household's year

    Args:
        household (dict): The household itself
    """
    return list(household["people"]["you"]["age"].keys())[0]


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

    response_body = dict(
        status="ok",
        message=None,
        result=dict(
            household_id=household_id,
        ),
    )
    return Response(
        json.dumps(response_body),
        status=201,
        mimetype="application/json",
    )


def update_household(country_id: str, household_id: str) -> Response:
    """
    Update a household via UPDATE request

    Args: country_id (str): The country ID
    """

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    # Fetch existing household first
    try:
        row = database.query(
            f"SELECT * FROM household WHERE id = ? AND country_id = ?",
            (household_id, country_id),
        ).fetchone()

        if row is not None:
            household = dict(row)
            household["household_json"] = json.loads(
                household["household_json"]
            )
            household["label"]
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
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error fetching household #{household_id} while updating: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    payload = request.json
    label = payload.get("label") or household["label"]
    household_json = payload.get("data") or household["household_json"]
    household_hash = hash_object(household_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    try:
        database.query(
            f"UPDATE household SET household_json = ?, household_hash = ?, label = ?, api_version = ? WHERE id = ?",
            (
                json.dumps(household_json),
                household_hash,
                label,
                api_version,
                household_id,
            ),
        )
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error fetching household #{household_id} while updating: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    response_body = dict(
        status="ok",
        message=None,
        result=dict(
            household_id=household_id,
        ),
    )
    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
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
            policy_id=row["policy_id"],
            household_id=row["household_id"],
            country_id=row["country_id"],
            api_version=row["api_version"],
            computed_household_json=row["computed_household_json"],
            status=row["status"],
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

    # Add in any missing yearly variables
    household["household_json"] = add_yearly_variables(
        household["household_json"], country_id
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
    except Exception:
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


def get_calculate(country_id: str, add_missing: bool = False) -> dict:
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

    if add_missing:
        # Add in any missing yearly variables to household_json
        household_json = add_yearly_variables(household_json, country_id)

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
